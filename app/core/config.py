from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    chat_mode: Literal["natural", "light"] = "natural"
    chat_enabled_services: str = "inventory,rental,organization-customer"
    chat_max_conversations: int = Field(default=200, ge=1, le=10000)
    chat_history_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    chat_rate_limit_requests: int = Field(default=10, ge=1, le=1000)
    chat_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    chat_max_concurrent_requests: int = Field(default=1, ge=1, le=10)
    max_tool_result_chars: int = Field(default=12000, ge=1000, le=100000)
    log_level: str = "INFO"
    ai_db_fallback_enabled: bool = False
    ai_db_host: str = "127.0.0.1"
    ai_db_port: int = Field(default=3307, ge=1, le=65535)
    ai_db_user: str = "equipment_ai_reader"
    ai_db_password: SecretStr = SecretStr("")
    ai_db_timeout_seconds: int = Field(default=5, ge=1, le=30)
    ai_db_max_rows: int = Field(default=2000, ge=50, le=10000)
    ai_db_api_timeout_seconds: int = Field(default=3, ge=1, le=30)

    @model_validator(mode="after")
    def validate_database_fallback(self):
        if self.ai_db_fallback_enabled:
            if self.ai_db_user.casefold() == "root" or not self.ai_db_user.strip():
                raise ValueError("AI database fallback phải dùng tài khoản chỉ đọc riêng, không dùng root")
            if len(self.ai_db_password.get_secret_value()) < 12:
                raise ValueError("AI_DB_PASSWORD cần ít nhất 12 ký tự khi bật fallback")
        return self

    @field_validator("chat_enabled_services")
    @classmethod
    def validate_services(cls, value: str) -> str:
        services = {part.strip() for part in value.split(",") if part.strip()}
        if services - {"inventory", "rental", "organization-customer"}:
            raise ValueError("CHAT_ENABLED_SERVICES chỉ nhận inventory,rental,organization-customer")
        return ",".join(sorted(services))

    @property
    def enabled_services(self) -> frozenset[str]:
        return frozenset(part for part in self.chat_enabled_services.split(",") if part)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
