from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sicamp:sicamp@localhost:5432/sicamp"
    llm_provider: Literal["auto", "demo", "gateway"] = "auto"
    llm_base_url: str = "https://llm-gateway.sicamp.ru/v1"
    llm_api_key: str = ""
    llm_model: str = "nebius/Qwen/Qwen3-235B-A22B-Instruct-2507"
    llm_timeout: float = 180
    llm_max_tokens: int = 12000
    embedding_provider: Literal["local", "hash", "api"] = "local"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=384, ge=8, le=2000)
    embedding_local_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: str = str(ROOT / "model-cache")
    embedding_threads: int = Field(default=2, ge=1, le=32)
    seed_demo: bool = True

    @model_validator(mode="after")
    def select_llm_provider(self):
        if self.llm_provider == "auto":
            self.llm_provider = "gateway" if self.llm_api_key else "demo"
        return self

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value):
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL должна использовать PostgreSQL: postgresql+psycopg://...")
        return value


settings = Settings()
