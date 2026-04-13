import asyncio
import json
import re
import os
from typing import Dict, Any, List, TypedDict, Optional
from crewai import Crew, Agent

from app.agent.tasks import TASK_CONFIGS
from app.agent.agents import agents
from app.core.memory import memory, short_term_memory
from app.core.rag_tools import search_knowledge_base
from app.llm.model_factory import llm, debug_llm_env
from app.settings import settings

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
            memories = memory.retrieve_memories(user_id=user_id, query=task, top_k=3)
            related = [m["content"] for m in memories]
            memory_text = "\n".join([f"- {m}" for m in related]) if related else ""
        except Exception:
            pass

        return {"short_term_context": short_term_context, "related_memories": [memory_text]}

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
        return {"final_report": result_text}

    async def research_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import researcher

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
        return {"research_result": result_text}

    async def execute_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import agents

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
        return {"execute_result": result_text}

    async def validate_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import validator

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
        return {"validate_result": result_text}

    async def manager_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import manager

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
        return {"final_report": result_text}

    async def save_memory_node(self, state: StreamingAgentState) -> Dict:
        user_id = state.get("user_id", "default")
        session_id = state.get("session_id", user_id)
        task = state["task"]
        result = state.get("final_report", "")
        task_id = state.get("task_id", "unknown")
        task_type = state.get("task_type", "task")

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
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户需求：{task}\n执行结果：{result}",
                    memory_type="task",
                    metadata={"task_id": task_id, "original_task_type": task_type}
                )
            elif memory_type == "question":
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户问题：{task}\n回答：{result}",
                    memory_type="question",
                    metadata={"task_id": task_id}
                )
            else:
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户：{task}\n助手：{result}",
                    memory_type="conversation",
                    metadata={"session_id": session_id, "original_task_type": task_type}
                )
        except Exception:
            pass

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
        from langgraph.graph import StateGraph, END

        wf = StateGraph(StreamingAgentState)

        wf.add_node("recall", self.recall_memories_node)
        wf.add_node("route", self.route_node)
        wf.add_node("chat", self.chat_node)
        wf.add_node("rag_vote", self.rag_vote_node)
        wf.add_node("research", self.research_node)
        wf.add_node("execute", self.execute_node)
        wf.add_node("execute_direct", self.execute_direct_node)
        wf.add_node("execute_skip_research", self.execute_skip_research_node)
        wf.add_node("execute_skip_research_validate", self.execute_skip_research_validate_node)
        wf.add_node("execute_skip_validate", self.execute_skip_validate_node)
        wf.add_node("validate", self.validate_node)
        wf.add_node("manager", self.manager_node)
        wf.add_node("save_memory", self.save_memory_node)

        wf.set_entry_point("recall")
        wf.add_edge("recall", "route")

        wf.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "chat": "chat",
                "rag_vote": "rag_vote",
                "execute_direct": "execute_direct",
                "execute_skip_research": "execute_skip_research",
                "execute_skip_research_validate": "execute_skip_research_validate",
                "execute_skip_validate": "execute_skip_validate",
                "research": "research"
            }
        )

        wf.add_edge("chat", "save_memory")
        wf.add_edge("rag_vote", "save_memory")
        wf.add_conditional_edges(
            "execute_direct",
            lambda state: "manager" if state.get("route_decision", {}).get("skip_validate", False) else "validate",
            {
                "validate": "validate",
                "manager": "manager"
            }
        )
        wf.add_edge("execute_skip_research", "validate")
        wf.add_edge("execute_skip_research_validate", "manager")
        wf.add_edge("execute_skip_validate", "manager")
        wf.add_edge("research", "execute")
        wf.add_edge("execute", "validate")
        wf.add_edge("validate", "manager")
        wf.add_edge("manager", "save_memory")
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

    await send_func(task_id, "complete", "system", {
        "content": "✨ 完成",
        "result": result["final_report"]
    })

    return result["final_report"]
