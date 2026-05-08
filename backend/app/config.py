from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMERGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace_root: Path = Path("./workspace")
    default_extract_model: str = "gemini-2.0-flash"
    default_agent_model: str = "claude-sonnet-4-6"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
