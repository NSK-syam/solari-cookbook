"""Unit and contract tests for external-source adapter normalization."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from septic_sentinel.adapters.base import PropertyLocation, RetryExhaustedError, with_retries
from septic_sentinel.adapters.delaware import RESOURCE_URL, DelawareSepticAdapter
from septic_sentinel.adapters.mireye import MIREYE_API_URL, MireyeAdapter
from septic_sentinel.adapters.noaa import NoaaPrecipitationAdapter
from septic_sentinel.domain import EvidenceStatus

CASE_ID = "case_adapter_test"
LOCATION = PropertyLocation(
    address="123 Test Road, Dover, DE",
    lat=39.1582,
    lng=-75.5244,
    parcel_id="12-034.00-056",
)


@pytest.mark.asyncio
async def test_with_retries_returns_success_and_reuses_request_id(monkeypatch) -> None:
    attempts: list[str] = []

    async def no_wait(_: float) -> None:
        return None

    async def operation(request_id: str) -> str:
        attempts.append(request_id)
        if len(attempts) == 1:
            raise ConnectionError("temporary failure")
        return "ok"

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    result, request_id = await with_retries(operation, max_attempts=2)

    assert result == "ok"
    assert request_id.startswith("req_")
    assert attempts == [request_id, request_id]


@pytest.mark.asyncio
async def test_with_retries_raises_typed_error_after_exhaustion(monkeypatch) -> None:
    attempts: list[str] = []

    async def no_wait(_: float) -> None:
        return None

    async def operation(request_id: str) -> None:
        attempts.append(request_id)
        raise OSError("source offline")

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    with pytest.raises(RetryExhaustedError, match="failed after retries") as raised:
        await with_retries(operation, max_attempts=3)

    assert len(attempts) == 3
    assert attempts == [raised.value.request_id] * 3
    assert isinstance(raised.value.cause, OSError)
    assert str(raised.value.cause) == "source offline"


@pytest.mark.asyncio
async def test_with_retries_converts_timeout_to_exhaustion() -> None:
    async def operation(_: str) -> None:
        await asyncio.sleep(0.05)

    with pytest.raises(RetryExhaustedError) as raised:
        await with_retries(operation, max_attempts=1, timeout_seconds=0.001)

    assert isinstance(raised.value.cause, TimeoutError)


def _async_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_delaware_normalizes_matching_permit_and_citations() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json=[
                {
                    "permitnumber": "P-100",
                    "taxparcelnumbers": "12 034-00-056",
                    "appreceiveddate": "1999-04-10T00:00:00.000",
                    "permitstatus": "Final",
                    "url_for_permit_details": "https://example.test/permits/P-100",
                    "owner_name": "Must not be retained",
                },
                {"permitnumber": "OTHER", "taxparcelnumbers": "99-999"},
            ],
        )

    async with _async_client(handler) as client:
        evidence = (await DelawareSepticAdapter(client).collect(CASE_ID, LOCATION))[0]

    assert seen_request is not None
    assert str(seen_request.url).startswith(RESOURCE_URL)
    assert seen_request.url.params["$q"] == LOCATION.parcel_id
    assert seen_request.headers["X-Request-ID"] == evidence.request_id
    assert evidence.status == EvidenceStatus.SUCCESS
    assert evidence.confidence == 1.0
    assert evidence.payload["candidate_count"] == 1
    assert evidence.payload["permits"][0]["permitnumber"] == "P-100"
    assert "owner_name" not in evidence.payload["permits"][0]
    assert len(evidence.citations) == 2


@pytest.mark.asyncio
async def test_delaware_completed_query_with_no_matching_parcel_is_not_found() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"permitnumber": "OTHER", "taxparcelnumbers": "99-999"}],
        )

    async with _async_client(handler) as client:
        evidence = (await DelawareSepticAdapter(client).collect(CASE_ID, LOCATION))[0]

    assert evidence.status == EvidenceStatus.RECORD_NOT_FOUND
    assert evidence.request_id is not None
    assert evidence.payload == {
        "parcel_id": LOCATION.parcel_id,
        "query_completed": True,
        "candidates": [],
    }
    assert len(evidence.citations) == 1


@pytest.mark.asyncio
async def test_delaware_http_failure_becomes_evidence_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "maintenance"})

    async with _async_client(handler) as client:
        evidence = (await DelawareSepticAdapter(client).collect(CASE_ID, LOCATION))[0]

    assert evidence.status == EvidenceStatus.EVIDENCE_UNAVAILABLE
    assert evidence.error_code == "HTTPStatusError"
    assert "503 Service Unavailable" in (evidence.error_message or "")
    assert evidence.citations == []


def _noaa_data(features: list[dict]) -> dict:
    end = datetime(2026, 8, 5, 18, tzinfo=UTC)
    return {
        "station": {
            "properties": {"stationIdentifier": "KDOX", "name": "Dover"},
            "geometry": {"coordinates": [-75.47, 39.13]},
        },
        "start": end - timedelta(hours=72),
        "end": end,
        "observations_url": "https://api.weather.gov/stations/KDOX/observations",
        "features": features,
    }


def test_noaa_normalizes_precipitation_and_missing_observations() -> None:
    adapter = NoaaPrecipitationAdapter(lookback_hours=72)
    data = _noaa_data(
        [
            {
                "properties": {
                    "timestamp": "2026-08-05T18:00:00Z",
                    "precipitationLastHour": {"value": 0.0125},
                }
            },
            {"properties": {"precipitationLastHour": {"value": 0.0025}}},
            {"properties": {"precipitationLastHour": {"value": None}}},
        ]
    )

    evidence = adapter._normalize(CASE_ID, data, "req_noaa")

    assert evidence.status == EvidenceStatus.SUCCESS
    assert evidence.payload["precipitation_mm"] == 15.0
    assert evidence.payload["measured_observations"] == 2
    assert evidence.payload["missing_observations"] == 1
    assert evidence.payload["latest_observation"] == "2026-08-05T18:00:00Z"
    assert evidence.confidence == pytest.approx(2 / 72)
    assert evidence.citations[0].source_name == "NOAA National Weather Service"


def test_noaa_no_measurements_is_stale_without_citations() -> None:
    adapter = NoaaPrecipitationAdapter(lookback_hours=24)
    data = _noaa_data(
        [{"properties": {"timestamp": "2026-08-05T18:00:00Z", "precipitationLastHour": {}}}]
    )

    evidence = adapter._normalize(CASE_ID, data, "req_noaa")

    assert evidence.status == EvidenceStatus.STALE
    assert evidence.payload["precipitation_mm"] == 0.0
    assert evidence.payload["measured_observations"] == 0
    assert evidence.payload["missing_observations"] == 1
    assert evidence.confidence == 0.0
    assert evidence.citations == []


@pytest.mark.asyncio
async def test_noaa_missing_coordinates_is_unavailable_without_network() -> None:
    adapter = NoaaPrecipitationAdapter(lookback_hours=48)

    evidence = (
        await adapter.collect(
            CASE_ID,
            PropertyLocation(address="Unknown location", parcel_id="PARCEL-1"),
        )
    )[0]

    assert evidence.status == EvidenceStatus.EVIDENCE_UNAVAILABLE
    assert evidence.error_code == "ValueError"
    assert evidence.error_message == "Coordinates are required"
    assert evidence.payload == {"lookback_hours": 48}


def test_mireye_payload_prefers_structured_content() -> None:
    result = SimpleNamespace(
        structuredContent={"disposition": "resolved", "lat": "39.1"},
        content=[SimpleNamespace(text='{"disposition":"clarify"}')],
    )

    assert MireyeAdapter._payload(result) == {
        "disposition": "resolved",
        "lat": "39.1",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"parcel":{"apn":"ABC"}}', {"parcel": {"apn": "ABC"}}),
        ("[1,2]", {"value": [1, 2]}),
        ("not json", {"text": "not json"}),
    ],
)
def test_mireye_payload_normalizes_text_blocks(text: str, expected: dict) -> None:
    result = SimpleNamespace(structuredContent=None, content=[SimpleNamespace(text=text)])

    assert MireyeAdapter._payload(result) == expected


def test_mireye_citations_are_recursive_deduplicated_and_normalized() -> None:
    payload = {
        "terrain": {
            "source": "USGS",
            "source_url": "https://example.test/usgs",
            "fetched_at": "2026-08-05T12:30:00Z",
            "confidence": "0.88",
        },
        "duplicate": {
            "source_name": "USGS",
            "url": "https://example.test/usgs",
        },
        "nested": [
            {
                "source": "FEMA",
                "url": "https://example.test/fema",
                "retrieved_at": "invalid timestamp",
                "confidence": "unknown",
            }
        ],
    }

    citations = MireyeAdapter._citations(payload)

    assert [(item.source_name, str(item.source_url)) for item in citations] == [
        ("USGS", "https://example.test/usgs"),
        ("FEMA", "https://example.test/fema"),
    ]
    assert citations[0].retrieved_at == datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
    assert citations[0].confidence == 0.88
    assert citations[1].retrieved_at.tzinfo is not None
    assert citations[1].confidence is None


def test_mireye_citations_fall_back_to_mireye_provenance() -> None:
    citations = MireyeAdapter._citations({"terrain": {"slope_pct": 3.2}})

    assert len(citations) == 1
    assert citations[0].source_name == "Mireye"
    assert str(citations[0].source_url).rstrip("/") == MIREYE_API_URL
    assert citations[0].label == "Mireye MCP tool response"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("39.15", 39.15), (12, 12.0), (0, 0.0), (None, None), ("not-a-number", None)],
)
def test_mireye_number_normalization(value, expected: float | None) -> None:
    assert MireyeAdapter._number(value) == expected
