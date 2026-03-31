from langgraph.graph import StateGraph, END
from typing import TypedDict
from crewai import Task, Crew

from app.core.task_queue import add_log


def get_agents():
    from app.agent.agents import researcher, executor, validator, manager
    return researcher, executor, validator, manager


# 🔥 全局通用状态（不绑定任何业务！）
class AgentState(TypedDict):
    task_id: str  # 任务唯一id
    task: str  # 用户任意需求（写歌/查天气/写代码/分析）
    research_result: str  # 研究：需求理解 + 执行方案
    execute_result: str  # 执行：核心结果（自动判断要不要写代码）
    validate_result: str  # 校验：结果是否正确
    final_report: str  # 最终报告（中文）


# ------------------------------------------------------------------------------
# 🔥 节点1：研究员（通用：理解任何需求）
# ------------------------------------------------------------------------------
def research_node(state):
    researcher, _, _, _ = get_agents()

    task = Task(
        description=f"""
用户需求：{state['task']}

你的任务：
1. 清晰理解用户需求
2. 给出最简单、最直接的落地方案
3. 不需要多余流程，直接告诉执行者应该输出什么
4. 全部使用中文输出

输出格式：
【需求理解】
【执行方案】
""",
        agent=researcher,
        expected_output="清晰的需求理解与可执行方案，中文"
    )

    res = Crew(agents=[researcher], tasks=[task], llm=researcher.llm).kickoff()
    print("\n📌 研究完成:\n", res)
    log = "🔍 智能需求分析师：已完成需求分析"
    print(log)
    add_log(state["task_id"], f"{log} \n {res}")
    return {"research_result": str(res), "logs": [log, ]}


# ------------------------------------------------------------------------------
# 🔥 节点2：执行者（万能：自动判断要不要写代码）
# ------------------------------------------------------------------------------
def execute_node(state):
    _, executor, _, _ = get_agents()

    task = Task(
        description=f"""
根据研究结果执行任务：
{state['research_result']}

规则：
- 如果需求需要代码 → 写可运行代码
- 如果需求是创意/文案/报告/歌词 → 直接生成内容
- 如果需求是查询 → 直接给出结果
- 输出必须是中文
- 直接给最终内容，不要废话
""",
        agent=executor,
        expected_output="直接输出最终结果，中文"
    )

    res = Crew(agents=[executor], tasks=[task], llm=executor.llm).kickoff()
    print("\n✅ 执行完成:\n", res)
    log = "⚙️ 全能任务执行者：已生成结果"
    print(log)
    add_log(state["task_id"], f"{log} \n {res}")
    return {"execute_result": str(res), "logs": [log]}


# ------------------------------------------------------------------------------
# 🔥 节点3：校验员（通用：检查结果是否正确）
# ------------------------------------------------------------------------------
def validate_node(state):
    _, _, validator, _ = get_agents()

    task = Task(
        description=f"""
用户需求：{state['task']}
执行结果：{state['execute_result']}

检查：
1. 结果是否满足需求
2. 内容是否正确
3. 格式是否正常
4. 全部用中文给出校验结论
""",
        agent=validator,
        expected_output="中文校验报告"
    )

    res = Crew(agents=[validator], tasks=[task], llm=validator.llm).kickoff()
    print("\n🔍 校验完成:\n", res)
    log = "🧪 结果质量校验师：已完成校验"
    print(log)
    add_log(state["task_id"], f"{log} \n {res}")
    return {"validate_result": str(res), "logs": [log]}


# ------------------------------------------------------------------------------
# 🔥 节点4：经理（通用：汇总最终结果，中文输出）
# ------------------------------------------------------------------------------
def manager_node(state):
    _, _, _, manager = get_agents()

    task = Task(
        description=f"""
汇总所有结果，输出最终版答案：
用户需求：{state['task']}
执行结果：{state['execute_result']}
校验结果：{state['validate_result']}

要求：
1. 只输出用户真正想要的最终答案
2. 不要过程，不要多余分析
3. 100% 中文
4. 干净、整洁、可直接使用
""",
        agent=manager,
        expected_output="最终答案，纯中文，直接可用"
    )

    res = Crew(agents=[manager], tasks=[task], llm=manager.llm).kickoff()
    print("\n🎉 最终报告:\n", res)
    log = "📋 最终报告汇总师：已生成报告"
    print(log)
    add_log(state["task_id"], f"{log} \n {res}")
    return {"final_report": str(res), "logs": [log]}


# ------------------------------------------------------------------------------
# 🔥 构建工作流
# ------------------------------------------------------------------------------
def build_workflow():
    wf = StateGraph(AgentState)

    wf.add_node("research", research_node)
    wf.add_node("execute", execute_node)
    wf.add_node("validate", validate_node)
    wf.add_node("manager", manager_node)

    wf.set_entry_point("research")
    wf.add_edge("research", "execute")
    wf.add_edge("execute", "validate")
    wf.add_edge("validate", "manager")
    wf.add_edge("manager", END)

    return wf.compile()


workflow = build_workflow()


# --------------------------
# 执行并返回 AGENT 日志
# --------------------------
def run_task_with_logs(task_id: str, task_content: str):
    result = workflow.invoke({
        "task_id": task_id,
        "task": task_content,
        "research_result": "",
        "execute_result": "",
        "validate_result": "",
        "final_report": ""
    })

    return result["final_report"]
