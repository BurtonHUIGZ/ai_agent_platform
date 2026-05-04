import asyncio
import json
import re
import os
import time
from typing import Dict, Any, List, TypedDict, Optional
from crewai import Crew, Agent

from app.agent.tasks import TASK_CONFIGS
from app.agent.agents import agents
from app.core.memory import memory, short_term_memory, MAX_EMBEDDING_TOKENS, estimate_tokens
from app.core.rag_tools import search_knowledge_base
from app.core.eval_db import eval_db
from app.core.eval_types import FeedbackRecord
from app.llm.model_factory import llm, debug_llm_env
from app.core.rag_eval import rag_realtime_evaluator
from langchain_core.messages import HumanMessage
from app.settings import settings
from app.core.metrics import metrics

print(f"[DEBUG LLM ENV] {debug_llm_env()}")


def _get_task_factory():
    from app.agent.tasks import TaskFactory
    return TaskFactory(agents)


def _get_executor():
    from app.agent.agents import executor
    return executor


def load_prompts():
    from app.agent.tasks import load_prompts
    return load_prompts()


class RouteDecision(TypedDict):
    task_type: str
    reason: str
    need_memory: bool
    skip_research: bool
    skip_validate: bool
    skip_summary: bool
    agent_level: str
    response_style: str


class StreamingAgentState(TypedDict):
    task_id: str
    user_id: str
    session_id: str
    task: str
    task_type: str
    short_term_context: str
    related_memories: List[str]
    research_result: str
    plan: str
    plan_results: List[str]
    execute_result: str
    validate_result: str
    final_report: str
    route_decision: RouteDecision


