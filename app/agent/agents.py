import yaml
from crewai import Agent
from app.llm.model_factory import ModelFactory

llm = ModelFactory.get_llm()

# ## ========== 【四个通用智能体，支撑所有业务】 ==========
# researcher = Agent(
#     role="智能需求分析师",
#     goal="精准理解用户任何需求，自动分类任务，生成可落地方案",
#     backstory="""
#     你能处理所有任务：代码、文案、歌词、查询、分析、报告、策划、总结等。
#     你会自动判断任务类型，并给出最直接的执行方案。
#     全程使用中文。
#     """,
#     llm=llm,
#     verbose=True
# )
#
# executor = Agent(
#     role="全能任务执行者",
#     goal="根据需求直接产出最终结果",
#     backstory="""
#     你能写代码、写歌、写文案、写报告、做查询、做分析、做总结。
#     不需要用户提醒，直接输出最终可用内容。
#     全程使用中文。
#     """,
#     llm=llm,
#     verbose=True
# )
#
# validator = Agent(
#     role="结果质量校验师",
#     goal="确保结果正确、完整、满足需求",
#     backstory="""
#     你严格校验内容质量，修正错误，补充缺失。
#     全程使用中文。
#     """,
#     llm=llm,
#     verbose=True
# )
#
# manager = Agent(
#     role="最终报告汇总师",
#     goal="输出简洁、完整、可用的最终中文报告",
#     backstory="""
#     你只输出用户真正想要的结果，不输出多余过程。
#     格式美观，直接可用。
#     全程使用中文。
#     """,
#     llm=llm,
#     verbose=True
# )




def load_agents():
    with open("./config/agents.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    agents = {}
    for name, cfg in config["agents"].items():
        agents[name] = Agent(
            role=cfg["role"],
            goal=cfg["goal"],
            backstory=cfg["backstory"],
            llm=llm,
            verbose=cfg.get("verbose", True),
            memory=cfg.get("memory", True),
            allow_delegation=cfg.get("allow_delegation", True),
        )
    return agents

agents = load_agents()

researcher = agents["researcher"]
executor = agents["executor"]
validator = agents["validator"]
manager = agents["manager"]
