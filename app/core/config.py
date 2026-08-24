from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cấu hình duy nhất cho AI API, được đọc từ file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Equipment Rental AI"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8090
    cors_origins: str = "http://localhost:5173"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = Field(min_length=1)
    ollama_timeout_seconds: float = 120

    api_gateway_base_url: str = "http://localhost:8080"
    api_gateway_timeout_seconds: float = 30

    chat_history_limit: int = Field(default=20, ge=2, le=100)
    max_tool_result_chars: int = Field(default=12000, ge=1000, le=100000)
    log_level: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