class StreamingWorkflow:
    def __init__(self, send_func):
        self.send_func = send_func
        self.router = self._create_router_agent()

    def _create_router_agent(self) -> Agent:
        from app.agent.agents import router
        return router

    def _parse_route_decision(self, raw_output: str) -> RouteDecision:
        default_decision = {
            "task_type": "complex",
            "reason": "默认复杂任务",
            "need_memory": True,
            "skip_research": False,
            "skip_validate": False,
            "skip_summary": False,
            "agent_level": "expert",
            "response_style": "detailed"
        }

        try:
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw_output, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())
                key_map = {
                    "task_type": ["task_type", "task_类型", "类型"],
                    "reason": ["reason", "原因", "判断理由"],
                    "need_memory": ["need_memory", "需要内存", "需要记忆"],
                    "skip_research": ["skip_research", "跳过研究"],
                    "skip_validate": ["skip_validate", "跳过验证"],
                    "skip_summary": ["skip_summary", "跳过总结"],
                    "agent_level": ["agent_level", "代理级别", "agent级别"],
                    "response_style": ["response_style", "响应样式", "响应风格"]
                }

                def get_val(d, keys, default):
                    for k in keys:
                        if k in d:
                            return d[k]
                    return default

                return {
                    "task_type": get_val(decision, key_map["task_type"], "complex"),
                    "reason": get_val(decision, key_map["reason"], ""),
                    "need_memory": get_val(decision, key_map["need_memory"], True),
                    "skip_research": get_val(decision, key_map["skip_research"], False),
                    "skip_validate": get_val(decision, key_map["skip_validate"], False),
                    "skip_summary": get_val(decision, key_map["skip_summary"], False),
                    "agent_level": get_val(decision, key_map["agent_level"], "expert"),
                    "response_style": get_val(decision, key_map["response_style"], "detailed")
                }
        except (json.JSONDecodeError, KeyError) as e:
            pass

        return default_decision

    async def recall_memories_node(self, state: StreamingAgentState) -> Dict:
        user_id = state.get("user_id", "default")
        session_id = state.get("session_id", user_id)
        task = state["task"]
        task_id = state.get("task_id", "unknown")

        short_term_context = ""
        try:
            short_term_msgs = short_term_memory.get_messages(session_id, last_n=10)
            if short_term_msgs:
                short_term_context = "\n".join([
                    f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
                    for m in short_term_msgs
                ])
        except Exception:
            pass

        memory_text = ""
        try:
            # 使用混合检索 + 重排序
            all_memories = memory.hybrid_retrieve(
                user_id=user_id,
                query=task,
                top_k=5,
                user_top_k=5,
                kb_top_k=5
            )
            
            if all_memories:
                related = [m.get("full_content", m["content"]) for m in all_memories]
                memory_text = "\n".join([f"- {m}" for m in related])
            else:
                memory_text = ""
        except Exception as e:
            print(f"[recall_memories] 混合检索失败: {e}")
            memory_text = ""

        combined = []
        if short_term_context:
            combined.append(f"【近期对话】\n{short_term_context}")
        if memory_text:
            combined.append(f"【历史记忆】\n{memory_text}")

        return {"short_term_context": "\n\n".join(combined), "related_memories": [memory_text]}

    async def route_node(self, state: StreamingAgentState) -> Dict:

        task = state["task"]
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "thinking", "router", {
            "content": "🎯 分析任务意图...",
            "streaming": False
        })

        from app.agent.tasks import load_prompts
        prompts = load_prompts()
        route_prompt = prompts.get("route", "").format(task=task)

        raw_output = ""
        try:
            loop = asyncio.get_event_loop()
            from app.settings import settings
            if settings.ACTIVE_PROVIDER == "OLLAMA":
                from langchain_core.messages import HumanMessage
                response = await loop.run_in_executor(
                    None,
                    lambda: llm.invoke([HumanMessage(content=route_prompt)])
                )
                raw_output = response.content if hasattr(response, 'content') else str(response)
            else:
                response = await loop.run_in_executor(
                    None,
                    lambda: llm.call(route_prompt)
                )
                raw_output = response.content if hasattr(response, 'content') else str(response)

            route_decision = self._parse_route_decision(raw_output)
            task_type = route_decision["task_type"]

            print(f"[ROUTER] raw_output: {raw_output[:200]}...")
            print(f"[ROUTER] task_type: {task_type}, reason: {route_decision['reason']}")

            await self.send_func(task_id, "thinking", "router", {
                "content": f"✅ 路由决策：{task_type} | {route_decision['reason']}",
                "streaming": False
            })

            return {
                "task_type": task_type,
                "route_decision": route_decision
            }
        except Exception as e:
            import loguru
            logger = loguru.logger
            logger.error(f"路由分析失败: {e}\nraw_output: {raw_output}")
            await self.send_func(task_id, "thinking", "router", {
                "content": f"⚠️ 路由分析失败，使用默认决策: {str(e)}",
                "streaming": False
            })
            default = {
                "task_type": "complex",
                "reason": "路由失败，默认复杂任务",
                "need_memory": True,
                "skip_research": False,
                "skip_validate": False,
                "skip_summary": False,
                "agent_level": "expert",
                "response_style": "detailed"
            }
            return {
                "task_type": "complex",
                "route_decision": default
            }

    def _run_crew_with_stream(self, crew: Crew, task_id: str, agent_name: str) -> str:
        import sys

        class StreamBuffer:
            def __init__(self, send_func, tid, agent):
                self.send_func = send_func
                self.tid = tid
                self.agent = agent
                self.buffer = []

            def write(self, text):
                if text.strip():
                    self.buffer.append(text)
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(self.send_func(self.tid, "thinking", self.agent, {
                                "content": text,
                                "streaming": True
                            }))
                    except:
                        pass

            def flush(self):
                pass

        stream = StreamBuffer(self.send_func, task_id, agent_name)
        old_stdout = sys.stdout
        sys.stdout = stream

        try:
            result = crew.kickoff()
        finally:
            sys.stdout = old_stdout

        return str(result)

    async def chat_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor

        start_time = time.time()
        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        task = state["task"]

        prompt = f"""{short_term_context}

{memories_context}

用户：{task}

请直接回答用户，不需要执行任何任务。"""

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "💬 助手",
            "content": "回复中..."
        })

        simple_task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=prompt
        )
        crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": "💬 助手", "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("chat", duration)
        return {"final_report": result_text}

    async def research_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import researcher

        start_time = time.time()
        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        cfg = TASK_CONFIGS["research_task"]

        await self.send_func(task_id, "agent_start", "researcher", {
            "role": cfg["role_zh"],
            "content": cfg["start_msg"]
        })

        task = _get_task_factory().create(
            "research_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            task=state["task"]
        )

        crew = Crew(agents=[researcher], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "researcher"))

        await self.send_func(task_id, "agent_end", "researcher", {"role": cfg["role_zh"], "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("researcher", duration)
        return {"research_result": result_text}

    async def execute_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import agents

        start_time = time.time()
        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        cfg = TASK_CONFIGS["execute_task"]

        await self.send_func(task_id, "agent_start", "executor", {
            "role": cfg["role_zh"],
            "content": cfg["start_msg"]
        })

        task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=state["research_result"]
        )

        crew = Crew(
            agents=[agents["executor"], agents["validator"]],
            tasks=[task],
            verbose=True
        )

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": cfg["role_zh"], "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("executor", duration)
        return {"execute_result": result_text}

    async def validate_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import validator

        start_time = time.time()
        task_id = state.get("task_id", "unknown")
        cfg = TASK_CONFIGS["validate_task"]

        await self.send_func(task_id, "agent_start", "validator", {
            "role": cfg["role_zh"],
            "content": cfg["start_msg"]
        })

        task = _get_task_factory().create(
            "validate_task",
            task=state["task"],
            execute_result=state["execute_result"]
        )

        crew = Crew(agents=[validator], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "validator"))

        await self.send_func(task_id, "agent_end", "validator", {"role": cfg["role_zh"], "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("validator", duration)
        return {"validate_result": result_text}

    async def manager_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import manager

        start_time = time.time()
        task_id = state.get("task_id", "unknown")
        cfg = TASK_CONFIGS["summarize_task"]

        await self.send_func(task_id, "agent_start", "manager", {
            "role": cfg["role_zh"],
            "content": cfg["start_msg"]
        })

        task = _get_task_factory().create(
            "summarize_task",
            task=state["task"],
            execute_result=state["execute_result"],
            validate_result=state["validate_result"]
        )

        crew = Crew(agents=[manager], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "manager"))

        await self.send_func(task_id, "agent_end", "manager", {"role": cfg["role_zh"], "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("manager", duration)
        return {"final_report": result_text, "task_type": state.get("task_type", "complex")}

    async def plan_node(self, state: StreamingAgentState) -> Dict:

        start_time = time.time()
        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        task = state["task"]

        await self.send_func(task_id, "agent_start", "planner", {
            "role": "📝 规划师",
            "content": "正在生成执行计划..."
        })

        prompts = load_prompts()
        plan_prompt = prompts.get("plan", "").format(
            short_term_context=short_term_context,
            related_memories=memories_context,
            task=task
        )

        loop = asyncio.get_event_loop()
        if settings.ACTIVE_PROVIDER == "OLLAMA":
            response = await loop.run_in_executor(
                None,
                lambda: llm.invoke([HumanMessage(content=plan_prompt)])
            )
            result_text = response.content if hasattr(response, 'content') else str(response)
        else:
            response = await loop.run_in_executor(
                None,
                lambda: llm.call(plan_prompt)
            )
            result_text = response.content if hasattr(response, 'content') else str(response)

        await self.send_func(task_id, "agent_end", "planner", {"role": "📝 规划师", "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("planner", duration)
        return {"plan": result_text, "plan_results": []}

    async def execute_plan_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor

        start_time = time.time()
        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        plan = state.get("plan", "")
        cfg = TASK_CONFIGS["execute_task"]

        await self.send_func(task_id, "agent_start", "executor", {
            "role": cfg["role_zh"],
            "content": "正在执行计划..."
        })

        prompts = load_prompts()
        execute_prompt = prompts.get("execute_plan", "").format(
            short_term_context=short_term_context,
            related_memories=memories_context,
            plan=plan
        )

        task_obj = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=execute_prompt
        )
        crew = Crew(agents=[executor], tasks=[task_obj], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": cfg["role_zh"], "content": result_text})
        duration = time.time() - start_time
        metrics.record_agent("execute_plan", duration)
        return {"execute_result": result_text, "plan_results": [result_text]}

    async def save_memory_node(self, state: StreamingAgentState) -> Dict:
        user_id = state.get("user_id", "default")
        session_id = state.get("session_id", user_id)
        task = state["task"]
        result = state.get("final_report", "")
        task_id = state.get("task_id", "unknown")
        route_decision = state.get("route_decision", {})
        task_type = route_decision.get("task_type", "complex")

        print(f"[save_memory] task_type={task_type}, task={task[:30]}...")

        short_term_memory.add(session_id, "user", task)
        short_term_memory.add(session_id, "assistant", result)

        token_count = short_term_memory.get_token_count(session_id)
        if token_count > 500:
            short_term_memory.compress_context(session_id, compress_threshold=15)

        try:
            task_type_to_memory_type = {
                "complex": "task",
                "simple": "task",
                "question": "question",
                "chat": "conversation"
            }
            memory_type = task_type_to_memory_type.get(task_type, "conversation")

            if memory_type == "task":
                if len(result) > MAX_EMBEDDING_TOKENS:
                    from app.settings import settings
                    try:
                        loop = asyncio.get_event_loop()
                        if settings.ACTIVE_PROVIDER == "OLLAMA":
                            from langchain_core.messages import HumanMessage
                            response = await loop.run_in_executor(
                                None,
                                lambda: llm.invoke([HumanMessage(content=f"用30字以内总结：{result[:MAX_EMBEDDING_TOKENS]}")])
                            )
                        else:
                            response = await loop.run_in_executor(
                                None,
                                lambda: llm.call(f"用30字以内总结：{result[:MAX_EMBEDDING_TOKENS]}")
                            )
                        summary = response.content if hasattr(response, 'content') else str(response)
                        print(f"[save_memory] 摘要生成成功: {summary}")
                        content = f"用户需求：{task[:500]}\n摘要：{summary}"
                    except Exception as e:
                        import traceback
                        print(f"[save_memory] 摘要生成失败: {e}")
                        traceback.print_exc()
                        content = f"用户需求：{task[:500]}\n执行结果：{result[:2000]}...[已截断]"
                else:
                    content = f"用户需求：{task[:500]}\n执行结果：{result}"
                    
                if len(content) > 3500:
                    content = content[:3500] + "...[已截断]"
            elif memory_type == "question":
                content = f"用户问题：{task}\n回答：{result[:1000]}"
            else:
                content = f"用户：{task}\n助手：{result}"
                if len(content) > 3500:
                    content = content[:3500] + "..."
            
            print(f"[save_memory] 准备保存 memory_type={memory_type}, task_type={task_type}, content_len={len(content)}")

            if memory_type == "task":
                memory_id = memory.add_memory(
                    user_id=user_id,
                    content=content,
                    full_content=f"用户需求：{task}\n执行结果：{result}",
                    memory_type="task",
                    metadata={"task_id": task_id, "original_task_type": task_type}
                )
                print(f"[save_memory] 已保存 task 记忆, id={memory_id}")
            elif memory_type == "question":
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户问题：{task}\n回答：{result}",
                    full_content=f"用户问题：{task}\n回答：{result}",
                    memory_type="question",
                    metadata={"task_id": task_id}
                )
            else:
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户：{task}\n助手：{result}",
                    full_content=f"用户：{task}\n助手：{result}",
                    memory_type="conversation",
                    metadata={"session_id": session_id, "original_task_type": task_type}
                )
        except Exception as e:
            import traceback
            print(f"[save_memory] 错误: {e}")
            traceback.print_exc()

        return {}

    def _route_decision(self, state: StreamingAgentState) -> str:
        task_type = state.get("task_type", "complex")
        route_decision = state.get("route_decision", {})
        skip_research = route_decision.get("skip_research", False)
        skip_validate = route_decision.get("skip_validate", False)

        if task_type == "chat":
            return "chat"
        elif task_type == "question":
            return "rag_vote"
        elif task_type == "plan_execute":
            return "plan_execute"
        elif task_type == "simple":
            if skip_research:
                return "execute_skip_research"
            return "research"
        else:
            if skip_research:
                if skip_validate:
                    return "execute_skip_research_validate"
                return "execute_skip_research"
            if skip_validate:
                return "execute_skip_validate"
            return "research"

    def build_workflow(self):
        """
        构建 LangGraph 状态图工作流。

        工作流节点:
        - recall: 回忆相关记忆
        - route: 根据任务类型路由到不同处理路径
        - chat: 对话模式 (简单问答)
        - rag_vote: RAG检索模式 (知识库查询)
        - research: 研究模式 (需要搜索外部信息)
        - execute: 执行模式 (代码执行)
        - execute_direct: 直接执行 (无需研究，直接执行)
        - execute_skip_research: 跳过研究执行
        - execute_skip_research_validate: 跳过研究验证执行
        - execute_skip_validate: 跳过验证执行
        - validate: 验证执行结果
        - manager: 管理执行结果
        - save_memory: 保存对话记忆

        工作流执行流程:
        1. recall -> route: 加载记忆并路由
        2. route 根据任务类型选择:
           - chat: 对话模式
           - rag_vote: RAG检索
           - execute_direct: 直接执行
           - execute_skip_research: 跳过研究执行
           - execute_skip_research_validate: 跳过研究验证执行
           - execute_skip_validate: 跳过验证执行
           - research: 研究后执行
        3. 执行完成后进行验证
        4. manager 处理结果
        5. save_memory 保存记忆
        """
        from langgraph.graph import StateGraph, END

        # 创建状态图，使用 StreamingAgentState 作为状态类型
        # StateGraph 是 LangGraph 的核心类，用于构建有向无环图 (DAG)
        wf = StateGraph(StreamingAgentState)

        # add_node(name, handler): 添加节点到图中
        # - name: 节点名称（字符串），用于标识和引用该节点
        # - handler: 节点的处理函数（async 函数），接收当前状态并返回更新后的状态
        # 节点是工作流中的基本执行单元，每个节点处理特定的任务
        # recall: 检索相关记忆
        wf.add_node("recall", self.recall_memories_node)
        # route: 路由决策，判断任务类型
        wf.add_node("route", self.route_node)
        # chat: 对话模式，处理简单问答
        wf.add_node("chat", self.chat_node)
        # rag_vote: RAG检索模式，从知识库获取信息
        wf.add_node("rag_vote", self.rag_vote_node)
        # research: 研究模式，搜索外部信息
        wf.add_node("research", self.research_node)
        # execute: 执行模式，运行代码
        wf.add_node("execute", self.execute_node)
        # execute_direct: 直接执行模式，无需研究
        wf.add_node("execute_direct", self.execute_direct_node)
        # execute_skip_research: 跳过研究直接执行
        wf.add_node("execute_skip_research", self.execute_skip_research_node)
        # execute_skip_research_validate: 跳过研究验证执行
        wf.add_node("execute_skip_research_validate", self.execute_skip_research_validate_node)
        # execute_skip_validate: 跳过验证执行
        wf.add_node("execute_skip_validate", self.execute_skip_validate_node)
        # validate: 验证执行结果
        wf.add_node("validate", self.validate_node)
        # manager: 管理执行结果
        wf.add_node("manager", self.manager_node)
        # save_memory: 保存对话记忆
        wf.add_node("save_memory", self.save_memory_node)

        # set_entry_point(name): 设置工作流的入口节点
        # 工作流从该节点开始执行
        wf.set_entry_point("recall")

        # add_edge(source, target): 添加普通边，连接两个节点
        # - source: 源节点名称
        # - target: 目标节点名称
        # 表示从源节点执行完毕后，无条件转移到目标节点
        # recall 执行完后进入 route 节点
        wf.add_edge("recall", "route")

        # add_conditional_edges(source, condition_fn, mapping): 添加条件边
        # - source: 源节点名称
        # - condition_fn: 条件函数，接收当前状态，返回路由目标（mapping 中的某个 key）
        # - mapping: 路由目标映射表 {返回值: 目标节点名, ...}
        # 根据条件函数的返回值，决定下一步流向哪个节点
        # route 节点根据 _route_decision 返回值进行条件路由
        wf.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "chat": "chat",
                "rag_vote": "rag_vote",
                "plan_execute": "plan_execute",
                "execute_direct": "execute_direct",
                "execute_skip_research": "execute_skip_research",
                "execute_skip_research_validate": "execute_skip_research_validate",
                "execute_skip_validate": "execute_skip_validate",
                "research": "research"
            }
        )

        # Plan-and-Execute flow
        wf.add_node("plan_execute", self.plan_node)
        wf.add_edge("plan_execute", "execute_plan")
        wf.add_node("execute_plan", self.execute_plan_node)
        wf.add_edge("execute_plan", "validate")

        # chat 和 rag_vote 完成后保存记忆
        wf.add_edge("chat", "save_memory")
        wf.add_edge("rag_vote", "save_memory")

        # execute_direct 根据 skip_validate 决定是否验证
        wf.add_conditional_edges(
            "execute_direct",
            lambda state: "manager" if state.get("route_decision", {}).get("skip_validate", False) else "validate",
            {
                "validate": "validate",
                "manager": "manager"
            }
        )

        # 其他执行路径的边
        # execute_skip_research: 验证后管理
        wf.add_edge("execute_skip_research", "validate")
        # execute_skip_research_validate: 直接到管理
        wf.add_edge("execute_skip_research_validate", "manager")
        # execute_skip_validate: 直接到管理
        wf.add_edge("execute_skip_validate", "manager")
        # research: 研究后执行
        wf.add_edge("research", "execute")
        # execute: 执行后验证
        wf.add_edge("execute", "validate")
        # validate: 验证后管理
        wf.add_edge("validate", "manager")
        # manager: 管理后保存记忆
        wf.add_edge("manager", "save_memory")
        # save_memory: 结束工作流
        wf.add_edge("save_memory", END)

        return wf.compile()

    async def execute_direct_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor

        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        task = state["task"]
        route_decision = state.get("route_decision", {})
        
        skip_validate = route_decision.get("skip_validate", False)
        agent_level = route_decision.get("agent_level", "expert")
        response_style = route_decision.get("response_style", "detailed")

        style_hint = "简洁" if response_style == "brief" else "详细"
        level_hint = "使用简单易懂的语言" if agent_level == "simple" else "可以使用专业术语"

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "💡 直接回答",
            "content": "正在分析问题..."
        })

        prompt = f"""{short_term_context}

{memories_context}

用户问题：{task}

请回答用户问题。{level_hint}。回答风格：{style_hint}。"""

        simple_task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=prompt
        )
        crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": "💡 直接回答", "content": result_text})
        
        if skip_validate:
            return {"final_report": result_text}
        return {"execute_result": result_text}

    async def rag_vote_node(self, state: StreamingAgentState) -> Dict:
        task = state["task"]
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "thinking", "router", {
            "content": "🔍 多路检索+投票中...",
            "streaming": False
        })

        try:
            rag_result = search_knowledge_base.invoke(task)
        except Exception:
            rag_result = "检索失败"

        try:
            executor = _get_executor()
            web_prompt = f"请搜索网络回答用户问题：{task}"
            simple_task = _get_task_factory().create(
                "execute_task",
                short_term_context="",
                related_memories="",
                research_result=web_prompt
            )
            crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)
            loop = asyncio.get_event_loop()
            web_result = await loop.run_in_executor(None, lambda: crew.kickoff())
        except Exception as e:
            web_result = f"搜索失败: {e}"

        try:
            executor = _get_executor()
            direct_prompt = f"请直接回答用户问题：{task}"
            simple_task = _get_task_factory().create(
                "execute_task",
                short_term_context="",
                related_memories="",
                research_result=direct_prompt
            )
            crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)
            loop = asyncio.get_event_loop()
            direct_result = await loop.run_in_executor(None, lambda: crew.kickoff())
        except Exception as e:
            direct_result = f"回答失败: {e}"

        prompts = load_prompts()
        vote_prompt = prompts.get("route_question", "").format(
            rag_result=rag_result,
            web_result=str(web_result),
            direct_result=str(direct_result),
            task=task
        )

        try:
            loop = asyncio.get_event_loop()
            if settings.ACTIVE_PROVIDER == "OLLAMA":
                from langchain_core.messages import HumanMessage
                response = await loop.run_in_executor(
                    None,
                    lambda: llm.invoke([HumanMessage(content=vote_prompt)])
                )
                vote_result = response.content if hasattr(response, 'content') else str(response)
            else:
                response = await loop.run_in_executor(
                    None,
                    lambda: llm.call(vote_prompt)
                )
                vote_result = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            vote_result = f"投票失败: {e}"

        import re
        import json
        winner = "rag"
        try:
            json_match = re.search(r'\{[^{}]*\}', vote_result, re.DOTALL)
            if json_match:
                vote_data = json.loads(json_match.group())
                winner = vote_data.get("winner", "rag")
        except Exception:
            pass

        await self.send_func(task_id, "thinking", "router", {
            "content": f"✅ 投票结果: {winner}",
            "streaming": False
        })

        if winner == "web":
            final_result = str(web_result)
        elif winner == "direct":
            final_result = str(direct_result)
        else:
            final_result = rag_result

        return {"final_report": final_result}

    async def execute_skip_research_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor

        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        task = state["task"]

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "⚡ 快速执行",
            "content": "跳过研究阶段，直接执行..."
        })

        prompt = f"""{short_term_context}

{memories_context}

用户需求：{task}

请直接执行任务，不需要额外研究。"""

        simple_task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=prompt
        )
        crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": "⚡ 快速执行", "content": result_text})
        return {"execute_result": result_text}

    async def execute_skip_research_validate_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor, manager

        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        task = state["task"]

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "⚡ 快速执行",
            "content": "直接执行并汇总结果..."
        })

        prompt = f"""{short_term_context}

{memories_context}

用户需求：{task}

请直接执行任务并输出最终结果。"""

        simple_task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=prompt
        )
        crew = Crew(agents=[executor], tasks=[simple_task], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": "⚡ 快速执行", "content": result_text})
        return {"execute_result": result_text, "final_report": result_text}

    async def execute_skip_validate_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor

        short_term_context = state.get("short_term_context", "")
        memories_context = state.get("related_memories", [""])[0]
        task_id = state.get("task_id", "unknown")
        research_result = state.get("research_result", "")

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "⚙️ 执行任务",
            "content": "执行中（跳过验证）..."
        })

        task = _get_task_factory().create(
            "execute_task",
            short_term_context=short_term_context,
            related_memories=memories_context,
            research_result=research_result
        )

        crew = Crew(agents=[executor], tasks=[task], verbose=False)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, lambda: self._run_crew_with_stream(crew, task_id, "executor"))

        await self.send_func(task_id, "agent_end", "executor", {"role": "⚙️ 执行任务", "content": result_text})
        return {"execute_result": result_text}


