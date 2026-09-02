"""Privacy-safe, user-driven checks against Delaware's public septic dataset."""

from __future__ import annotations

import re
import secrets
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from septic_sentinel.adapters.delaware import DATASET_URL, PUBLIC_FIELDS, RESOURCE_URL


class PublicRecordUnavailableError(RuntimeError):
    """Raised when the official public source cannot be queried safely."""


class PublicLookupRateLimiter:
    """Small per-process guard for the keyless public demo; stores no raw IPs."""

    def __init__(self, limit: int = 12, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._salt = secrets.token_bytes(32)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, identity: str, *, now: float | None = None) -> bool:
        observed = monotonic() if now is None else now
        key = sha256(self._salt + identity.encode("utf-8")).hexdigest()
        cutoff = observed - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(observed)
            return True


class PublicRecordCheckRequest(BaseModel):
    identifier_type: Literal["permit", "parcel"]
    identifier: str = Field(min_length=3, max_length=64)
    claimed_year: int = Field(ge=1900, le=2100)
    closing_date: date
    loan_amount_cents: int = Field(ge=1_000_000, le=500_000_000)
    daily_delay_cost_cents: int = Field(ge=0, le=10_000_000)
    expected_delay_days: int = Field(ge=1, le=365)
    inspection_cost_cents: int = Field(ge=0, le=10_000_000)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9. -]+", cleaned):
            raise ValueError("identifier contains unsupported characters")
        return cleaned


class PublicPermitRecord(BaseModel):
    permit_number: str
    parcel_reference: str
    application_received_date: date | None
    permit_status: str | None
    system_type: str | None
    construction_type: str | None
    county: str | None
    official_detail_url: str | None


class PublicExposureScenario(BaseModel):
    loan_amount_cents: int
    daily_delay_cost_cents: int
    expected_delay_days: int
    inspection_cost_cents: int
    without_action_cents: int
    after_action_cents: int
    preventable_cents: int
    formula: str = "daily_delay_cost × expected_delay_days; after_action = inspection_cost"
    truth_class: Literal["user_supplied_scenario"] = "user_supplied_scenario"


class PublicRecordCheckResult(BaseModel):
    query_type: Literal["permit", "parcel"]
    query_value: str
    comparison: Literal["aligned", "needs_review", "record_not_found"]
    summary: str
    claimed_year: int
    official_record_year: int | None
    closing_date: date
    days_to_close: int
    matching_record_count: int
    record: PublicPermitRecord | None
    exposure: PublicExposureScenario
    dataset_url: str = DATASET_URL
    retrieved_at: datetime
    limitation: str = (
        "A public permit application date is not proof of installation, replacement, "
        "system condition, or regulatory compliance. Confirm differences with DNREC."
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _text(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _official_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname == "den.dnrec.delaware.gov":
        return value
    return None


async def check_public_record(
    request: PublicRecordCheckRequest,
    *,
    client: httpx.AsyncClient | None = None,
    today: date | None = None,
) -> PublicRecordCheckResult:
    """Query live public data and calculate only the user's disclosed scenario."""
    owned_client = client is None
    http = client or httpx.AsyncClient(timeout=12)
    try:
        response = await http.get(
            RESOURCE_URL,
            params={
                "$q": request.identifier,
                "$select": ",".join(PUBLIC_FIELDS),
                "$limit": "50",
            },
            headers={"User-Agent": "Closing-Rescue-Public-Record-Check/1.0"},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Delaware API returned an invalid response")
    except (httpx.HTTPError, ValueError) as exc:
        raise PublicRecordUnavailableError(
            "The Delaware public record source is temporarily unavailable"
        ) from exc
    finally:
        if owned_client:
            await http.aclose()

    target = _normalize(request.identifier)
    field = "permitnumber" if request.identifier_type == "permit" else "taxparcelnumbers"
    matches = [row for row in rows if _normalize(str(row.get(field, ""))) == target]
    matches.sort(key=lambda row: str(row.get("appreceiveddate", "")), reverse=True)
    selected = matches[0] if matches else None
    received = _date(selected.get("appreceiveddate")) if selected else None
    official_year = received.year if received else None

    if selected is None:
        comparison = "record_not_found"
        summary = "No exact permit or parcel match was found in the Delaware dataset."
        record = None
    else:
        comparison = "aligned" if official_year == request.claimed_year else "needs_review"
        summary = (
            "The submitted year matches the public record's application-received year."
            if comparison == "aligned"
            else (
                "The submitted year differs from the public record's "
                "application-received year; verify the underlying documents."
            )
        )
        record = PublicPermitRecord(
            permit_number=_text(selected, "permitnumber") or "Not provided",
            parcel_reference=_text(selected, "taxparcelnumbers") or "Not provided",
            application_received_date=received,
            permit_status=_text(selected, "permitstatus"),
            system_type=_text(selected, "septicsystemtype"),
            construction_type=_text(selected, "constructiontype"),
            county=_text(selected, "county"),
            official_detail_url=_official_url(selected.get("url_for_permit_details")),
        )

    without_action = request.daily_delay_cost_cents * request.expected_delay_days
    after_action = request.inspection_cost_cents
    exposure = PublicExposureScenario(
        loan_amount_cents=request.loan_amount_cents,
        daily_delay_cost_cents=request.daily_delay_cost_cents,
        expected_delay_days=request.expected_delay_days,
        inspection_cost_cents=request.inspection_cost_cents,
        without_action_cents=without_action,
        after_action_cents=after_action,
        preventable_cents=max(without_action - after_action, 0),
    )
    current_date = today or datetime.now(UTC).date()
    return PublicRecordCheckResult(
        query_type=request.identifier_type,
        query_value=request.identifier,
        comparison=comparison,
        summary=summary,
        claimed_year=request.claimed_year,
        official_record_year=official_year,
        closing_date=request.closing_date,
        days_to_close=max((request.closing_date - current_date).days, 0),
        matching_record_count=len(matches),
        record=record,
        exposure=exposure,
        retrieved_at=datetime.now(UTC),
    )
