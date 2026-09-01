"""Delaware Socrata permitted-septic dataset adapter."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx

from septic_sentinel.adapters.base import (
    EvidenceAdapter,
    PropertyLocation,
    RetryExhaustedError,
    with_retries,
)
from septic_sentinel.domain import EvidenceStatus
from septic_sentinel.models import Citation, Evidence

DATASET_ID = "mv7j-tx3u"
RESOURCE_URL = f"https://data.delaware.gov/resource/{DATASET_ID}.json"
DATASET_URL = (
    f"https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/{DATASET_ID}"
)
PUBLIC_FIELDS = (
    "permitnumber",
    "taxparcelnumbers",
    "appreceiveddate",
    "permitstatus",
    "septicsystemtype",
    "septicsystemsubtype",
    "constructiontype",
    "flowrate",
    "minimumsize",
    "proposedsize",
    "perkrate",
    "county",
    "url_for_permit_details",
)


class DelawareSepticAdapter(EvidenceAdapter):
    source_name = "Delaware Open Data"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        if not location.parcel_id:
            return [
                Evidence(
                    case_id=case_id,
                    source=self.source_name,
                    kind="septic_permit",
                    status=EvidenceStatus.RECORD_NOT_FOUND,
                    payload={"reason": "parcel_identifier_unavailable", "candidates": []},
                )
            ]

        async def query(request_id: str) -> list[dict[str, Any]]:
            client = self._client or httpx.AsyncClient(timeout=20)
            close = self._client is None
            try:
                response = await client.get(
                    RESOURCE_URL,
                    params={"$q": location.parcel_id, "$limit": "50"},
                    headers={"X-Request-ID": request_id},
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError("Delaware API returned a non-list response")
                return data
            finally:
                if close:
                    await client.aclose()

        try:
            rows, request_id = await with_retries(query, max_attempts=2, timeout_seconds=25)
        except (RetryExhaustedError, httpx.HTTPError, ValueError) as exc:
            return [
                Evidence(
                    case_id=case_id,
                    source=self.source_name,
                    kind="septic_permit",
                    status=EvidenceStatus.EVIDENCE_UNAVAILABLE,
                    payload={},
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
            ]

        target = self._normalize_parcel(location.parcel_id)
        matches = [
            self._normalize_row(row)
            for row in rows
            if target and target in self._normalize_parcel(str(row.get("taxparcelnumbers", "")))
        ]
        if not matches:
            return [
                Evidence(
                    case_id=case_id,
                    source=self.source_name,
                    kind="septic_permit",
                    status=EvidenceStatus.RECORD_NOT_FOUND,
                    request_id=request_id,
                    payload={
                        "parcel_id": location.parcel_id,
                        "query_completed": True,
                        "candidates": [],
                    },
                    citations=[
                        Citation(
                            source_name=(
                                "Delaware Department of Natural Resources and Environmental Control"
                            ),
                            source_url=DATASET_URL,
                            label="Completed Permitted Septic Systems query",
                        )
                    ],
                )
            ]

        citations = [
            Citation(
                source_name="Delaware Department of Natural Resources and Environmental Control",
                source_url=DATASET_URL,
                retrieved_at=datetime.now(UTC),
                label="Permitted Septic Systems dataset",
            )
        ]
        for row in matches:
            detail_url = row.get("url_for_permit_details")
            if detail_url:
                citations.append(
                    Citation(
                        source_name="Delaware septic permit record",
                        source_url=detail_url,
                        label=f"Permit {row.get('permitnumber', 'record')}",
                    )
                )
        return [
            Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="septic_permit",
                status=EvidenceStatus.SUCCESS,
                request_id=request_id,
                confidence=1.0 if len(matches) == 1 else 0.75,
                payload={
                    "parcel_id": location.parcel_id,
                    "match_method": "normalized_tax_parcel_number",
                    "candidate_count": len(matches),
                    "permits": matches,
                },
                citations=citations,
                raw=matches,
            )
        ]

    @staticmethod
    def _normalize_parcel(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        return {field: row[field] for field in PUBLIC_FIELDS if field in row}
