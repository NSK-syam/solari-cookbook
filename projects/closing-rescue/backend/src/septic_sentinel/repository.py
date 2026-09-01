"""SQLite persistence behind a small repository interface."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias, TypeVar

import aiosqlite
from pydantic import BaseModel

from septic_sentinel.domain import ApprovalState, CaseState, Disposition, require_transition
from septic_sentinel.models import (
    ActionAttempt,
    ApprovalRequest,
    AuditEvent,
    CaseCreate,
    CaseRecord,
    CaseView,
    ContradictionFinding,
    DecisionSnapshot,
    Evidence,
    ExposureEstimate,
    PortfolioInvestigation,
    PortfolioLoan,
    PortfolioSnapshot,
    PriorityAssessment,
    VendorSelection,
)
from septic_sentinel.solari_models import SolariExecutionView

ModelT = TypeVar("ModelT", bound=BaseModel)
ExposureStage: TypeAlias = Literal["before_rescue", "after_rescue"]


class CaseNotFoundError(LookupError):
    pass


class RepositoryError(Exception):
    """Base error for portfolio persistence operations."""


class RepositoryNotFoundError(RepositoryError, LookupError):
    """A requested portfolio or portfolio loan does not exist."""


class RepositoryConflictError(RepositoryError):
    """Stored immutable state conflicts with the requested operation."""


class SQLiteRepository:
    def __init__(self, db_path: Path, migration_path: Path | None = None) -> None:
        self.db_path = db_path
        self.migration_path = migration_path or (
            Path(__file__).resolve().parents[2] / "migrations"
        )

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migrations = (
            sorted(self.migration_path.glob("*.sql"))
            if self.migration_path.is_dir()
            else [self.migration_path]
        )
        async with self._connect() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            await db.commit()
            for migration_path in migrations:
                migration_bytes = migration_path.read_bytes()
                migration = migration_bytes.decode("utf-8-sig")
                checksum = sha256(migration_bytes).hexdigest()
                statements = self._migration_statements(migration)
                await db.execute("BEGIN IMMEDIATE")
                try:
                    applied = await (
                        await db.execute(
                            "SELECT checksum FROM schema_migrations WHERE name = ?",
                            (migration_path.name,),
                        )
                    ).fetchone()
                    if applied:
                        self._require_matching_migration_checksum(
                            migration_path.name, checksum, applied[0]
                        )
                        await db.rollback()
                        continue
                    for statement in statements:
                        await db.execute(statement)
                    await db.execute(
                        "INSERT INTO schema_migrations (name, checksum, applied_at) "
                        "VALUES (?, ?, ?)",
                        (
                            migration_path.name,
                            checksum,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

    async def ping(self) -> None:
        """Verify that the configured database accepts a read query."""
        async with self._connect() as db:
            row = await (await db.execute("SELECT 1")).fetchone()
        if row is None or row[0] != 1:
            raise RepositoryError("database readiness probe returned an invalid result")

    async def create_portfolio(
        self, snapshot: PortfolioSnapshot
    ) -> tuple[PortfolioSnapshot, bool]:
        existing = await self.get_portfolio_by_idempotency(snapshot.idempotency_key)
        if existing is not None:
            return existing, False

        async with self._connect() as db:
            try:
                await db.execute(
                    "INSERT INTO portfolios (id, idempotency_key, data, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        snapshot.id,
                        snapshot.idempotency_key,
                        snapshot.model_dump_json(exclude_computed_fields=True),
                        snapshot.created_at.isoformat(),
                    ),
                )
                await db.executemany(
                    "INSERT INTO portfolio_loans "
                    "(id, portfolio_id, external_loan_id, loan_order, data, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            loan.id,
                            snapshot.id,
                            loan.external_loan_id,
                            order,
                            loan.model_dump_json(exclude_computed_fields=True),
                            snapshot.created_at.isoformat(),
                        )
                        for order, loan in enumerate(snapshot.loans)
                    ],
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                concurrent = await self.get_portfolio_by_idempotency(
                    snapshot.idempotency_key
                )
                if concurrent is not None:
                    return concurrent, False
                raise RepositoryConflictError(
                    "portfolio identity conflicts with stored data"
                ) from exc
        return snapshot, True

    async def get_portfolio(self, portfolio_id: str) -> PortfolioSnapshot:
        row = await self._fetch_one("SELECT data FROM portfolios WHERE id = ?", (portfolio_id,))
        if row is None:
            raise RepositoryNotFoundError(portfolio_id)
        return PortfolioSnapshot.model_validate_json(row[0])

    async def get_portfolio_by_idempotency(self, key: str) -> PortfolioSnapshot | None:
        row = await self._fetch_one(
            "SELECT data FROM portfolios WHERE idempotency_key = ?", (key,)
        )
        return PortfolioSnapshot.model_validate_json(row[0]) if row else None

    async def save_solari_execution(self, execution: SolariExecutionView) -> None:
        """Upsert the latest public receipt without ever persisting credentials."""
        await self._require_portfolio(execution.portfolio_id)
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO solari_executions (portfolio_id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(portfolio_id) DO UPDATE SET data = excluded.data, "
                "updated_at = excluded.updated_at",
                (
                    execution.portfolio_id,
                    execution.model_dump_json(),
                    execution.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_solari_execution(self, portfolio_id: str) -> SolariExecutionView | None:
        await self._require_portfolio(portfolio_id)
        row = await self._fetch_one(
            "SELECT data FROM solari_executions WHERE portfolio_id = ?", (portfolio_id,)
        )
        return SolariExecutionView.model_validate_json(row[0]) if row else None

    async def list_portfolio_loans(self, portfolio_id: str) -> list[PortfolioLoan]:
        await self._require_portfolio(portfolio_id)
        rows = await self._fetch_all(
            "SELECT data FROM portfolio_loans WHERE portfolio_id = ? ORDER BY loan_order",
            (portfolio_id,),
        )
        return [PortfolioLoan.model_validate_json(row[0]) for row in rows]

    async def add_priority_assessments(
        self,
        portfolio_id: str,
        assessments: Iterable[PriorityAssessment],
        batch_id: str | None = None,
    ) -> str:
        items = list(assessments)
        if not items:
            raise ValueError("priority assessment batch must not be empty")
        serialized = [item.model_dump_json() for item in items]
        resolved_batch_id = (
            self._validate_batch_id(batch_id)
            if batch_id is not None
            else self._stable_id("priority_batch", *serialized)
        )
        batch_created_at = datetime.now(UTC).isoformat()
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                batch_row = await (
                    await db.execute(
                        "SELECT sequence FROM priority_assessment_batches "
                        "WHERE portfolio_id = ? AND batch_id = ?",
                        (portfolio_id, resolved_batch_id),
                    )
                ).fetchone()
                if batch_row:
                    batch_sequence = batch_row[0]
                    rows = await (
                        await db.execute(
                            "SELECT id, external_loan_id, rank_order, data "
                            "FROM priority_assessments WHERE portfolio_id = ? "
                            "AND batch_id = ? ORDER BY rank_order",
                            (portfolio_id, resolved_batch_id),
                        )
                    ).fetchall()
                    if not self._priority_batch_rows_match(
                        portfolio_id, resolved_batch_id, items, rows
                    ):
                        raise RepositoryConflictError(
                            "priority assessment batch is sealed and differs"
                        )
                    await db.commit()
                    return resolved_batch_id
                else:
                    cursor = await db.execute(
                        "INSERT INTO priority_assessment_batches "
                        "(portfolio_id, batch_id, created_at) VALUES (?, ?, ?)",
                        (portfolio_id, resolved_batch_id, batch_created_at),
                    )
                    batch_sequence = cursor.lastrowid
                for rank, (item, data) in enumerate(zip(items, serialized, strict=True)):
                    ruleset = item.scenario_profile_version or ""
                    existing = await (
                        await db.execute(
                            "SELECT data, rank_order FROM priority_assessments "
                            "WHERE portfolio_id = ? AND batch_id = ? "
                            "AND external_loan_id = ?",
                            (
                                portfolio_id,
                                resolved_batch_id,
                                item.external_loan_id,
                            ),
                        )
                    ).fetchone()
                    if existing:
                        if existing != (data, rank):
                            raise RepositoryConflictError(
                                "priority assessment conflicts with immutable snapshot"
                            )
                        continue
                    row_id = self._stable_id(
                        "priority",
                        portfolio_id,
                        resolved_batch_id,
                        item.external_loan_id,
                    )
                    await db.execute(
                        "INSERT INTO priority_assessments "
                        "(id, portfolio_id, batch_sequence, batch_id, external_loan_id, "
                        "rank_order, "
                        "formula_version, ruleset_version, data, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row_id,
                            portfolio_id,
                            batch_sequence,
                            resolved_batch_id,
                            item.external_loan_id,
                            rank,
                            item.formula_version,
                            ruleset,
                            data,
                            batch_created_at,
                        ),
                    )
                await db.commit()
            except RepositoryConflictError:
                await db.rollback()
                raise
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                if await self._priority_batch_matches(
                    portfolio_id, resolved_batch_id, items
                ):
                    return resolved_batch_id
                await self._raise_link_or_conflict(portfolio_id, items, exc)
        return resolved_batch_id

    async def list_priority_assessments(
        self, portfolio_id: str, batch_id: str | None = None
    ) -> list[PriorityAssessment]:
        await self._require_portfolio(portfolio_id)
        resolved_batch_id = batch_id
        if resolved_batch_id is None:
            batches = await self.list_priority_assessment_batches(portfolio_id)
            if not batches:
                return []
            resolved_batch_id = batches[0]
        else:
            resolved_batch_id = self._validate_batch_id(resolved_batch_id)
        rows = await self._fetch_all(
            "SELECT data FROM priority_assessments WHERE portfolio_id = ? "
            "AND batch_id = ? ORDER BY rank_order",
            (portfolio_id, resolved_batch_id),
        )
        return [PriorityAssessment.model_validate_json(row[0]) for row in rows]

    async def list_priority_assessment_batches(self, portfolio_id: str) -> list[str]:
        await self._require_portfolio(portfolio_id)
        rows = await self._fetch_all(
            "SELECT batch_id FROM priority_assessment_batches "
            "WHERE portfolio_id = ? ORDER BY sequence DESC",
            (portfolio_id,),
        )
        return [row[0] for row in rows]

    async def select_investigation(
        self, portfolio_id: str, external_loan_id: str
    ) -> tuple[PortfolioInvestigation, bool]:
        await self._require_loan(portfolio_id, external_loan_id)
        existing = await self.get_investigation(portfolio_id)
        if existing is not None:
            if existing.external_loan_id == external_loan_id:
                return existing, False
            raise RepositoryConflictError("a different loan is already selected")
        item = PortfolioInvestigation(
            id=self._stable_id("investigation", portfolio_id),
            portfolio_id=portfolio_id,
            external_loan_id=external_loan_id,
        )
        try:
            await self._insert_model(
                "INSERT INTO portfolio_investigations "
                "(id, portfolio_id, external_loan_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    item.id,
                    portfolio_id,
                    external_loan_id,
                    item.model_dump_json(),
                    item.created_at.isoformat(),
                ),
            )
        except aiosqlite.IntegrityError as exc:
            concurrent = await self.get_investigation(portfolio_id)
            if concurrent and concurrent.external_loan_id == external_loan_id:
                return concurrent, False
            raise RepositoryConflictError("a different loan is already selected") from exc
        return item, True

    async def get_investigation(
        self, portfolio_id: str
    ) -> PortfolioInvestigation | None:
        await self._require_portfolio(portfolio_id)
        row = await self._fetch_one(
            "SELECT data FROM portfolio_investigations WHERE portfolio_id = ?",
            (portfolio_id,),
        )
        return PortfolioInvestigation.model_validate_json(row[0]) if row else None

    async def add_contradiction(
        self, portfolio_id: str, external_loan_id: str, item: ContradictionFinding
    ) -> None:
        await self._add_linked_snapshot(
            table="contradictions",
            row_id=item.id,
            portfolio_id=portfolio_id,
            external_loan_id=external_loan_id,
            data=item.model_dump_json(),
            created_at=item.created_at,
        )

    async def list_contradictions(
        self, portfolio_id: str, external_loan_id: str
    ) -> list[ContradictionFinding]:
        await self._require_loan(portfolio_id, external_loan_id)
        rows = await self._fetch_all(
            "SELECT data FROM contradictions WHERE portfolio_id = ? "
            "AND external_loan_id = ? ORDER BY created_at, id",
            (portfolio_id, external_loan_id),
        )
        return [ContradictionFinding.model_validate_json(row[0]) for row in rows]

    async def add_vendor_selection(
        self, portfolio_id: str, external_loan_id: str, item: VendorSelection
    ) -> None:
        data = item.model_dump_json()
        await self._add_linked_snapshot(
            table="vendor_selections",
            row_id=self._stable_id(
                "vendor", portfolio_id, external_loan_id, item.evaluated_at.isoformat()
            ),
            portfolio_id=portfolio_id,
            external_loan_id=external_loan_id,
            data=data,
            created_at=item.selected_at,
        )

    async def get_latest_vendor_selection(
        self, portfolio_id: str, external_loan_id: str
    ) -> VendorSelection | None:
        await self._require_loan(portfolio_id, external_loan_id)
        row = await self._fetch_one(
            "SELECT data FROM vendor_selections WHERE portfolio_id = ? "
            "AND external_loan_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (portfolio_id, external_loan_id),
        )
        return VendorSelection.model_validate_json(row[0]) if row else None

    async def add_exposure_estimate(
        self,
        portfolio_id: str,
        external_loan_id: str,
        stage: ExposureStage,
        item: ExposureEstimate,
    ) -> None:
        stage = self._validate_exposure_stage(stage)
        await self._require_loan(portfolio_id, external_loan_id)
        existing = await self._fetch_one(
            "SELECT id, data FROM exposure_estimates WHERE portfolio_id = ? "
            "AND external_loan_id = ? AND stage = ?",
            (portfolio_id, external_loan_id, stage),
        )
        if existing:
            if existing == (item.id, item.model_dump_json()):
                return
            raise RepositoryConflictError("exposure stage already has an immutable estimate")
        try:
            await self._insert_model(
                "INSERT INTO exposure_estimates "
                "(id, portfolio_id, external_loan_id, stage, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item.id,
                    portfolio_id,
                    external_loan_id,
                    stage,
                    item.model_dump_json(),
                    item.created_at.isoformat(),
                ),
            )
        except aiosqlite.IntegrityError as exc:
            winner = await self._fetch_one(
                "SELECT id, data FROM exposure_estimates WHERE portfolio_id = ? "
                "AND external_loan_id = ? AND stage = ?",
                (portfolio_id, external_loan_id, stage),
            )
            if winner == (item.id, item.model_dump_json()):
                return
            raise RepositoryConflictError("exposure estimate identity conflicts") from exc

    async def get_exposure_estimate(
        self,
        portfolio_id: str,
        external_loan_id: str,
        stage: ExposureStage,
    ) -> ExposureEstimate | None:
        stage = self._validate_exposure_stage(stage)
        await self._require_loan(portfolio_id, external_loan_id)
        row = await self._fetch_one(
            "SELECT data FROM exposure_estimates WHERE portfolio_id = ? "
            "AND external_loan_id = ? AND stage = ?",
            (portfolio_id, external_loan_id, stage),
        )
        return ExposureEstimate.model_validate_json(row[0]) if row else None

    async def create_case(self, request: CaseCreate) -> tuple[CaseRecord, bool]:
        existing = await self.get_case_by_idempotency(request.idempotency_key)
        if existing is not None:
            return existing, False
        case = CaseRecord(
            **request.model_dump(exclude={"idempotency_key"}),
            idempotency_key=request.idempotency_key,
        )
        async with self._connect() as db:
            try:
                await db.execute(
                    """
                    INSERT INTO cases (
                        id, external_case_id, idempotency_key, state, disposition,
                        data, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.id,
                        case.external_case_id,
                        case.idempotency_key,
                        case.state,
                        case.disposition,
                        case.model_dump_json(),
                        case.created_at.isoformat(),
                        case.updated_at.isoformat(),
                    ),
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                concurrent = await self.get_case_by_idempotency(request.idempotency_key)
                if concurrent is None:
                    raise
                return concurrent, False
        return case, True

    async def get_case(self, case_id: str) -> CaseRecord:
        record = await self._fetch_one("SELECT data FROM cases WHERE id = ?", (case_id,))
        if record is None:
            raise CaseNotFoundError(case_id)
        return CaseRecord.model_validate_json(record[0])

    async def get_case_by_idempotency(self, key: str) -> CaseRecord | None:
        record = await self._fetch_one("SELECT data FROM cases WHERE idempotency_key = ?", (key,))
        return CaseRecord.model_validate_json(record[0]) if record else None

    async def list_cases(self) -> list[CaseRecord]:
        rows = await self._fetch_all("SELECT data FROM cases ORDER BY created_at DESC", ())
        return [CaseRecord.model_validate_json(row[0]) for row in rows]

    async def transition_case(
        self, case_id: str, target: CaseState, disposition: Disposition | None = None
    ) -> CaseRecord:
        current = await self.get_case(case_id)
        require_transition(current.state, target)
        updated = current.model_copy(
            update={
                "state": target,
                "disposition": disposition if disposition is not None else current.disposition,
                "updated_at": datetime.now(UTC),
            }
        )
        async with self._connect() as db:
            await db.execute(
                "UPDATE cases SET state = ?, disposition = ?, data = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    updated.state,
                    updated.disposition,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    case_id,
                ),
            )
            await db.commit()
        return updated

    async def add_evidence(self, item: Evidence) -> None:
        await self._insert_model(
            "INSERT INTO evidence (id, case_id, source, status, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.case_id,
                item.source,
                item.status,
                item.model_dump_json(),
                item.retrieved_at.isoformat(),
            ),
        )

    async def add_evidence_many(self, items: Iterable[Evidence]) -> None:
        for item in items:
            await self.add_evidence(item)

    async def add_decision(self, item: DecisionSnapshot) -> None:
        await self._insert_model(
            "INSERT INTO decisions (id, case_id, data, created_at) VALUES (?, ?, ?, ?)",
            (item.id, item.case_id, item.model_dump_json(), item.created_at.isoformat()),
        )

    async def add_approval(self, item: ApprovalRequest) -> tuple[ApprovalRequest, bool]:
        existing = await self._fetch_one(
            "SELECT data FROM approvals WHERE idempotency_key = ?", (item.idempotency_key,)
        )
        if existing:
            return ApprovalRequest.model_validate_json(existing[0]), False
        await self._insert_model(
            """
            INSERT INTO approvals (
                id, case_id, idempotency_key, state, data, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.case_id,
                item.idempotency_key,
                item.state,
                item.model_dump_json(),
                item.created_at.isoformat(),
                item.created_at.isoformat(),
            ),
        )
        return item, True

    async def compare_and_swap_approval(
        self,
        expected: ApprovalRequest,
        updated: ApprovalRequest,
        event: AuditEvent,
    ) -> ApprovalRequest:
        """Atomically replace an exact approval snapshot and append its audit event."""
        if expected.id != updated.id or expected.case_id != event.case_id:
            raise ValueError("Approval CAS identities do not match")
        allowed = {
            (ApprovalState.PENDING, ApprovalState.PENDING),
            (ApprovalState.PENDING, ApprovalState.APPROVED),
            (ApprovalState.PENDING, ApprovalState.REJECTED),
            (ApprovalState.APPROVED, ApprovalState.CONSUMED),
        }
        if (expected.state, updated.state) not in allowed:
            raise ValueError("Unsupported approval state transition")
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await (
                    await db.execute(
                        "SELECT state, data FROM approvals WHERE id = ?", (expected.id,)
                    )
                ).fetchone()
                expected_row = (expected.state, expected.model_dump_json())
                if row != expected_row:
                    raise RepositoryConflictError("approval snapshot changed concurrently")
                cursor = await db.execute(
                    "UPDATE approvals SET state = ?, data = ?, updated_at = ? "
                    "WHERE id = ? AND state = ? AND data = ?",
                    (
                        updated.state,
                        updated.model_dump_json(),
                        (updated.decided_at or datetime.now(UTC)).isoformat(),
                        expected.id,
                        expected.state,
                        expected.model_dump_json(),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RepositoryConflictError("approval snapshot changed concurrently")
                await db.execute(
                    "INSERT INTO audit_events (id, case_id, event_type, data, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.case_id,
                        event.event_type,
                        event.model_dump_json(),
                        event.created_at.isoformat(),
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return updated

    async def get_approval(self, approval_id: str) -> ApprovalRequest:
        record = await self._fetch_one("SELECT data FROM approvals WHERE id = ?", (approval_id,))
        if record is None:
            raise CaseNotFoundError(approval_id)
        return ApprovalRequest.model_validate_json(record[0])

    async def add_action(self, item: ActionAttempt) -> tuple[ActionAttempt, bool]:
        existing = await self._fetch_one(
            "SELECT data FROM actions WHERE idempotency_key = ?", (item.idempotency_key,)
        )
        if existing:
            return ActionAttempt.model_validate_json(existing[0]), False
        await self._insert_model(
            """
            INSERT INTO actions (
                id, case_id, approval_id, idempotency_key, state, data, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.case_id,
                item.approval_id,
                item.idempotency_key,
                item.state,
                item.model_dump_json(),
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ),
        )
        return item, True

    async def update_action(self, item: ActionAttempt) -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE actions SET state = ?, data = ?, updated_at = ? WHERE id = ?",
                (item.state, item.model_dump_json(), item.updated_at.isoformat(), item.id),
            )
            await db.commit()

    async def get_action_by_approval(self, approval_id: str) -> ActionAttempt | None:
        record = await self._fetch_one(
            "SELECT data FROM actions WHERE approval_id = ? ORDER BY created_at DESC LIMIT 1",
            (approval_id,),
        )
        return ActionAttempt.model_validate_json(record[0]) if record else None

    async def add_event(self, item: AuditEvent) -> None:
        await self._insert_model(
            """
            INSERT INTO audit_events (id, case_id, event_type, data, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.case_id,
                item.event_type,
                item.model_dump_json(),
                item.created_at.isoformat(),
            ),
        )

    async def get_view(self, case_id: str) -> CaseView:
        case = await self.get_case(case_id)
        evidence = await self._models_for_case("evidence", case_id, Evidence)
        decisions = await self._models_for_case("decisions", case_id, DecisionSnapshot)
        approvals = await self._models_for_case("approvals", case_id, ApprovalRequest)
        actions = await self._models_for_case("actions", case_id, ActionAttempt)
        events = await self._models_for_case("audit_events", case_id, AuditEvent)
        return CaseView(
            case=case,
            evidence=evidence,
            decisions=decisions,
            approvals=approvals,
            actions=actions,
            events=events,
        )

    async def _models_for_case(self, table: str, case_id: str, model: type[ModelT]) -> list[ModelT]:
        allowed_tables = {"evidence", "decisions", "approvals", "actions", "audit_events"}
        if table not in allowed_tables:
            raise ValueError("Unsupported table")
        rows = await self._fetch_all(
            f"SELECT data FROM {table} WHERE case_id = ? ORDER BY created_at", (case_id,)
        )
        return [model.model_validate_json(row[0]) for row in rows]

    async def _insert_model(self, sql: str, values: tuple[object, ...]) -> None:
        async with self._connect() as db:
            await db.execute(sql, values)
            await db.commit()

    async def _add_linked_snapshot(
        self,
        *,
        table: str,
        row_id: str,
        portfolio_id: str,
        external_loan_id: str,
        data: str,
        created_at: datetime,
    ) -> None:
        allowed_tables = {"contradictions", "vendor_selections"}
        if table not in allowed_tables:
            raise ValueError("unsupported snapshot table")
        await self._require_loan(portfolio_id, external_loan_id)
        existing = await self._fetch_one(
            f"SELECT portfolio_id, external_loan_id, data FROM {table} WHERE id = ?",
            (row_id,),
        )
        if existing:
            if existing == (portfolio_id, external_loan_id, data):
                return
            raise RepositoryConflictError(f"{table} snapshot identity conflicts")
        try:
            await self._insert_model(
                f"INSERT INTO {table} "
                "(id, portfolio_id, external_loan_id, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (row_id, portfolio_id, external_loan_id, data, created_at.isoformat()),
            )
        except aiosqlite.IntegrityError as exc:
            winner = await self._fetch_one(
                f"SELECT portfolio_id, external_loan_id, data FROM {table} WHERE id = ?",
                (row_id,),
            )
            if winner == (portfolio_id, external_loan_id, data):
                return
            raise RepositoryConflictError(f"{table} snapshot identity conflicts") from exc

    async def _require_portfolio(self, portfolio_id: str) -> None:
        row = await self._fetch_one("SELECT 1 FROM portfolios WHERE id = ?", (portfolio_id,))
        if row is None:
            raise RepositoryNotFoundError(f"portfolio not found: {portfolio_id}")

    async def _require_loan(self, portfolio_id: str, external_loan_id: str) -> None:
        await self._require_portfolio(portfolio_id)
        row = await self._fetch_one(
            "SELECT 1 FROM portfolio_loans WHERE portfolio_id = ? AND external_loan_id = ?",
            (portfolio_id, external_loan_id),
        )
        if row is None:
            raise RepositoryNotFoundError(
                f"loan {external_loan_id} not found in portfolio {portfolio_id}"
            )

    async def _raise_link_or_conflict(
        self,
        portfolio_id: str,
        items: list[PriorityAssessment],
        exc: aiosqlite.IntegrityError,
    ) -> None:
        await self._require_portfolio(portfolio_id)
        for item in items:
            await self._require_loan(portfolio_id, item.external_loan_id)
        raise RepositoryConflictError("priority assessment identity conflicts") from exc

    async def _priority_batch_matches(
        self,
        portfolio_id: str,
        batch_id: str,
        items: list[PriorityAssessment],
    ) -> bool:
        rows = await self._fetch_all(
            "SELECT id, external_loan_id, rank_order, data "
            "FROM priority_assessments WHERE portfolio_id = ? AND batch_id = ? "
            "ORDER BY rank_order",
            (portfolio_id, batch_id),
        )
        return self._priority_batch_rows_match(portfolio_id, batch_id, items, rows)

    def _priority_batch_rows_match(
        self,
        portfolio_id: str,
        batch_id: str,
        items: list[PriorityAssessment],
        rows: list[tuple],
    ) -> bool:
        expected = [
            (
                self._stable_id(
                    "priority", portfolio_id, batch_id, item.external_loan_id
                ),
                item.external_loan_id,
                rank,
                item.model_dump_json(),
            )
            for rank, item in enumerate(items)
        ]
        return rows == expected

    @staticmethod
    def _validate_batch_id(batch_id: object) -> str:
        if type(batch_id) is not str or not batch_id.strip():
            raise ValueError("batch_id must be a nonblank string")
        return batch_id.strip()

    @staticmethod
    def _validate_exposure_stage(stage: object) -> ExposureStage:
        if stage not in {"before_rescue", "after_rescue"} or type(stage) is not str:
            raise ValueError("unsupported exposure stage")
        return stage

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = sha256("\x1f".join(parts).encode()).hexdigest()
        return f"{prefix}_{digest}"

    @staticmethod
    def _require_matching_migration_checksum(
        name: str, expected: str, applied: str
    ) -> None:
        if applied != expected:
            raise RepositoryConflictError(
                f"migration checksum mismatch for {name}: database history differs"
            )

    @classmethod
    def _migration_statements(cls, migration: str) -> list[str]:
        statements: list[str] = []
        buffer = ""
        for character in migration:
            buffer += character
            if character == ";" and sqlite3.complete_statement(buffer):
                cls._append_migration_statement(statements, buffer)
                buffer = ""
        cls._append_migration_statement(statements, buffer)
        return statements

    @classmethod
    def _append_migration_statement(
        cls, statements: list[str], statement: str
    ) -> None:
        executable = cls._without_leading_sql_comments(statement)
        if not executable:
            return
        first_keyword = executable.split(None, 1)[0].rstrip(";").upper()
        if first_keyword in {
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT",
            "RELEASE",
            "END",
        }:
            raise RepositoryConflictError(
                f"migration transaction control is not allowed: {first_keyword}"
            )
        statements.append(statement)

    @staticmethod
    def _without_leading_sql_comments(statement: str) -> str:
        remaining = statement.lstrip()
        while remaining:
            if remaining.startswith("--"):
                newline = remaining.find("\n")
                if newline < 0:
                    return ""
                remaining = remaining[newline + 1 :].lstrip()
                continue
            if remaining.startswith("/*"):
                close = remaining.find("*/", 2)
                if close < 0:
                    return ""
                remaining = remaining[close + 2 :].lstrip()
                continue
            break
        return remaining

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.db_path)
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA busy_timeout = 5000")
            yield db
        finally:
            await db.close()

    async def _fetch_one(self, sql: str, values: tuple[object, ...]) -> tuple | None:
        async with self._connect() as db:
            cursor = await db.execute(sql, values)
            return await cursor.fetchone()

    async def _fetch_all(self, sql: str, values: tuple[object, ...]) -> list[tuple]:
        async with self._connect() as db:
            cursor = await db.execute(sql, values)
            return await cursor.fetchall()
