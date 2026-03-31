import os

# 必须加：绕过crewai强制检查
os.environ["OPENAI_API_KEY"] = "dummy-key"

# 强制让 CrewAI 走本地 LLM
os.environ["OPENAI_API_BASE"] = "http://localhost:11434/v1"
os.environ["OPENAI_MODEL_NAME"] = "qwen:7b"

from crewai import Agent, Task, Crew, Process

# 创建 Agent
researcher = Agent(
    role='研究员',
    goal='研究 {topic} 并总结',
    backstory='你是一名专业分析师。',
    verbose=True,
    allow_delegation=False
)

# 创建任务
task = Task(
    description='研究 {topic} 的关键信息。',
    expected_output='3 个关键点的列表。',
    agent=researcher
)

# 运行 Crew
crew = Crew(
    agents=[researcher],
    tasks=[task],
    # verbose=2,
    process=Process.sequential
)

result = crew.kickoff(inputs={"topic": "帮我查询今天的天气，并告诉我你是怎么查询的"})
print("\n" + "="*50)
print("结果:", result)