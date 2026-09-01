"""Deterministic, privacy-safe adapters for the judged demo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from septic_sentinel.adapters.base import EvidenceAdapter, LocationAdapter, PropertyLocation
from septic_sentinel.domain import EvidenceStatus
from septic_sentinel.models import Citation, Evidence

MIREYE_URL = "https://api.mireye.com/mcp"
DELAWARE_URL = "https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/mv7j-tx3u"
NOAA_URL = "https://api.weather.gov"


class FixtureStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._records = [
            json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))
        ]
        self._by_address = {record["address"].lower(): record for record in self._records}
        self._by_parcel = {record["location"]["parcel_id"]: record for record in self._records}

    def for_address(self, address: str) -> dict[str, Any] | None:
        return self._by_address.get(address.lower())

    def for_location(self, location: PropertyLocation) -> dict[str, Any] | None:
        return self._by_parcel.get(location.parcel_id or "")


class FixtureMireyeAdapter(LocationAdapter, EvidenceAdapter):
    source_name = "Mireye"

    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    async def resolve(self, case_id: str, address: str) -> tuple[PropertyLocation | None, Evidence]:
        record = self.store.for_address(address)
        if record is None:
            return None, Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="location",
                status=EvidenceStatus.AMBIGUOUS,
                payload={"reason": "fixture_address_not_found"},
            )
        location_data = record["location"]
        location = PropertyLocation(
            address=record["address"],
            lat=location_data["lat"],
            lng=location_data["lng"],
            parcel_id=location_data["parcel_id"],
        )
        return location, Evidence(
            case_id=case_id,
            source=self.source_name,
            kind="location",
            status=EvidenceStatus.SUCCESS,
            confidence=location_data["payload"]["confidence"],
            payload=location_data["payload"],
            citations=[_citation("Mireye MCP", MIREYE_URL, "Recorded fixture response")],
            raw=location_data["payload"],
        )

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        record = self.store.for_location(location)
        if record is None:
            return [_unavailable(case_id, self.source_name, "physical_context")]
        return [
            Evidence(
                case_id=case_id,
                source=self.source_name,
                kind=kind,
                status=EvidenceStatus.SUCCESS,
                payload=record[kind],
                citations=[_citation("Mireye MCP", MIREYE_URL, f"Recorded {kind} fixture")],
                raw=record[kind],
            )
            for kind in ("terrain", "flood_risk")
        ]


class FixtureDelawareAdapter(EvidenceAdapter):
    source_name = "Delaware Open Data"

    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        record = self.store.for_location(location)
        if record is None:
            return [_unavailable(case_id, self.source_name, "septic_permit")]
        permit = record["permit"]
        status = EvidenceStatus(permit["status"])
        return [
            Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="septic_permit",
                status=status,
                confidence=1.0 if status == EvidenceStatus.SUCCESS else None,
                payload={key: value for key, value in permit.items() if key != "status"},
                citations=[
                    _citation(
                        "Delaware Department of Natural Resources and Environmental Control",
                        DELAWARE_URL,
                        "Recorded Permitted Septic Systems query",
                    )
                ],
                raw=permit,
            )
        ]


class FixtureNoaaAdapter(EvidenceAdapter):
    source_name = "NOAA National Weather Service"

    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        record = self.store.for_location(location)
        if record is None:
            return [_unavailable(case_id, self.source_name, "recent_precipitation")]
        return [
            Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="recent_precipitation",
                status=EvidenceStatus.SUCCESS,
                confidence=0.9,
                payload=record["precipitation"],
                citations=[
                    _citation(
                        "NOAA National Weather Service", NOAA_URL, "Recorded station observations"
                    )
                ],
                raw=record["precipitation"],
            )
        ]


def _citation(source: str, url: str, label: str) -> Citation:
    return Citation(source_name=source, source_url=url, label=label)


def _unavailable(case_id: str, source: str, kind: str) -> Evidence:
    return Evidence(
        case_id=case_id,
        source=source,
        kind=kind,
        status=EvidenceStatus.EVIDENCE_UNAVAILABLE,
        payload={},
        error_code="FixtureNotFound",
        error_message="No fixture matches the resolved property",
    )
