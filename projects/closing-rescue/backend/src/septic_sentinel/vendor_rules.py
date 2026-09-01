"""Dependency-free deterministic rules for synthetic vendor scouting audits."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

VendorReasonCode = Literal[
    "name_not_approved",
    "not_approved",
    "not_qualified",
    "appointment_expired",
    "appointment_after_cutoff",
    "availability_observation_after_as_of",
]


def normalize_approved_names(names: Iterable[str]) -> tuple[str, ...]:
    """Return a stable, unique policy snapshot and reject semantic blanks."""
    normalized: list[str] = []
    for name in names:
        if not isinstance(name, str):
            raise ValueError("Approved vendor names must be strings")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Approved vendor names must not be blank")
        normalized.append(clean_name)
    return tuple(sorted(set(normalized)))


def vendor_rejection_reasons(
    *,
    vendor_name: str,
    approved: bool,
    qualified: bool,
    appointment_at: datetime,
    available_as_of: datetime,
    approved_names: tuple[str, ...],
    cutoff: datetime,
    as_of: datetime,
) -> tuple[VendorReasonCode, ...]:
    """Return fixed reasons; expiry wins if appointment boundaries overlap."""
    reasons: list[VendorReasonCode] = []
    if vendor_name not in approved_names:
        reasons.append("name_not_approved")
    if not approved:
        reasons.append("not_approved")
    if not qualified:
        reasons.append("not_qualified")
    if appointment_at <= as_of:
        reasons.append("appointment_expired")
    elif appointment_at >= cutoff:
        reasons.append("appointment_after_cutoff")
    if available_as_of > as_of:
        reasons.append("availability_observation_after_as_of")
    return tuple(reasons)


def vendor_option_order_key(
    *, appointment_at: datetime, price_cents: int, vendor_name: str, option_id: str
) -> tuple[datetime, int, str, str]:
    """Return the canonical deterministic option ordering key."""
    return appointment_at, price_cents, vendor_name, option_id
