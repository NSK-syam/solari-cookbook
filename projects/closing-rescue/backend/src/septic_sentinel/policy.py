"""Deterministic evidence gates that run before model reasoning."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

from septic_sentinel.domain import Disposition, EvidenceStatus
from septic_sentinel.models import Evidence


class PolicyAssessment(BaseModel):
    clearance_allowed: bool
    required_disposition: Disposition | None = None
    reasons: list[str] = Field(default_factory=list)
    missing_required_sources: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    system_age_years: int | None = None
    environmental_modifiers: list[str] = Field(default_factory=list)
    days_to_closing: int


REQUIRED_KINDS = frozenset({"location", "terrain", "flood_risk", "septic_permit"})


def assess_policy(evidence: list[Evidence], closing_date: date) -> PolicyAssessment:
    by_kind: dict[str, list[Evidence]] = {}
    for item in evidence:
        by_kind.setdefault(item.kind, []).append(item)

    reasons: list[str] = []
    missing: list[str] = []
    conflicts: list[str] = []
    modifiers: list[str] = []
    required_disposition: Disposition | None = None

    for kind in REQUIRED_KINDS:
        items = by_kind.get(kind, [])
        if not items or all(item.status != EvidenceStatus.SUCCESS for item in items):
            missing.append(kind)

    location_items = by_kind.get("location", [])
    if any(item.status == EvidenceStatus.AMBIGUOUS for item in location_items):
        reasons.append("The property location is ambiguous and requires clarification.")
        required_disposition = Disposition.INVESTIGATE

    permit_items = by_kind.get("septic_permit", [])
    if any(item.status == EvidenceStatus.RECORD_NOT_FOUND for item in permit_items):
        reasons.append("No matching septic permit record was found in the completed query.")
        required_disposition = Disposition.INVESTIGATE

    successful_permits = [item for item in permit_items if item.status == EvidenceStatus.SUCCESS]
    permit_parcels = {
        str(item.payload.get("parcel_id"))
        for item in successful_permits
        if item.payload.get("parcel_id")
    }
    location_parcels = {
        str(
            item.payload.get("parcel_id")
            or (item.payload.get("parcel") or {}).get("apn")
            or (item.payload.get("parcel") or {}).get("parcel_id")
        )
        for item in location_items
        if item.status == EvidenceStatus.SUCCESS
    }
    location_parcels.discard("None")
    if permit_parcels and location_parcels and permit_parcels.isdisjoint(location_parcels):
        conflicts.append("Mireye and permit records identify different parcels.")
        required_disposition = Disposition.INVESTIGATE

    system_age = _system_age(successful_permits)
    if system_age is not None and system_age >= 25:
        reasons.append(
            f"The available permit date indicates a system age of approximately {system_age} years."
        )

    for item in by_kind.get("terrain", []) + by_kind.get("flood_risk", []):
        if item.status == EvidenceStatus.SUCCESS:
            modifiers.extend(_environmental_modifiers(item.payload))

    for item in by_kind.get("recent_precipitation", []):
        rainfall = _find_number(item.payload, {"precipitation_mm"})
        if item.status == EvidenceStatus.SUCCESS and rainfall is not None and rainfall >= 25:
            modifiers.append(f"Recent observed precipitation was {rainfall:.1f} mm.")

    days_to_closing = (closing_date - datetime.now(UTC).date()).days
    if system_age is not None and system_age >= 25 and modifiers and days_to_closing <= 21:
        required_disposition = Disposition.INSPECT
        reasons.append(
            "Older-system evidence, site modifiers, and the closing deadline "
            "justify inspection review."
        )

    if missing:
        reasons.append(
            "Required evidence is missing or unavailable: " + ", ".join(sorted(missing)) + "."
        )
        if required_disposition != Disposition.INSPECT:
            required_disposition = Disposition.INVESTIGATE

    return PolicyAssessment(
        clearance_allowed=not missing and not conflicts and required_disposition is None,
        required_disposition=required_disposition,
        reasons=reasons,
        missing_required_sources=sorted(missing),
        conflicts=conflicts,
        system_age_years=system_age,
        environmental_modifiers=list(dict.fromkeys(modifiers)),
        days_to_closing=days_to_closing,
    )


def _system_age(items: list[Evidence]) -> int | None:
    dates: list[date] = []
    for item in items:
        for permit in item.payload.get("permits", []):
            raw = permit.get("appreceiveddate")
            if not raw:
                continue
            try:
                dates.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date())
            except ValueError:
                continue
    if not dates:
        return None
    newest = max(dates)
    today = datetime.now(UTC).date()
    return today.year - newest.year - ((today.month, today.day) < (newest.month, newest.day))


def _environmental_modifiers(payload: dict[str, Any]) -> list[str]:
    modifiers: list[str] = []
    drainage = _find_text(payload, {"drainage_class", "soil_drainage", "soil_drainage_class"})
    if drainage and any(word in drainage.lower() for word in ("poor", "very poor")):
        modifiers.append(f"Soil drainage is reported as {drainage}.")
    slope = _find_number(payload, {"slope_pct", "slope_percent", "slope"})
    if slope is not None and slope >= 15:
        modifiers.append(f"Reported slope is {slope:.1f} percent.")
    flood = _find_value(payload, {"within_floodplain", "floodplain", "flood_risk"})
    if flood is True or str(flood).lower() in {"true", "high", "yes"}:
        modifiers.append("The property is reported within a floodplain or high flood-risk area.")
    return modifiers


def _find_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in keys:
                if isinstance(nested, dict) and "value" in nested:
                    return nested["value"]
                return nested
            found = _find_value(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_value(nested, keys)
            if found is not None:
                return found
    return None


def _find_number(value: Any, keys: set[str]) -> float | None:
    raw = _find_value(value, keys)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _find_text(value: Any, keys: set[str]) -> str | None:
    raw = _find_value(value, keys)
    return str(raw) if raw is not None else None
