from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from septic_sentinel import api
from septic_sentinel.config import Settings
from septic_sentinel.public_record_check import (
    PublicLookupRateLimiter,
    PublicRecordCheckRequest,
    PublicRecordUnavailableError,
    check_public_record,
)
from septic_sentinel.runtime import build_service

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    case_service = build_service(
        Settings(
            mode="fixture",
            db_path=tmp_path / "public-record-api.sqlite3",
            fixture_root=FIXTURE_ROOT,
        )
    )
    monkeypatch.setattr(api, "service", case_service)
    with TestClient(api.app) as client:
        yield client


def request(**changes: object) -> PublicRecordCheckRequest:
    values: dict[str, object] = {
        "identifier_type": "permit",
        "identifier": "0310-90S",
        "claimed_year": 1990,
        "closing_date": "2026-09-10",
        "loan_amount_cents": 35_000_000,
        "daily_delay_cost_cents": 125_000,
        "expected_delay_days": 5,
        "inspection_cost_cents": 48_000,
    }
    return PublicRecordCheckRequest.model_validate({**values, **changes})


def transport(payload: object, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _: httpx.Response(status, json=payload))


@pytest.mark.asyncio
async def test_exact_permit_lookup_returns_public_fields_and_user_math() -> None:
    row = {
        "permitnumber": "0310-90S",
        "taxparcelnumbers": "1-34-07.00-0430.00",
        "appreceiveddate": "1990-06-28T00:00:00.000",
        "permitstatus": "Completion Report Received",
        "septicsystemtype": "Gravity",
        "constructiontype": "New Construction",
        "county": "Sussex",
        "url_for_permit_details": "https://den.dnrec.delaware.gov/Detail/PermitDetail.aspx?id=60484984",
        "ownername": "must never be returned",
    }
    async with httpx.AsyncClient(transport=transport([row])) as client:
        result = await check_public_record(
            request(), client=client, today=date(2026, 9, 1)
        )

    assert result.comparison == "aligned"
    assert result.record is not None
    assert result.record.county == "Sussex"
    assert "owner" not in result.model_dump_json().lower()
    assert result.days_to_close == 9
    assert result.exposure.without_action_cents == 625_000
    assert result.exposure.preventable_cents == 577_000


@pytest.mark.asyncio
async def test_parcel_lookup_selects_newest_exact_match_without_fabricating_claim() -> None:
    rows = [
        {
            "permitnumber": "OLD",
            "taxparcelnumbers": "1-23.00-4",
            "appreceiveddate": "1998-01-01T00:00:00.000",
        },
        {
            "permitnumber": "NEW",
            "taxparcelnumbers": "1-23-00-4",
            "appreceiveddate": "2014-04-02T00:00:00.000",
        },
        {
            "permitnumber": "OTHER",
            "taxparcelnumbers": "9-99",
            "appreceiveddate": "2024-01-01T00:00:00.000",
        },
    ]
    async with httpx.AsyncClient(transport=transport(rows)) as client:
        result = await check_public_record(
            request(identifier_type="parcel", identifier="1-23.00-4", claimed_year=2018),
            client=client,
        )

    assert result.comparison == "needs_review"
    assert result.matching_record_count == 2
    assert result.official_record_year == 2014
    assert result.record is not None and result.record.permit_number == "NEW"
    assert "verify" in result.summary.lower()


@pytest.mark.asyncio
async def test_no_exact_match_is_record_not_found() -> None:
    async with httpx.AsyncClient(transport=transport([])) as client:
        result = await check_public_record(request(), client=client)

    assert result.comparison == "record_not_found"
    assert result.record is None
    assert result.official_record_year is None


@pytest.mark.asyncio
async def test_upstream_failure_is_publicly_safe() -> None:
    async with httpx.AsyncClient(transport=transport({"error": "private"}, 500)) as client:
        with pytest.raises(PublicRecordUnavailableError, match="temporarily unavailable"):
            await check_public_record(request(), client=client)


def test_public_record_route_runs_a_fresh_lookup(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {
        "permitnumber": "0310-90S",
        "taxparcelnumbers": "1-34-07.00-0430.00",
        "appreceiveddate": "1990-06-28T00:00:00.000",
        "county": "Sussex",
    }

    async def lookup(input_request: PublicRecordCheckRequest):
        async with httpx.AsyncClient(transport=transport([row])) as client:
            return await check_public_record(
                input_request, client=client, today=date(2026, 9, 1)
            )

    monkeypatch.setattr(api, "check_public_record", lookup)
    response = api_client.post(
        "/api/v2/closing-rescue/public-record-check",
        json=request().model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["record"]["permit_number"] == "0310-90S"
    assert response.json()["comparison"] == "aligned"


def test_rate_limiter_expires_hashed_identity_windows() -> None:
    limiter = PublicLookupRateLimiter(limit=2, window_seconds=60)

    assert limiter.allow("reviewer", now=0)
    assert limiter.allow("reviewer", now=1)
    assert not limiter.allow("reviewer", now=2)
    assert limiter.allow("different-reviewer", now=2)
    assert limiter.allow("reviewer", now=61)
