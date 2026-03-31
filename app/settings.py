from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ENV: str = "dev"
    PORT: int = 8718
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "qwen:7b"

settings = Settings()