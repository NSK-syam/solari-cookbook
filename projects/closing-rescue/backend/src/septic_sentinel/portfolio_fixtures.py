"""Load the frozen synthetic portfolio used by the competition workflow."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from septic_sentinel.models import PortfolioLoan

FIXTURE_PATH = Path(__file__).resolve().parent / "data" / "closing-rescue.json"
PACKAGED_FIXTURE = resources.files("septic_sentinel").joinpath(
    "data", "closing-rescue.json"
)


def load_competition_portfolio() -> list[PortfolioLoan]:
    """Return validated loans from the deterministic competition fixture."""
    payload = json.loads(PACKAGED_FIXTURE.read_text(encoding="utf-8"))
    return [PortfolioLoan.model_validate(item) for item in payload["loans"]]
