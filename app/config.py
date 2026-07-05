from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: list[int] | int | str = Field(alias="ADMIN_IDS")
    marzban_base_url: str = Field(alias="MARZBAN_BASE_URL")
    marzban_username: str = Field(alias="MARZBAN_USERNAME")
    marzban_password: str = Field(alias="MARZBAN_PASSWORD")
    database_url: str = Field(default="sqlite+aiosqlite:///bot.db", alias="DATABASE_URL")
    timezone: str = Field(default="Asia/Tehran", alias="TIMEZONE")
    default_language: str = Field(default="en", alias="DEFAULT_LANGUAGE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: str | int | list[int]) -> list[int]:
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [int(item) for item in value]
        return [int(item.strip()) for item in value.split(",") if item.strip()]

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_async(cls, value: str) -> str:
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
