"""Environment-based application configuration."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FIXTURE_APPROVAL_RECOVERY_KEY = "fixture-only-approval-recovery-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_prefix="SEPTIC_SENTINEL_",
        extra="ignore",
    )

    mode: str = "fixture"
    db_path: Path = Path("./septic_sentinel.db")
    mireye_command: str = "uvx"
    mireye_args: str = "mireye-mcp"
    openai_model: str = "gpt-5-mini"
    source_timeout_seconds: float = 20.0
    source_max_attempts: int = 2
    fixture_root: Path = Path("../fixtures/cases")
    log_level: str = "INFO"
    retention_days: int = 30
    approval_recovery_key: SecretStr = SecretStr(FIXTURE_APPROVAL_RECOVERY_KEY)
    solari_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SOLARI_API_KEY", "SEPTIC_SENTINEL_SOLARI_API_KEY"),
    )
    solari_base_url: str = "https://api.getsolari.com"
    solari_timeout_seconds: float = 120.0
    solari_artifact_dir: Path = Path("./runtime-artifacts/closing-rescue")

    @model_validator(mode="after")
    def live_mode_requires_private_recovery_key(self) -> "Settings":
        recovery_key = self.approval_recovery_key.get_secret_value()
        if not recovery_key or not recovery_key.strip():
            raise ValueError("Approval recovery key must not be blank")
        if recovery_key != recovery_key.strip():
            raise ValueError("Approval recovery key must not have surrounding whitespace")
        if self.mode != "fixture":
            if recovery_key == FIXTURE_APPROVAL_RECOVERY_KEY:
                raise ValueError("Live mode requires an explicit approval recovery key")
            if len(recovery_key) < 32:
                raise ValueError("Live approval recovery key must be at least 32 characters")
        return self


settings = Settings()
