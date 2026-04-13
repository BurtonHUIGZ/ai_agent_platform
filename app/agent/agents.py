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
from app.core.memory import memory


def _create_rag_tools():
    from langchain_core.tools import tool
    
    @tool
    def search_knowledge_base(query: str, top_k: int = 5) -> str:
        """搜索知识库获取相关信息"""
        try:
            results = memory.retrieve_memories(user_id="default", query=query, top_k=top_k)
            if not results:
                return "知识库中未找到相关信息"
            return "\n\n".join([f"{i}. {r.get('content', '')}" for i, r in enumerate(results, 1)])
        except Exception as e:
            return f"检索失败: {e}"
    
    @tool
    def search_user_memory(query: str) -> str:
        """搜索用户历史记忆和偏好"""
        try:
            results = memory.retrieve_memories(user_id="default", query=query, memory_type="preference", top_k=3)
            if not results:
                return "未找到用户偏好"
            return "\n".join([r.get("content", "") for r in results])
        except Exception as e:
            return f"检索失败: {e}"
    
    return [search_knowledge_base, search_user_memory]


def load_agents():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "agents.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    agents = {}
    for name, agent_cfg in cfg["agents"].items():
        agents[name] = Agent(
            role=agent_cfg["role"],
            goal=agent_cfg["goal"],
            backstory=agent_cfg["backstory"],
            llm=llm,
            verbose=agent_cfg.get("verbose", True),
            memory=False,
            allow_delegation=agent_cfg.get("allow_delegation", True),
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
