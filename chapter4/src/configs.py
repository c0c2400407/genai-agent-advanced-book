from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: SecretStr = Field(default="", repr=False, validation_alias=AliasChoices("LLM_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"))
    openai_api_base: str = Field(default="https://openrouter.ai/api/v1", validation_alias=AliasChoices("LLM_BASE_URL", "OPENROUTER_BASE_URL", "OPENAI_API_BASE"))
    openai_model: str = Field(default="", validation_alias=AliasChoices("LLM_MODEL", "OPENROUTER_MODEL", "OPENAI_MODEL"))
    structured_mode: str = "schema"
    tool_mode: str = "native"
    max_subtasks: int = Field(default=2, ge=1, le=2)
    max_challenges: int = Field(default=2, ge=1, le=3)
    max_api_calls: int = Field(default=20, ge=1, le=30)
    request_interval: float = Field(default=3.2, ge=0)
    reasoning_effort: str | None = None
    max_output_tokens: int = Field(default=1200, ge=128, le=8192)
    search_backend: Literal["tfidf", "lmstudio"] = "tfidf"
    embedding_base_url: str = "http://localhost:1234/v1"
    embedding_model: str = ""
    embedding_api_key: SecretStr = Field(default="lm-studio", repr=False)
    embedding_batch_size: int = Field(default=8, ge=1, le=64)
    embedding_document_prefix: str = "auto"
    embedding_query_prefix: str = "auto"
    save_full_logs: bool = True

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore", populate_by_name=True, hide_input_in_errors=True)
