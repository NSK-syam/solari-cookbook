"""Application dependency assembly."""

from pathlib import Path

from septic_sentinel.actions import ActionService
from septic_sentinel.adapters.delaware import DelawareSepticAdapter
from septic_sentinel.adapters.fixtures import (
    FixtureDelawareAdapter,
    FixtureMireyeAdapter,
    FixtureNoaaAdapter,
    FixtureStore,
)
from septic_sentinel.adapters.mireye import MireyeAdapter
from septic_sentinel.adapters.noaa import NoaaPrecipitationAdapter
from septic_sentinel.closing_rescue import ClosingRescueService
from septic_sentinel.config import Settings
from septic_sentinel.contradictions import ContradictionEngine
from septic_sentinel.exposure import ExposureEngine
from septic_sentinel.orchestrator import EvidenceCollector
from septic_sentinel.priority import PriorityEngine
from septic_sentinel.reasoner import ReasoningEngine
from septic_sentinel.repository import SQLiteRepository
from septic_sentinel.service import SepticSentinelService
from septic_sentinel.solari_execution import (
    LiveBrowserAdapter,
    LiveDesktopAdapter,
    LiveSandboxAdapter,
    SolariExecutionService,
)
from septic_sentinel.vendors import VendorScout


def build_service(config: Settings) -> SepticSentinelService:
    repository = SQLiteRepository(Path(config.db_path))
    if config.mode == "fixture":
        store = FixtureStore(Path(config.fixture_root))
        mireye = FixtureMireyeAdapter(store)
        evidence_adapters = [
            mireye,
            FixtureDelawareAdapter(store),
            FixtureNoaaAdapter(store),
        ]
    else:
        mireye = MireyeAdapter(config.mireye_command, config.mireye_args.split())
        evidence_adapters = [mireye, DelawareSepticAdapter(), NoaaPrecipitationAdapter()]
    collector = EvidenceCollector(
        repository=repository,
        location_adapter=mireye,
        evidence_adapters=evidence_adapters,
    )
    return SepticSentinelService(
        repository=repository,
        collector=collector,
        reasoner=ReasoningEngine(config.openai_model),
        actions=ActionService(repository, config.approval_recovery_key.get_secret_value()),
    )


def build_closing_rescue_service(config: Settings) -> ClosingRescueService:
    """Build Closing Rescue while preserving the established v1 assembly."""
    case_service = build_service(config)
    return ClosingRescueService(
        case_service=case_service,
        priority=PriorityEngine(),
        contradictions=ContradictionEngine(),
        vendors=VendorScout(),
        exposure=ExposureEngine(),
    )


def build_solari_execution_service(
    config: Settings, repository: SQLiteRepository
) -> SolariExecutionService | None:
    """Build live Solari adapters only when a key is explicitly configured."""
    if config.solari_api_key is None:
        return None
    api_key = config.solari_api_key.get_secret_value()
    timeout_ms = int(config.solari_timeout_seconds * 1_000)
    artifact_dir = Path(config.solari_artifact_dir)
    return SolariExecutionService(
        repository,
        LiveSandboxAdapter(api_key, config.solari_base_url, artifact_dir, timeout_ms),
        LiveBrowserAdapter(api_key, config.solari_base_url, artifact_dir, timeout_ms),
        LiveDesktopAdapter(api_key, config.solari_base_url, artifact_dir, timeout_ms),
        timeout_seconds=config.solari_timeout_seconds,
    )
