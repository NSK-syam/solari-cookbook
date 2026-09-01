"""Public, redacted receipts for the three Solari execution products."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class SolariStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class SolariExecutionStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SolariArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["manifest", "citation", "screenshot", "replay", "receipt"]
    label: str = Field(min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=2_048)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    media_type: str | None = Field(default=None, max_length=100)

    @field_validator("url")
    @classmethod
    def artifact_url_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (value.startswith("https://") or value.startswith("/api/v2/")):
            raise ValueError("artifact URL must be HTTPS or a local API artifact")
        return value


class SolariStepReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: Literal["sandbox", "browser", "desktop"]
    status: SolariStepStatus
    session_id: str | None = Field(default=None, max_length=200)
    detail: str = Field(min_length=1, max_length=500)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    artifacts: tuple[SolariArtifact, ...] = ()
    failure_reason: str | None = Field(default=None, max_length=300)

    @field_validator("session_id", "detail", "failure_reason")
    @classmethod
    def receipt_must_not_persist_sensitive_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        forbidden = ("slr_live_", "api_key", "cookie", "ownername")
        if any(token in lowered for token in forbidden):
            raise ValueError("receipt contains a forbidden sensitive value")
        return value


class SolariExecutionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    portfolio_id: str = Field(min_length=1, max_length=200)
    status: SolariExecutionStatus
    steps: tuple[SolariStepReceipt, SolariStepReceipt, SolariStepReceipt]
    manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    updated_at: AwareDatetime

    def step(self, product: str) -> SolariStepReceipt:
        return next(item for item in self.steps if item.product == product)


def pending_step(
    product: Literal["sandbox", "browser", "desktop"], now: datetime
) -> SolariStepReceipt:
    detail = "Waiting for human approval" if product == "desktop" else "Waiting to run"
    status = SolariStepStatus.BLOCKED if product == "desktop" else SolariStepStatus.PENDING
    return SolariStepReceipt(
        product=product, status=status, detail=detail, started_at=None, completed_at=None
    )
