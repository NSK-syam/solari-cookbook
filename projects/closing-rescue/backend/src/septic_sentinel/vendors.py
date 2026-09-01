"""Deterministic scouting over frozen synthetic vendor availability."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from septic_sentinel.models import VendorConsideration, VendorOption, VendorSelection
from septic_sentinel.vendor_rules import (
    normalize_approved_names,
    vendor_option_order_key,
    vendor_rejection_reasons,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "data" / "delaware-inspectors.json"
PACKAGED_FIXTURE = resources.files("septic_sentinel").joinpath("data", "delaware-inspectors.json")


def load_delaware_inspectors() -> list[VendorOption]:
    """Load the packaged, synthetic Delaware inspector availability fixture."""
    payload = json.loads(PACKAGED_FIXTURE.read_text(encoding="utf-8"))
    return [VendorOption.model_validate_json(json.dumps(item)) for item in payload["options"]]


class VendorScout:
    """Select an eligible option deterministically without booking it."""

    def select(
        self,
        options: Iterable[VendorOption],
        approved_names: Iterable[str],
        cutoff: datetime,
        as_of: datetime,
    ) -> VendorSelection:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = cutoff.astimezone(UTC)
        as_of = as_of.astimezone(UTC)
        approved = normalize_approved_names(approved_names)
        normalized = tuple(
            VendorOption.model_validate(item.model_dump(mode="python")) for item in options
        )
        ordered = tuple(
            sorted(
                normalized,
                key=lambda item: vendor_option_order_key(
                    appointment_at=item.appointment_at,
                    price_cents=item.price_cents,
                    vendor_name=item.vendor_name,
                    option_id=item.id,
                ),
            )
        )
        considered: list[VendorConsideration] = []
        viable: list[VendorOption] = []
        for item in ordered:
            reasons = vendor_rejection_reasons(
                vendor_name=item.vendor_name,
                approved=item.approved,
                qualified=item.qualified,
                appointment_at=item.appointment_at,
                available_as_of=item.available_as_of,
                approved_names=approved,
                cutoff=cutoff,
                as_of=as_of,
            )
            considered.append(
                VendorConsideration(option=item, rejection_reason_codes=reasons)
            )
            if not reasons:
                viable.append(item)

        return VendorSelection(
            selected=viable[0] if viable else None,
            considered=tuple(considered),
            approved_names=approved,
            cutoff=cutoff,
            evaluated_at=as_of,
            selected_at=as_of,
        )
