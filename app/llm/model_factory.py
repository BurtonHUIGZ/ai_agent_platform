import os
from app.settings import settings
from app.settings import get_model_config, get_available_providers
from crewai import LLM as CrewAILLM
from langchain_ollama import ChatOllama


def _get_llm_config():
    config = get_model_config(settings.ACTIVE_PROVIDER)
    provider = settings.ACTIVE_PROVIDER
    model_name = config["model"]
    if provider == "ALIYUN_BAILIAN":
        model_name = f"openai/{model_name}"
    return config, provider, model_name


config, provider, model_name = _get_llm_config()

os.environ["OPENAI_API_KEY"] = config["api_key"]
os.environ["OPENAI_MODEL_NAME"] = model_name
os.environ["OPENAI_API_BASE"] = config["base_url"]


def debug_llm_env():
    """调试：打印当前LLM环境变量"""
    return {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_MODEL_NAME": os.environ.get("OPENAI_MODEL_NAME"),
        "OPENAI_API_BASE": os.environ.get("OPENAI_API_BASE"),
        "ACTIVE_PROVIDER": settings.ACTIVE_PROVIDER,
    }


class ModelFactory:
    @staticmethod
    def get_llm(temperature: float = None):
        """获取LLM实例"""
        config, provider, model_name = _get_llm_config()
        temp = temperature if temperature is not None else config.get("temperature", 0.7)

        if provider == "OLLAMA":
            return ChatOllama(
                model=config["model"],
                base_url=config["base_url"],
                api_key=config["api_key"],
                temperature=temp
            )
        else:
            return CrewAILLM(
                model=model_name,
                base_url=config["base_url"],
                api_base=config["base_url"],
                api_key=config["api_key"],
                temperature=temp,
                provider="litellm"
            )

    @staticmethod
    def get_eval_llm():
        """获取评估专用LLM实例"""
        config, provider, _ = _get_llm_config()
        
        if provider == "ALIYUN_BAILIAN":
            eval_model_name = config.get("eval_model", "qwen-max")
            eval_model = f"openai/{eval_model_name}"
            return CrewAILLM(
                model=eval_model,
                base_url=config["base_url"],
                api_base=config["base_url"],
                api_key=config["api_key"],
                temperature=config.get("eval_temperature", 0),
                provider="litellm"
            )
        else:
            return ModelFactory.get_llm(temperature=0)


llm = ModelFactory.get_llm()