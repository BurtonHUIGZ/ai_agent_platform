import os
import json
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Dict, Any, Optional


class Settings(BaseSettings):
    ENV: str = "dev"
    PORT: int = 8718
    ACTIVE_PROVIDER: str = "ALIYUN_BAILIAN"


@lru_cache()
def load_model_config() -> Dict[str, Any]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "models.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache()
def get_model_config(provider: str = None) -> Dict[str, Any]:
    """获取指定provider的模型配置"""
    config = load_model_config()
    active_provider = "ALIYUN_BAILIAN"
    try:
        active_provider = Settings().ACTIVE_PROVIDER
    except Exception:
        pass
    provider_key = provider if provider else active_provider
    result = config.get(provider_key)
    if result:
        return result
    return config.get("OLLAMA")


@lru_cache()
def get_available_providers() -> list[str]:
    """获取所有可用的模型provider"""
    return list(load_model_config().keys())


settings = Settings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = os.path.join(BASE_DIR, "static")
CHROMA_PATH = os.path.join(BASE_DIR, "data", "chroma_db")
