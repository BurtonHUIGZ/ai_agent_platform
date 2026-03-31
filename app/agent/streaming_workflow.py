import asyncio
from typing import Dict, Any, List, TypedDict
from crewai import Task, Crew
from app.core.memory import memory


class StreamingAgentState(TypedDict):
    task_id: str
    user_id: str
    task: str
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
        task = state["task"]
        task_id = state.get("task_id", "unknown")
        
        await self.send_func(task_id, "thinking", "system", {
            "content": "📚 开始检索相关记忆...",
            "streaming": False
        })
        
        try:
            memories = memory.retrieve_memories(
                user_id=user_id,
                query=task,
                top_k=3
            )
            related = [m["content"] for m in memories]
            memory_text = "\n".join([f"- {m}" for m in related]) if related else "（无相关记忆）"
            
            if related:
                await self.send_func(task_id, "thinking", "system", {
                    "content": f"✅ 检索到 {len(related)} 条相关记忆",
                    "streaming": False
                })
                for i, mem in enumerate(related):
                    preview = mem[:200] + "..." if len(mem) > 200 else mem
                    await self.send_func(task_id, "thinking", "memory", {
                        "content": f"【记忆{i+1}】{preview}",
                        "streaming": False
                    })
            else:
                await self.send_func(task_id, "thinking", "system", {
                    "content": "💭 无相关历史记忆，将从头开始分析",
                    "streaming": False
                })
        except Exception as e:
            await self.send_func(task_id, "thinking", "error", {
                "content": f"⚠️ 记忆检索失败: {e}",
                "streaming": False
            })
            memory_text = "（记忆检索失败）"
        
        return {"related_memories": [memory_text]}

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

    async def research_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import researcher
        
        memories_context = state.get("related_memories", ["（无相关记忆）"])[0]
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "agent_start", "researcher", {
            "role": "🔍 智能需求分析师",
            "content": "开始分析用户需求..."
        })

        prompt = f"""【用户历史记忆参考】
{memories_context}

【当前用户需求】
{state['task']}

你的任务：
1. 参考历史记忆，理解用户的习惯和偏好
2. 清晰理解用户需求
3. 给出最简单、最直接的落地方案
4. 不需要多余流程，直接告诉执行者应该输出什么
5. 全部使用中文输出
6. 展示你的完整思考过程

请详细展示你的思考过程。
"""

        task = Task(
            description=prompt,
            agent=researcher,
            expected_output="清晰的需求理解与可执行方案，中文"
        )

        crew = Crew(agents=[researcher], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(
            None, 
            lambda: self._run_crew_with_stream(crew, task_id, "researcher")
        )
        
        await self.send_func(task_id, "agent_end", "researcher", {
            "role": "🔍 智能需求分析师",
            "content": result_text
        })
        print(result_text)
        return {"research_result": result_text}

    async def execute_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import executor
        
        memories_context = state.get("related_memories", ["（无相关记忆）"])[0]
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "agent_start", "executor", {
            "role": "⚙️ 全能任务执行者",
            "content": "开始执行任务..."
        })

        prompt = f"""【用户历史记忆参考】
{memories_context}

【研究结果】
{state['research_result']}

规则：
- 参考历史记忆，注意用户的习惯和偏好
- 如果需求需要代码 → 写可运行代码
- 如果需求是创意/文案/报告/歌词 → 直接生成内容
- 如果需求是查询 → 直接给出结果
- 输出必须是中文
- 直接给最终内容，不要废话
- 展示你的执行思路和创作过程

请详细展示你的思考和创作过程。
"""

        task = Task(
            description=prompt,
            agent=executor,
            expected_output="直接输出最终结果，中文"
        )

        crew = Crew(agents=[executor], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(
            None, 
            lambda: self._run_crew_with_stream(crew, task_id, "executor")
        )
        
        await self.send_func(task_id, "agent_end", "executor", {
            "role": "⚙️ 全能任务执行者",
            "content": result_text
        })
        print(result_text)
        return {"execute_result": result_text}

    async def validate_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import validator
        
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "agent_start", "validator", {
            "role": "🧪 结果质量校验师",
            "content": "开始校验..."
        })

        prompt = f"""用户需求：{state['task']}
执行结果：{state['execute_result']}

检查：
1. 结果是否满足需求
2. 内容是否正确
3. 格式是否正常
4. 全部用中文给出校验结论
5. 展示你的校验思路

请详细展示你的校验思考过程。
"""

        task = Task(
            description=prompt,
            agent=validator,
            expected_output="中文校验报告"
        )

        crew = Crew(agents=[validator], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(
            None, 
            lambda: self._run_crew_with_stream(crew, task_id, "validator")
        )
        
        await self.send_func(task_id, "agent_end", "validator", {
            "role": "🧪 结果质量校验师",
            "content": result_text
        })
        print(result_text)
        return {"validate_result": result_text}

    async def manager_node(self, state: StreamingAgentState) -> Dict:
        from app.agent.agents import manager
        
        task_id = state.get("task_id", "unknown")

        await self.send_func(task_id, "agent_start", "manager", {
            "role": "📋 最终报告汇总师",
            "content": "开始汇总最终报告..."
        })

        prompt = f"""汇总所有结果，输出最终版答案：
用户需求：{state['task']}
执行结果：{state['execute_result']}
校验结果：{state['validate_result']}

要求：
1. 只输出用户真正想要的最终答案
2. 不要过程，不要多余分析
3. 100% 中文
4. 干净、整洁、可直接使用
"""

        task = Task(
            description=prompt,
            agent=manager,
            expected_output="最终答案，纯中文，直接可用"
        )

        crew = Crew(agents=[manager], tasks=[task], verbose=True)

        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(
            None, 
            lambda: self._run_crew_with_stream(crew, task_id, "manager")
        )
        
        await self.send_func(task_id, "agent_end", "manager", {
            "role": "📋 最终报告汇总师",
            "content": result_text
        })
        print(result_text)
        return {"final_report": result_text}

    async def save_memory_node(self, state: StreamingAgentState) -> Dict:
        user_id = state.get("user_id", "default")
        task = state["task"]
        result = state["final_report"]
        task_id = state.get("task_id", "unknown")
        
        memory_content = f"用户需求：{task}\n执行结果：{result}"
        
        await self.send_func(task_id, "thinking", "system", {
            "content": "💾 正在保存任务记忆...",
            "streaming": False
        })
        
        try:
            memory_id = memory.add_memory(
                user_id=user_id,
                content=memory_content,
                memory_type="task",
                metadata={
                    "task_id": task_id,
                    "task_preview": task[:100]
                }
            )
            await self.send_func(task_id, "thinking", "system", {
                "content": f"✅ 记忆已保存 (ID: {memory_id[:8]}...)",
                "streaming": False
            })
        except Exception as e:
            await self.send_func(task_id, "thinking", "error", {
                "content": f"⚠️ 记忆保存失败: {e}",
                "streaming": False
            })
        
        return {}

    def build_workflow(self):
        from langgraph.graph import StateGraph, END
        wf = StateGraph(StreamingAgentState)

        wf.add_node("recall", self.recall_memories_node)
        wf.add_node("research", self.research_node)
        wf.add_node("execute", self.execute_node)
        wf.add_node("validate", self.validate_node)
        wf.add_node("manager", self.manager_node)
        wf.add_node("save_memory", self.save_memory_node)

        wf.set_entry_point("recall")
        wf.add_edge("recall", "research")
        wf.add_edge("research", "execute")
        wf.add_edge("execute", "validate")
        wf.add_edge("validate", "manager")
        wf.add_edge("manager", "save_memory")
        wf.add_edge("save_memory", END)

        return wf.compile()


async def run_streaming_task(task_id: str, task_content: str, user_id: str, send_func):
    await send_func(task_id, "thinking", "system", {
        "content": "🚀 任务开始执行",
        "streaming": False
    })
    
    workflow = StreamingWorkflow(send_func)
    compiled = workflow.build_workflow()
    
    result = await compiled.ainvoke({
        "task_id": task_id,
        "user_id": user_id,
        "task": task_content,
        "related_memories": [],
        "research_result": "",
        "execute_result": "",
        "validate_result": "",
        "final_report": ""
    })
    
    await send_func(task_id, "complete", "system", {
        "content": "🎉 任务执行完成！",
        "result": result["final_report"]
    })
    
    return result["final_report"]
