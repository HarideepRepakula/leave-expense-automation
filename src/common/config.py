"""Application settings loaded from environment variables and .env (spec section 24).

Secrets never live in source. .env.example documents every variable with placeholders.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://lea_migrator:change-me-migrator@localhost:5432/lea_dev",
        alias="DATABASE_URL",
    )
    test_database_url: str = Field(
        default="postgresql+psycopg://lea_migrator:change-me-migrator@localhost:5432/lea_test",
        alias="TEST_DATABASE_URL",
    )
    as_of_date: date = Field(default=date(2026, 10, 22), alias="AS_OF_DATE")

    postgres_app_user: str = Field(default="lea_app", alias="POSTGRES_APP_USER")
    postgres_app_password: str = Field(default="", alias="POSTGRES_APP_PASSWORD")
    postgres_analytics_user: str = Field(default="lea_analytics_ro", alias="POSTGRES_ANALYTICS_USER")
    postgres_analytics_password: str = Field(default="", alias="POSTGRES_ANALYTICS_PASSWORD")
    postgres_evaluation_user: str = Field(default="lea_evaluation", alias="POSTGRES_EVALUATION_USER")
    postgres_evaluation_password: str = Field(default="", alias="POSTGRES_EVALUATION_PASSWORD")

    llm_explanations_enabled: bool = Field(default=False, alias="LLM_EXPLANATIONS_ENABLED")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
