import os
from app.settings import settings

# 暴力修复：直接设置环境变量，绕过所有校验
os.environ["OPENAI_API_KEY"] = settings.LLM_API_KEY
os.environ["OPENAI_MODEL_NAME"] = settings.LLM_MODEL
os.environ["OPENAI_API_BASE"] = settings.LLM_BASE_URL

from langchain_ollama import ChatOllama

from langchain_openai import ChatOpenAI


class ModelFactory:
    @staticmethod
    def get_llm(model_name=None):
        model = model_name or settings.LLM_MODEL
        return ChatOllama(
            base_url=settings.LLM_BASE_URL,
            api_key="dummy-key",  # 随便填，本地不需要真实key
            model=model,
            temperature=0.1
        )
