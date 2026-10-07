"""All configuration comes from environment variables (twelve-factor).

One object, read once at start. A missing variable fails here, not on first use.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    temporal_address: str
    temporal_namespace: str = "default"
    queue: str = "workflow"


@lru_cache
def settings() -> Settings:
    return Settings()
