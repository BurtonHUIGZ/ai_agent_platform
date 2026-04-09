import yaml
from crewai import Agent
from app.llm.model_factory import ModelFactory

llm = ModelFactory.get_llm()


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
            memory=False,
            allow_delegation=cfg.get("allow_delegation", True),
        )
    return agents


agents = load_agents()

researcher = agents["researcher"]
executor = agents["executor"]
validator = agents["validator"]
manager = agents["manager"]

from app.agent.tasks import init_task_factory
init_task_factory(agents)
