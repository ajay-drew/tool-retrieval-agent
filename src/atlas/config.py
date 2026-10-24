from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    atlas_llm_provider: str = "gemini"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    atlas_model: str = "gemini-3.5-flash"
    atlas_max_output_tokens: int = 4096
    atlas_max_request_tokens: int | None = None
    atlas_reasoning_effort: str | None = None
    atlas_k: int = 8
    atlas_embed_model: str = "BAAI/bge-small-en-v1.5"
    atlas_examples_per_tool: int = 5
    atlas_hybrid: bool = False
    atlas_approve_writes: bool = True
    atlas_price_in_per_m: float = 0.0
    atlas_price_out_per_m: float = 0.0
    atlas_services: list[str] = ["paypal"]
    atlas_specs_dir: Path = Path("specs")
    atlas_data_dir: Path = Path("data")
    atlas_runlog: Path = Path("runs/runlog.jsonl")
    atlas_max_tool_tokens: int = 1500
    atlas_today: str | None = None

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    atlas_tools_collection: str = "atlas_tools"
    atlas_kb_collection: str = "atlas_kb"

    langsmith_tracing: bool = True
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "atlas"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @field_validator("llm_api_key", "langsmith_api_key", "qdrant_api_key", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def tracing_enabled(self) -> bool:
        return self.langsmith_tracing and self.langsmith_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
