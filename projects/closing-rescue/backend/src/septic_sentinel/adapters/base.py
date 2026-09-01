"""Common adapter contract and reliability helpers."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import uuid4

from septic_sentinel.models import Evidence

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class PropertyLocation:
    address: str
    lat: float | None = None
    lng: float | None = None
    parcel_id: str | None = None


class EvidenceAdapter(ABC):
    source_name: str

    @abstractmethod
    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        """Collect normalized evidence for a property."""


class LocationAdapter(ABC):
    source_name: str

    @abstractmethod
    async def resolve(self, case_id: str, address: str) -> tuple[PropertyLocation | None, Evidence]:
        """Resolve an address and return both location and auditable evidence."""


class RetryExhaustedError(RuntimeError):
    def __init__(self, request_id: str, cause: Exception) -> None:
        super().__init__(f"Source request {request_id} failed after retries: {cause}")
        self.request_id = request_id
        self.cause = cause


async def with_retries(
    operation: Callable[[str], Awaitable[ResultT]],
    *,
    max_attempts: int = 2,
    timeout_seconds: float = 20.0,
) -> tuple[ResultT, str]:
    """Run an external operation with bounded timeout and retry behavior."""
    request_id = f"req_{uuid4().hex}"
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with asyncio.timeout(timeout_seconds):
                return await operation(request_id), request_id
        except (TimeoutError, OSError, ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                await asyncio.sleep(0.2 * (attempt + 1))
    assert last_error is not None
    raise RetryExhaustedError(request_id, last_error)
