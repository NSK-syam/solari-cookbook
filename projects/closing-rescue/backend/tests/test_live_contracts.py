"""Opt-in compatibility checks against current external services."""

import os

import pytest

from septic_sentinel.adapters.base import PropertyLocation
from septic_sentinel.adapters.delaware import DelawareSepticAdapter
from septic_sentinel.adapters.mireye import MireyeAdapter
from septic_sentinel.adapters.noaa import NoaaPrecipitationAdapter
from septic_sentinel.domain import EvidenceStatus

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_CONTRACTS") != "1",
    reason="Set RUN_LIVE_CONTRACTS=1 to call Mireye, Delaware, and NOAA",
)


@pytest.mark.live
async def test_mireye_mcp_required_tools_are_available() -> None:
    adapter = MireyeAdapter(
        os.getenv("SEPTIC_SENTINEL_MIREYE_COMMAND", "uvx"),
        os.getenv("SEPTIC_SENTINEL_MIREYE_ARGS", "mireye-mcp").split(),
    )
    tools = await adapter.discover_tools()
    assert {"mireye_lookup", "mireye_fetch"} <= tools


@pytest.mark.live
async def test_delaware_completed_no_match_is_not_an_api_failure() -> None:
    result = await DelawareSepticAdapter().collect(
        "contract",
        PropertyLocation(address="Dover, DE", parcel_id="NONEXISTENT-CONTRACT-PARCEL"),
    )
    assert result[0].status == EvidenceStatus.RECORD_NOT_FOUND
    assert result[0].payload["query_completed"] is True


@pytest.mark.live
async def test_noaa_contract_returns_a_typed_observation_result() -> None:
    result = await NoaaPrecipitationAdapter(lookback_hours=24).collect(
        "contract",
        PropertyLocation(address="Dover, DE", lat=39.1573, lng=-75.5198),
    )
    assert result[0].status in {EvidenceStatus.SUCCESS, EvidenceStatus.STALE}
    assert result[0].kind == "recent_precipitation"
