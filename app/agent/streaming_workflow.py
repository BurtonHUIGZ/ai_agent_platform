import asyncio
from typing import Dict, Any, List, TypedDict, Optional
from crewai import Crew

from app.agent.tasks import TASK_CONFIGS
from app.agent.agents import agents
from app.core.memory import memory, short_term_memory


def _get_task_factory():
    from app.agent.tasks import TaskFactory
    return TaskFactory(agents)


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


class StreamingWorkflow:
    def __init__(self, send_func):
        self.send_func = send_func

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
        task_id = state.get("task_id", "unknown")
        task = state["task"]

        prompt = f"""判断用户意图，只输出一个词：

任务类型选项：
- chat: 闲聊、问候、自我介绍、简单问答等简单对话
- task: 需要执行具体任务（写代码、写报告、分析、创作等）

用户输入：{task}

输出："""

        from app.agent.agents import researcher
        simple_task = _get_task_factory().create(
            "research_task",
            short_term_context="",
            related_memories="",
            task=prompt
        )
        crew = Crew(agents=[researcher], tasks=[simple_task], verbose=False)

        loop = asyncio.get_event_loop()
        task_type = await loop.run_in_executor(
            None, lambda: str(crew.kickoff())
        )

        task_type = "task" if "task" in task_type.lower() else "chat"

        await self.send_func(task_id, "thinking", "system", {
            "content": f"🎯 意图识别：{task_type}",
            "streaming": False
        })

        return {"task_type": task_type}

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

        short_term_memory.add(session_id, "user", task)
        short_term_memory.add(session_id, "assistant", result)

        if state.get("task_type") == "task":
            try:
                memory.add_memory(
                    user_id=user_id,
                    content=f"用户需求：{task}\n执行结果：{result}",
                    memory_type="task",
                    metadata={"task_id": task_id}
                )
            except Exception:
                pass

        return {}

    def build_workflow(self):
        from langgraph.graph import StateGraph, END

        wf = StateGraph(StreamingAgentState)

        wf.add_node("recall", self.recall_memories_node)
        wf.add_node("route", self.route_node)
        wf.add_node("chat", self.chat_node)
        wf.add_node("research", self.research_node)
        wf.add_node("execute", self.execute_node)
        wf.add_node("validate", self.validate_node)
        wf.add_node("manager", self.manager_node)
        wf.add_node("save_memory", self.save_memory_node)

        wf.set_entry_point("recall")
        wf.add_edge("recall", "route")

        wf.add_conditional_edges(
            "route",
            lambda state: state.get("task_type", "task"),
            {
                "chat": "chat",
                "task": "research"
            }
        )

        wf.add_edge("chat", "save_memory")
        wf.add_edge("research", "execute")
        wf.add_edge("execute", "validate")
        wf.add_edge("validate", "manager")
        wf.add_edge("manager", "save_memory")
        wf.add_edge("save_memory", END)

        return wf.compile()


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
