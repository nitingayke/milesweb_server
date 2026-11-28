"""Configuration for the read-only connector API."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings are read from environment variables and an optional .env file."""

    # Development-only opaque bearer-token to client-id mappings. This mock
    # emulates the already-verified identity the MCP server forwards.
    phase2_test_tokens: str = ""
    jwt_secret_key: str = "milesweb-mcp-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_in_minutes: int = 1440
    mock_whmcs_identifier: str = ""
    mock_whmcs_secret: str = ""
    dummy_login_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
