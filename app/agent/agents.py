import os
import yaml
import uuid

from crewai import Agent
from crewai.tools.base_tool import Tool
from pydantic import BaseModel

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
from app.core.rag_eval import rag_realtime_evaluator


class SearchKnowledgeBaseInput(BaseModel):
    query: str
    top_k: int = 5


class SearchUserMemoryInput(BaseModel):
    query: str


def _create_rag_tools():
    _session_id = str(uuid.uuid4())
    
    def _search_knowledge_base(query: str, top_k: int = 5) -> str:
        """搜索知识库获取相关信息"""
        try:
            import time
            start = time.time()
            results = memory.hybrid_retrieve(user_id="default", query=query, top_k=top_k, user_top_k=top_k, kb_top_k=top_k)
            latency_ms = (time.time() - start) * 1000
            
            if not results:
                return "知识库中未找到相关信息"
            
            result_text = "\n\n".join([f"{i}. {r.get('content', '')}" for i, r in enumerate(results, 1)])
            
            try:
                rag_realtime_evaluator.evaluate_retrieval(
                    query=query,
                    retrieved_docs=results,
                    session_id=_session_id,
                    latency_ms=latency_ms
                )
            except Exception as eval_error:
                print(f"[RAG评估] 检索评估失败: {eval_error}")
            
            return result_text
        except Exception as e:
            return f"检索失败: {e}"
    
    def _search_user_memory(query: str) -> str:
        """搜索用户历史记忆和偏好"""
        try:
            results = memory.hybrid_retrieve(user_id="default", query=query, top_k=3, user_top_k=3, kb_top_k=3)
            if not results:
                return "未找到用户偏好或历史记录"
            return "\n".join([r.get("content", "") for r in results])
        except Exception as e:
            return f"检索失败: {e}"
    
    search_kb_tool = Tool(
        name="search_knowledge_base",
        description="搜索知识库获取相关信息。当用户询问需要查找特定信息、文档、政策、指南等内容时使用。",
        func=_search_knowledge_base,
        args_schema=SearchKnowledgeBaseInput,
    )
    
    search_mem_tool = Tool(
        name="search_user_memory",
        description="搜索用户历史对话记录。用于获取用户之前的对话内容、历史交互等信息。",
        func=_search_user_memory,
        args_schema=SearchUserMemoryInput,
    )
    
    return [search_kb_tool, search_mem_tool]


def load_agents():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "agents.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    rag_tools = _create_rag_tools()
    
    agents = {}
    for name, agent_cfg in cfg["agents"].items():
        agent_tools = []
        if name in ["researcher", "executor"]:
            agent_tools = rag_tools
        
        agents[name] = Agent(
            role=agent_cfg["role"],
            goal=agent_cfg["goal"],
            backstory=agent_cfg["backstory"],
            llm=llm,
            verbose=agent_cfg.get("verbose", True),
            memory=False,
            allow_delegation=agent_cfg.get("allow_delegation", True),
            tools=agent_tools,
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
