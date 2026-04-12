import os
import yaml
from crewai import Agent

config = None
provider = None
model_name = None


def _ensure_env():
    global config, provider, model_name
    from app.settings import settings, get_model_config
    config = get_model_config(settings.ACTIVE_PROVIDER)
    provider = settings.ACTIVE_PROVIDER
    model_name = config["model"]
    if provider == "ALIYUN_BAILIAN":
        model_name = f"openai/{model_name}"
    os.environ["OPENAI_API_KEY"] = config["api_key"]
    os.environ["OPENAI_MODEL_NAME"] = model_name
    os.environ["OPENAI_API_BASE"] = config["base_url"]


_ensure_env()

from app.llm.model_factory import llm


def load_agents():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "agents.yaml"), "r", encoding="utf-8") as f:
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
            tools=[],
        )
    return agents


agents = load_agents()

researcher = agents["researcher"]
executor = agents["executor"]
validator = agents["validator"]
manager = agents["manager"]
router = agents["router"]

from app.agent.tasks import init_task_factory
init_task_factory(agents)
