"""Recent rainfall evidence from the authoritative NOAA/NWS API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

NWS_API = "https://api.weather.gov"


class NoaaPrecipitationAdapter(EvidenceAdapter):
    source_name = "NOAA National Weather Service"

    def __init__(self, client: httpx.AsyncClient | None = None, lookback_hours: int = 72) -> None:
        self._client = client
        self.lookback_hours = lookback_hours

    async def collect(self, case_id: str, location: PropertyLocation) -> list[Evidence]:
        if location.lat is None or location.lng is None:
            return [self._unavailable(case_id, ValueError("Coordinates are required"))]

        async def query(request_id: str) -> dict[str, Any]:
            client = self._client or httpx.AsyncClient(timeout=20)
            close = self._client is None
            headers = {
                "User-Agent": "SepticSentinel/0.1 (competition demo; contact: local-user)",
                "Accept": "application/geo+json",
                "X-Request-ID": request_id,
            }
            try:
                points_url = f"{NWS_API}/points/{location.lat:.4f},{location.lng:.4f}"
                points = await client.get(points_url, headers=headers)
                points.raise_for_status()
                stations_url = points.json()["properties"]["observationStations"]
                stations = await client.get(stations_url, params={"limit": 5}, headers=headers)
                stations.raise_for_status()
                features = stations.json().get("features", [])
                if not features:
                    raise ValueError("NOAA returned no observation stations")
                station = features[0]
                station_id = station["properties"]["stationIdentifier"]
                end = datetime.now(UTC)
                start = end - timedelta(hours=self.lookback_hours)
                observations_url = f"{NWS_API}/stations/{station_id}/observations"
                observations = await client.get(
                    observations_url,
                    params={
                        "start": start.isoformat().replace("+00:00", "Z"),
                        "end": end.isoformat().replace("+00:00", "Z"),
                        "limit": 200,
                    },
                    headers=headers,
                )
                observations.raise_for_status()
                return {
                    "points_url": points_url,
                    "stations_url": stations_url,
                    "observations_url": str(observations.url),
                    "station": station,
                    "start": start,
                    "end": end,
                    "features": observations.json().get("features", []),
                }
            finally:
                if close:
                    await client.aclose()

        try:
            data, request_id = await with_retries(query, max_attempts=2, timeout_seconds=25)
            return [self._normalize(case_id, data, request_id)]
        except (RetryExhaustedError, httpx.HTTPError, KeyError, ValueError) as exc:
            return [self._unavailable(case_id, exc)]

    def _normalize(self, case_id: str, data: dict[str, Any], request_id: str) -> Evidence:
        precipitation_mm = 0.0
        measured_hours = 0
        missing_hours = 0
        latest_timestamp: str | None = None
        for feature in data["features"]:
            properties = feature.get("properties", {})
            latest_timestamp = latest_timestamp or properties.get("timestamp")
            measurement = properties.get("precipitationLastHour") or {}
            value = measurement.get("value")
            if value is None:
                missing_hours += 1
                continue
            measured_hours += 1
            precipitation_mm += float(value) * 1000

        station = data["station"]
        station_properties = station.get("properties", {})
        station_id = station_properties.get("stationIdentifier", "unknown")
        status = EvidenceStatus.SUCCESS if measured_hours else EvidenceStatus.STALE
        citations = (
            [
                Citation(
                    source_name="NOAA National Weather Service",
                    source_url=data["observations_url"],
                    label=f"Station {station_id} observations",
                )
            ]
            if measured_hours
            else []
        )
        return Evidence(
            case_id=case_id,
            source=self.source_name,
            kind="recent_precipitation",
            status=status,
            request_id=request_id,
            confidence=min(1.0, measured_hours / max(1, self.lookback_hours)),
            payload={
                "station_id": station_id,
                "station_name": station_properties.get("name"),
                "station_coordinates": station.get("geometry", {}).get("coordinates"),
                "lookback_hours": self.lookback_hours,
                "period_start": data["start"].isoformat(),
                "period_end": data["end"].isoformat(),
                "precipitation_mm": round(precipitation_mm, 2),
                "measured_observations": measured_hours,
                "missing_observations": missing_hours,
                "latest_observation": latest_timestamp,
                "interpretation": "urgency_modifier_only",
            },
            citations=citations,
            raw={"feature_count": len(data["features"])},
        )

    def _unavailable(self, case_id: str, error: Exception) -> Evidence:
        return Evidence(
            case_id=case_id,
            source=self.source_name,
            kind="recent_precipitation",
            status=EvidenceStatus.EVIDENCE_UNAVAILABLE,
            payload={"lookback_hours": self.lookback_hours},
            error_code=type(error).__name__,
            error_message=str(error),
        )
