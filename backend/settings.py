"""All configuration comes from environment variables (twelve-factor).

One object, read once at start. A missing variable fails here, not on first use.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    temporal_address: str
    temporal_namespace: str = "default"
    queue: Literal["workflow", "a"] = "workflow"
    # The researcher's keys; only the worker on queue `a` needs them, so they are optional here and required there.
    tavily_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-6-luna"


@lru_cache
def settings() -> Settings:
    return Settings()
