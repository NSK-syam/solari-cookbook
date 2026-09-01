"""Case orchestration for location resolution and parallel evidence collection."""

from __future__ import annotations

import asyncio
from time import monotonic

from septic_sentinel.adapters.base import EvidenceAdapter, LocationAdapter
from septic_sentinel.domain import CaseState, EvidenceStatus
from septic_sentinel.models import AuditEvent, CaseRecord, Evidence
from septic_sentinel.repository import SQLiteRepository


class EvidenceCollector:
    def __init__(
        self,
        repository: SQLiteRepository,
        location_adapter: LocationAdapter,
        evidence_adapters: list[EvidenceAdapter],
    ) -> None:
        self.repository = repository
        self.location_adapter = location_adapter
        self.evidence_adapters = evidence_adapters

    async def collect(self, case: CaseRecord) -> list[Evidence]:
        await self.repository.transition_case(case.id, CaseState.RESOLVING)
        await self._event(case.id, "location.started", "Resolving property with Mireye")
        location, location_evidence = await self.location_adapter.resolve(case.id, case.address)
        await self.repository.add_evidence(location_evidence)
        await self._event(
            case.id,
            "location.completed",
            f"Location resolution returned {location_evidence.status}",
            {"evidence_id": location_evidence.id, "status": location_evidence.status},
        )

        if location_evidence.status == EvidenceStatus.AMBIGUOUS:
            await self.repository.transition_case(case.id, CaseState.WAITING_FOR_CLARIFICATION)
            return [location_evidence]
        if location is None:
            await self.repository.transition_case(case.id, CaseState.MANUAL_REVIEW)
            return [location_evidence]

        await self.repository.transition_case(case.id, CaseState.COLLECTING)
        for adapter in self.evidence_adapters:
            await self._event(
                case.id,
                "source.started",
                f"Collecting evidence from {adapter.source_name}",
                {"source": adapter.source_name},
            )

        async def timed_collect(adapter: EvidenceAdapter):
            started = monotonic()
            try:
                return await adapter.collect(case.id, location), round(
                    (monotonic() - started) * 1000, 1
                )
            except BaseException as exc:
                return exc, round((monotonic() - started) * 1000, 1)

        results = await asyncio.gather(
            *(timed_collect(adapter) for adapter in self.evidence_adapters),
            return_exceptions=True,
        )
        collected: list[Evidence] = [location_evidence]
        for adapter, timed_result in zip(self.evidence_adapters, results, strict=True):
            if isinstance(timed_result, BaseException):
                result, latency_ms = timed_result, 0.0
            else:
                result, latency_ms = timed_result
            if isinstance(result, BaseException):
                items = [
                    Evidence(
                        case_id=case.id,
                        source=adapter.source_name,
                        kind="adapter_failure",
                        status=EvidenceStatus.EVIDENCE_UNAVAILABLE,
                        error_code=type(result).__name__,
                        error_message=str(result),
                        payload={},
                    )
                ]
            else:
                items = result
            await self.repository.add_evidence_many(items)
            collected.extend(items)
            await self._event(
                case.id,
                "source.completed",
                f"{adapter.source_name} returned {len(items)} evidence item(s)",
                {
                    "source": adapter.source_name,
                    "statuses": [item.status for item in items],
                    "evidence_ids": [item.id for item in items],
                    "latency_ms": latency_ms,
                },
            )

        await self.repository.transition_case(case.id, CaseState.REASONING)
        await self._event(case.id, "reasoning.ready", "Evidence collection is complete")
        return collected

    async def _event(
        self, case_id: str, event_type: str, message: str, data: dict | None = None
    ) -> None:
        await self.repository.add_event(
            AuditEvent(case_id=case_id, event_type=event_type, message=message, data=data or {})
        )
