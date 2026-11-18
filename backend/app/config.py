from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sicamp:sicamp@localhost:5432/sicamp"
    llm_provider: Literal["demo", "gateway"] = "demo"
    llm_base_url: str = "https://llm-gateway.sicamp.ru/v1"
    llm_api_key: str = ""
    llm_model: str = "nebius/deepseek-ai/DeepSeek-V4-Pro"
    llm_timeout: float = 180
    llm_max_tokens: int = 12000
    embedding_provider: Literal["local", "api"] = "local"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=384, ge=8, le=2000)
    seed_demo: bool = True

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value):
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL должна использовать PostgreSQL: postgresql+psycopg://...")
        return value


settings = Settings()