async def run_streaming_task(task_id: str, task_content: str, user_id: str, send_func,
                             session_id: Optional[str] = None):
    if session_id is None:
        session_id = user_id

    metrics.inc_concurrent()
    start_time = time.time()
    task_type = "unknown"

    try:
        await send_func(task_id, "thinking", "system", {
            "content": "🚀 开始处理",
            "streaming": False
        })

        workflow = StreamingWorkflow(send_func)
        compiled = workflow.build_workflow()

        result = await compiled.ainvoke({
            "task_id": task_id,
            "user_id": user_id,
            "session_id": session_id,
            "task": task_content,
            "task_type": "task",
            "short_term_context": "",
            "related_memories": [],
            "research_result": "",
            "execute_result": "",
            "validate_result": "",
            "final_report": ""
        })

        task_type = result.get("task_type", "task")
        
        final_report = result.get("final_report", "")
        
        await send_func(task_id, "complete", "system", {
            "content": "✨ 完成",
            "result": final_report
        })
        
        try:
            loop = asyncio.get_event_loop()
            retrieved_results = memory.retrieve_memories(
                user_id=user_id,
                query=task_content,
                top_k=5
            )
            eval_result = await loop.run_in_executor(
                None,
                lambda: rag_realtime_evaluator.evaluate_response(
                    query=task_content,
                    response=final_report,
                    retrieved_docs=retrieved_results,
                    session_id=session_id
                )
            )
            print(f"[RAG评估] 回答评估完成: {eval_result.get('overall_score', 'N/A')}")
            
            await send_func(task_id, "rag_eval", "system", {
                "content": "RAG评估完成",
                "eval_result": eval_result
            })
        except Exception as eval_error:
            print(f"[RAG评估] 回答评估失败: {eval_error}")
        
        return final_report
    except Exception as e:
        task_type = "error"
        raise
    finally:
        duration = time.time() - start_time
        status = "error" if task_type == "error" else "success"
        metrics.record_task(task_type, status, duration)
        metrics.dec_concurrent()
        
        final_response = ""
        if "result" in locals() and result:
            final_response = result.get("final_report", "")[:500]
        
        try:
            retrieved_results = memory.retrieve_memories(
                user_id=user_id,
                query=task_content,
                top_k=5
            )
            retrieved_doc_ids = [r["id"] for r in retrieved_results]
            eval_db.add_feedback(FeedbackRecord(
                session_id=session_id,
                query=task_content,
                response=final_response,
                retrieved_doc_ids=retrieved_doc_ids,
                retrieved_doc_count=len(retrieved_doc_ids),
                latency_ms=duration * 1000
            ))
        except Exception as e:
            print(f"[EVAL] Feedback record failed: {e}")
