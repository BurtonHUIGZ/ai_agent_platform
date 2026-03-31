import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENV: str = "dev"
    PORT: int = 8718
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "qwen:7b"


settings = Settings()

# 绝对路径修复（解决 static 报错的核心）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = os.path.join(BASE_DIR, "static")
CHROMA_PATH = os.path.join(BASE_DIR, "data", "chroma_db")
