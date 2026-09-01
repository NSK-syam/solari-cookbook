"""Mireye MCP adapter with provenance-preserving normalization."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from septic_sentinel.adapters.base import EvidenceAdapter, LocationAdapter, PropertyLocation
from septic_sentinel.domain import EvidenceStatus
from septic_sentinel.models import Citation, Evidence

MIREYE_API_URL = "https://api.mireye.com"
REQUIRED_TOOLS = frozenset({"mireye_lookup", "mireye_fetch"})


class MireyeCapabilityError(RuntimeError):
    pass


class MireyeAdapter(LocationAdapter, EvidenceAdapter):
    source_name = "Mireye"

    def __init__(self, command: str, args: list[str]) -> None:
        self.parameters = StdioServerParameters(command=command, args=args)

    @asynccontextmanager
    async def _session(self):
        async with stdio_client(self.parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                available = {tool.name for tool in tools.tools}
                missing = REQUIRED_TOOLS - available
                if missing:
                    raise MireyeCapabilityError(
                        f"Mireye MCP is missing required tools: {', '.join(sorted(missing))}"
                    )
                yield session, available

    async def discover_tools(self) -> set[str]:
        async with self._session() as (_, available):
            return available

    async def resolve(self, case_id: str, address: str) -> tuple[PropertyLocation | None, Evidence]:
        try:
            async with self._session() as (session, _):
                result = await session.call_tool(
                    "mireye_lookup", {"input": address, "include_parcel": True}
                )
        except Exception as exc:
            return None, self._error_evidence(case_id, "location", exc)

        payload = self._payload(result)
        if result.isError:
            return None, self._error_evidence(case_id, "location", RuntimeError(str(payload)))

        disposition = str(payload.get("disposition", "")).lower()
        if disposition == "clarify":
            return None, Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="location",
                status=EvidenceStatus.AMBIGUOUS,
                payload=payload,
                citations=self._citations(payload),
                raw=payload,
            )
        if disposition != "resolved":
            return None, Evidence(
                case_id=case_id,
                source=self.source_name,
                kind="location",
                status=EvidenceStatus.RECORD_NOT_FOUND,
                payload=payload,
                citations=self._citations(payload),
                raw=payload,
            )

        coordinate = payload.get("coordinate") or payload.get("location") or {}
        lat = self._number(coordinate.get("lat") or payload.get("lat"))
        lng = self._number(coordinate.get("lng") or coordinate.get("lon") or payload.get("lng"))
        if lat is None or lng is None:
            return None, self._error_evidence(
                case_id, "location", ValueError("Resolved Mireye result lacks coordinates")
            )

        parcel = payload.get("parcel") or {}
        parcel_id = (
            parcel.get("apn")
            or parcel.get("parcel_id")
            or parcel.get("id")
            or payload.get("parcel_id")
        )
        resolved_address = payload.get("resolved_address") or payload.get("address") or address
        location = PropertyLocation(
            address=str(resolved_address),
            lat=lat,
            lng=lng,
            parcel_id=str(parcel_id) if parcel_id else None,
        )
        evidence = Evidence(
            case_id=case_id,
            source=self.source_name,
            kind="location",
            status=EvidenceStatus.SUCCESS,
            confidence=self._number(payload.get("confidence")),
            payload=payload,
            citations=self._citations(payload),
            raw=payload,
        )
        return location, evidence

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        if location.lat is None or location.lng is None:
            return [
                self._error_evidence(
                    case_id, "physical_context", ValueError("Coordinates are required")
                )
            ]
        requests = (("terrain", "terrain"), ("flood_risk", "flood_risk"))
        evidence: list[Evidence] = []
        try:
            async with self._session() as (session, _):
                for preset, kind in requests:
                    result = await session.call_tool(
                        "mireye_fetch",
                        {"lat": location.lat, "lng": location.lng, "preset": preset},
                    )
                    payload = self._payload(result)
                    if result.isError:
                        evidence.append(
                            self._error_evidence(case_id, kind, RuntimeError(str(payload)))
                        )
                    else:
                        evidence.append(
                            Evidence(
                                case_id=case_id,
                                source=self.source_name,
                                kind=kind,
                                status=EvidenceStatus.SUCCESS,
                                payload=payload,
                                citations=self._citations(payload),
                                raw=payload,
                            )
                        )
        except Exception as exc:
            return [self._error_evidence(case_id, "physical_context", exc)]
        return evidence

    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        if result.structuredContent:
            return dict(result.structuredContent)
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                try:
                    import json

                    parsed = json.loads(text)
                    return parsed if isinstance(parsed, dict) else {"value": parsed}
                except (TypeError, ValueError):
                    return {"text": text}
        return {}

    @classmethod
    def _citations(cls, payload: dict[str, Any]) -> list[Citation]:
        found: dict[str, Citation] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                url = value.get("source_url") or value.get("url")
                source = value.get("source") or value.get("source_name")
                if url and source:
                    key = f"{source}|{url}"
                    if key not in found:
                        fetched = value.get("fetched_at") or value.get("retrieved_at")
                        try:
                            retrieved_at = datetime.fromisoformat(
                                str(fetched).replace("Z", "+00:00")
                            )
                        except (TypeError, ValueError):
                            retrieved_at = datetime.now(UTC)
                        found[key] = Citation(
                            source_name=str(source),
                            source_url=str(url),
                            retrieved_at=retrieved_at,
                            confidence=cls._number(value.get("confidence")),
                        )
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(payload)
        if not found:
            found[MIREYE_API_URL] = Citation(
                source_name="Mireye",
                source_url=MIREYE_API_URL,
                label="Mireye MCP tool response",
            )
        return list(found.values())

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error_evidence(case_id: str, kind: str, error: Exception) -> Evidence:
        return Evidence(
            case_id=case_id,
            source="Mireye",
            kind=kind,
            status=EvidenceStatus.EVIDENCE_UNAVAILABLE,
            error_code=type(error).__name__,
            error_message=str(error),
            payload={},
        )
