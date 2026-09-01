"""SQLite persistence contracts for Closing Rescue portfolio investigations."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import aiosqlite
import pytest
from pydantic import ValidationError

import septic_sentinel.repository as repository_module
from septic_sentinel.contradictions import ContradictionEngine
from septic_sentinel.exposure import ExposureEngine
from septic_sentinel.models import (
    CaseCreate,
    ContradictionFinding,
    NormalizedClaim,
    PortfolioSnapshot,
    TruthClass,
    VendorSelection,
)
from septic_sentinel.portfolio_fixtures import load_competition_portfolio
from septic_sentinel.priority import PriorityEngine
from septic_sentinel.repository import SQLiteRepository
from septic_sentinel.vendors import VendorScout, load_delaware_inspectors

AS_OF_DATE = date(2026, 8, 5)
AS_OF = datetime(2026, 8, 5, 18, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 11, 16, tzinfo=UTC)


def portfolio(*, key: str = "closing-rescue-run-1") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        id="portfolio_test",
        idempotency_key=key,
        loans=load_competition_portfolio(),
        created_at=AS_OF,
    )


@pytest.fixture
async def repo(tmp_path: Path) -> SQLiteRepository:
    repository = SQLiteRepository(tmp_path / "repository.sqlite3")
    await repository.initialize()
    return repository


async def test_initialize_runs_migrations_in_lexical_order_and_is_idempotent(
    tmp_path: Path,
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "002_second.sql").write_text(
        "INSERT INTO migration_order (position) VALUES ('second');",
        encoding="utf-8",
    )
    (migrations / "001_first.sql").write_text(
        "CREATE TABLE migration_order (position TEXT UNIQUE);"
        "INSERT INTO migration_order (position) VALUES ('first');",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "ordered.sqlite3", migrations)

    await repository.initialize()
    await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        rows = await (await db.execute("SELECT position FROM migration_order")).fetchall()
        ledger = await (
            await db.execute(
                "SELECT name, checksum FROM schema_migrations ORDER BY name"
            )
        ).fetchall()
    assert rows == [("first",), ("second",)]
    assert [row[0] for row in ledger] == ["001_first.sql", "002_second.sql"]
    assert all(len(row[1]) == 64 for row in ledger)


async def test_failed_migration_rolls_back_schema_and_ledger(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text(
        "CREATE TABLE should_rollback (id TEXT);"
        "INSERT INTO table_that_does_not_exist VALUES ('boom');",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "broken.sqlite3", migrations)

    with pytest.raises(aiosqlite.OperationalError):
        await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        table = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'should_rollback'"
            )
        ).fetchone()
        ledger = await (
            await db.execute("SELECT name FROM schema_migrations")
        ).fetchall()
    assert table is None
    assert ledger == []


async def test_concurrent_initialize_records_each_migration_once(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_once.sql").write_text(
        "CREATE TABLE initialize_once (value TEXT);"
        "INSERT INTO initialize_once VALUES ('applied');",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "concurrent-init.sqlite3", migrations)

    await asyncio.gather(*(repository.initialize() for _ in range(4)))

    async with aiosqlite.connect(repository.db_path) as db:
        rows = await (await db.execute("SELECT value FROM initialize_once")).fetchall()
        ledger = await (
            await db.execute("SELECT name FROM schema_migrations")
        ).fetchall()
    assert rows == [("applied",)]
    assert ledger == [("001_once.sql",)]


async def test_changed_applied_migration_checksum_is_rejected(tmp_path: Path) -> None:
    migration = tmp_path / "001_stable.sql"
    migration.write_text("CREATE TABLE stable_schema (id TEXT);", encoding="utf-8")
    repository = SQLiteRepository(tmp_path / "checksum.sqlite3", migration)
    await repository.initialize()
    migration.write_text("CREATE TABLE changed_schema (id TEXT);", encoding="utf-8")

    with pytest.raises(repository_module.RepositoryConflictError, match="checksum"):
        await repository.initialize()


@pytest.mark.parametrize("transaction_sql", ["ROLLBACK;", "COMMIT;"])
async def test_migration_rejects_embedded_transaction_control_atomically(
    tmp_path: Path, transaction_sql: str
) -> None:
    migration = tmp_path / "001_transaction_control.sql"
    migration.write_text(
        "CREATE TABLE transaction_escape (id TEXT);"
        f"{transaction_sql}"
        "CREATE TABLE must_not_exist (id TEXT);",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "transaction.sqlite3", migration)

    with pytest.raises(
        repository_module.RepositoryConflictError, match="transaction control"
    ):
        await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        escaped = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('transaction_escape', 'must_not_exist')"
            )
        ).fetchall()
        ledger = await (
            await db.execute("SELECT name FROM schema_migrations")
        ).fetchall()
    assert escaped == []
    assert ledger == []


async def test_migration_parser_accepts_triggers_comments_and_quoted_words(
    tmp_path: Path,
) -> None:
    migration = tmp_path / "001_trigger.sql"
    migration.write_text(
        "-- COMMIT and ROLLBACK are harmless in comments\n"
        "CREATE TABLE trigger_source (id TEXT PRIMARY KEY, value TEXT);\n"
        "CREATE TABLE trigger_log (message TEXT);\n"
        "CREATE TRIGGER log_insert AFTER INSERT ON trigger_source\n"
        "BEGIN\n"
        "  INSERT INTO trigger_log VALUES ('quoted COMMIT; and ROLLBACK;');\n"
        "END;\n"
        "/* BEGIN IMMEDIATE; is harmless here too */\n"
        "INSERT INTO trigger_source VALUES ('one', 'SAVEPOINT');\n",
        encoding="utf-8",
    )
    repository = SQLiteRepository(tmp_path / "trigger.sqlite3", migration)

    await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        log = await (await db.execute("SELECT message FROM trigger_log")).fetchall()
        trigger = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'log_insert'"
            )
        ).fetchone()
    assert log == [("quoted COMMIT; and ROLLBACK;",)]
    assert trigger == ("log_insert",)


async def test_repository_migrations_install_trigger_bodies(repo: SQLiteRepository) -> None:
    async with aiosqlite.connect(repo.db_path) as db:
        triggers = await (
            await db.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        ).fetchall()
    names = {row[0] for row in triggers}
    assert {
        "decisions_immutable_update",
        "audit_events_append_only_delete",
        "priority_assessments_immutable_update",
        "portfolio_investigations_immutable_delete",
    } <= names


@pytest.mark.parametrize(
    "transaction_sql",
    [
        "BEGIN;",
        "COMMIT;",
        "ROLLBACK;",
        "SAVEPOINT migration;",
        "RELEASE migration;",
        "END TRANSACTION;",
    ],
)
async def test_bom_prefixed_transaction_control_is_rejected_before_schema_work(
    tmp_path: Path, transaction_sql: str
) -> None:
    migration = tmp_path / "001_bom_control.sql"
    migration.write_bytes(
        b"\xef\xbb\xbf"
        + transaction_sql.encode()
        + b"CREATE TABLE bom_escape (id TEXT);"
    )
    repository = SQLiteRepository(tmp_path / "bom-control.sqlite3", migration)

    with pytest.raises(
        repository_module.RepositoryConflictError, match="transaction control"
    ):
        await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        escaped = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'bom_escape'"
            )
        ).fetchone()
        ledger = await (
            await db.execute("SELECT name FROM schema_migrations")
        ).fetchall()
    assert escaped is None
    assert ledger == []


async def test_bom_prefixed_normal_migration_is_atomic_and_checksum_tracks_raw_bytes(
    tmp_path: Path,
) -> None:
    migration = tmp_path / "001_bom_normal.sql"
    raw = b"\xef\xbb\xbfCREATE TABLE bom_normal (value TEXT);"
    migration.write_bytes(raw)
    repository = SQLiteRepository(tmp_path / "bom-normal.sqlite3", migration)

    await repository.initialize()

    async with aiosqlite.connect(repository.db_path) as db:
        table = await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'bom_normal'"
            )
        ).fetchone()
        checksum = await (
            await db.execute(
                "SELECT checksum FROM schema_migrations WHERE name = ?",
                (migration.name,),
            )
        ).fetchone()
    assert table == ("bom_normal",)
    assert checksum == (sha256(raw).hexdigest(),)

    migration.write_bytes(raw.removeprefix(b"\xef\xbb\xbf"))
    with pytest.raises(repository_module.RepositoryConflictError, match="checksum"):
        await repository.initialize()


async def test_existing_case_tables_still_work(repo: SQLiteRepository) -> None:
    created, was_created = await repo.create_case(
        CaseCreate(
            external_case_id="LEGACY-1",
            address="1 Legacy Lane, Dover, DE",
            closing_date=AS_OF_DATE,
            approver_identity="ops@example.test",
            idempotency_key="legacy-case-key",
        )
    )
    assert was_created is True
    assert await repo.get_case(created.id) == created


async def test_portfolio_and_all_47_loans_roundtrip_atomically(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    stored, created = await repo.create_portfolio(snapshot)

    assert created is True
    assert stored == snapshot
    assert await repo.get_portfolio(snapshot.id) == snapshot
    assert await repo.get_portfolio_by_idempotency(snapshot.idempotency_key) == snapshot
    assert await repo.list_portfolio_loans(snapshot.id) == snapshot.loans
    assert len(await repo.list_portfolio_loans(snapshot.id)) == 47
    assert stored.created_at.tzinfo is UTC


async def test_portfolio_idempotency_returns_original_without_duplicate_loans(
    repo: SQLiteRepository,
) -> None:
    original = portfolio()
    changed = original.model_copy(
        update={"id": "portfolio_changed", "loans": original.loans[:1]}
    )

    first, first_created = await repo.create_portfolio(original)
    second, second_created = await repo.create_portfolio(changed)

    assert (first, first_created) == (original, True)
    assert (second, second_created) == (original, False)
    assert len(await repo.list_portfolio_loans(original.id)) == 47


async def test_concurrent_duplicate_portfolio_creation_returns_one_snapshot(
    repo: SQLiteRepository,
) -> None:
    first = portfolio(key="concurrent-key")
    second = first.model_copy(update={"id": "portfolio_concurrent_competitor"})

    results = await asyncio.gather(
        repo.create_portfolio(first), repo.create_portfolio(second)
    )

    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    stored = await repo.get_portfolio_by_idempotency("concurrent-key")
    assert stored is not None
    assert stored == results[0][0]
    assert len(await repo.list_portfolio_loans(stored.id)) == 47


@pytest.mark.parametrize("duplicate_field", ["id", "external_loan_id"])
async def test_duplicate_loan_identity_rolls_back_whole_portfolio(
    repo: SQLiteRepository, duplicate_field: str
) -> None:
    snapshot = portfolio(key=f"duplicate-{duplicate_field}")
    loans = list(snapshot.loans[:2])
    loans[1] = loans[1].model_copy(
        update={duplicate_field: getattr(loans[0], duplicate_field)}
    )
    invalid = snapshot.model_copy(update={"loans": loans})

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.create_portfolio(invalid)

    assert await repo.get_portfolio_by_idempotency(invalid.idempotency_key) is None


async def test_priority_assessments_roundtrip_in_rank_order(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessments = PriorityEngine().rank(snapshot.loans, as_of=AS_OF_DATE)

    await repo.add_priority_assessments(snapshot.id, assessments)
    await repo.add_priority_assessments(snapshot.id, assessments)

    stored = await repo.list_priority_assessments(snapshot.id)
    assert stored == assessments
    assert len(stored) == 47
    assert stored[0].external_loan_id == "CR-0047"
    assert stored[0].source_inputs == assessments[0].source_inputs
    assert stored[0].input_signals == assessments[0].input_signals


async def test_concurrent_identical_priority_batches_are_idempotent(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessments = PriorityEngine().rank(snapshot.loans, as_of=AS_OF_DATE)

    batch_ids = await asyncio.gather(
        *(repo.add_priority_assessments(snapshot.id, assessments) for _ in range(4))
    )

    assert len(set(batch_ids)) == 1
    assert await repo.list_priority_assessments(snapshot.id) == assessments
    async with aiosqlite.connect(repo.db_path) as db:
        count = await (
            await db.execute(
                "SELECT COUNT(*) FROM priority_assessments WHERE portfolio_id = ?",
                (snapshot.id,),
            )
        ).fetchone()
    assert count == (47,)


async def test_priority_identity_with_different_data_is_a_conflict(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    changed = assessment.model_copy(update={"selection_explanation": "Changed snapshot"})
    batch_id = await repo.add_priority_assessments(
        snapshot.id, [assessment], batch_id="fixed-priority-run"
    )

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_priority_assessments(
            snapshot.id, [changed], batch_id="fixed-priority-run"
        )

    assert batch_id == "fixed-priority-run"
    assert await repo.list_priority_assessments(snapshot.id, batch_id) == [assessment]


@pytest.mark.parametrize("replay_kind", ["subset", "superset", "reordered", "changed"])
async def test_explicit_priority_batch_rejects_any_partial_or_changed_replay(
    repo: SQLiteRepository, replay_kind: str
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessments = PriorityEngine().rank(snapshot.loans[:2], as_of=AS_OF_DATE)
    if replay_kind == "superset":
        original = assessments[:1]
        replay = assessments
    else:
        original = assessments
        if replay_kind == "subset":
            replay = assessments[:1]
        elif replay_kind == "reordered":
            replay = list(reversed(assessments))
        else:
            replay = [
                assessments[0],
                assessments[1].model_copy(
                    update={"selection_explanation": "Changed sealed batch"}
                ),
            ]
    await repo.add_priority_assessments(
        snapshot.id, original, batch_id="sealed-priority-run"
    )

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_priority_assessments(
            snapshot.id, replay, batch_id="sealed-priority-run"
        )

    assert await repo.list_priority_assessments(
        snapshot.id, "sealed-priority-run"
    ) == original


async def test_explicit_priority_batch_rejects_forged_stored_row_identity(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    batch_id = "forged-row-run"
    async with aiosqlite.connect(repo.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute(
            "INSERT INTO priority_assessment_batches "
            "(portfolio_id, batch_id, created_at) VALUES (?, ?, ?)",
            (snapshot.id, batch_id, AS_OF.isoformat()),
        )
        await db.execute(
            "INSERT INTO priority_assessments "
            "(id, portfolio_id, batch_sequence, batch_id, external_loan_id, rank_order, "
            "formula_version, ruleset_version, data, created_at) "
            "VALUES ('forged-row-id', ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (
                snapshot.id,
                cursor.lastrowid,
                batch_id,
                assessment.external_loan_id,
                assessment.formula_version,
                assessment.scenario_profile_version or "",
                assessment.model_dump_json(),
                AS_OF.isoformat(),
            ),
        )
        await db.commit()

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_priority_assessments(
            snapshot.id, [assessment], batch_id=batch_id
        )


async def test_concurrent_explicit_priority_full_replays_are_idempotent(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessments = PriorityEngine().rank(snapshot.loans, as_of=AS_OF_DATE)

    batch_ids = await asyncio.gather(
        *(
            repo.add_priority_assessments(
                snapshot.id, assessments, batch_id="concurrent-sealed-run"
            )
            for _ in range(4)
        )
    )

    assert batch_ids == ["concurrent-sealed-run"] * 4
    assert await repo.list_priority_assessments(
        snapshot.id, "concurrent-sealed-run"
    ) == assessments


async def test_concurrent_different_explicit_priority_batches_have_one_winner(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessments = PriorityEngine().rank(snapshot.loans[:2], as_of=AS_OF_DATE)
    changed = [
        assessments[0],
        assessments[1].model_copy(
            update={"selection_explanation": "Concurrent changed batch"}
        ),
    ]

    results = await asyncio.gather(
        repo.add_priority_assessments(
            snapshot.id, assessments, batch_id="concurrent-different-run"
        ),
        repo.add_priority_assessments(
            snapshot.id, changed, batch_id="concurrent-different-run"
        ),
        return_exceptions=True,
    )

    assert sum(result == "concurrent-different-run" for result in results) == 1
    conflicts = [result for result in results if isinstance(result, BaseException)]
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], repository_module.RepositoryConflictError)
    stored = await repo.list_priority_assessments(
        snapshot.id, "concurrent-different-run"
    )
    assert stored in (assessments, changed)


async def test_different_priority_batches_coexist_and_latest_is_deterministic(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    changed = assessment.model_copy(update={"selection_explanation": "Re-evaluated snapshot"})

    first_batch = await repo.add_priority_assessments(snapshot.id, [assessment])
    second_batch = await repo.add_priority_assessments(snapshot.id, [changed])

    assert first_batch != second_batch
    assert await repo.list_priority_assessment_batches(snapshot.id) == [
        second_batch,
        first_batch,
    ]
    assert await repo.list_priority_assessments(snapshot.id) == [changed]
    assert await repo.list_priority_assessments(snapshot.id, first_batch) == [assessment]
    assert await repo.list_priority_assessments(snapshot.id, second_batch) == [changed]


async def test_priority_latest_uses_sequence_when_timestamps_and_lexical_ids_disagree(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    changed = assessment.model_copy(update={"selection_explanation": "Newest tied batch"})
    loan_id = assessment.external_loan_id
    tied_at = AS_OF.isoformat()

    async with aiosqlite.connect(repo.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for row_id, batch_id, item in (
            ("priority_old", "z-lexically-later-old", assessment),
            ("priority_new", "a-lexically-earlier-new", changed),
        ):
            cursor = await db.execute(
                "INSERT INTO priority_assessment_batches "
                "(portfolio_id, batch_id, created_at) VALUES (?, ?, ?)",
                (snapshot.id, batch_id, tied_at),
            )
            await db.execute(
                "INSERT INTO priority_assessments "
                "(id, portfolio_id, batch_sequence, batch_id, external_loan_id, "
                "rank_order, formula_version, ruleset_version, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                (
                    row_id,
                    snapshot.id,
                    cursor.lastrowid,
                    batch_id,
                    loan_id,
                    item.formula_version,
                    item.scenario_profile_version or "",
                    item.model_dump_json(),
                    tied_at,
                ),
            )
        await db.commit()

    assert await repo.list_priority_assessment_batches(snapshot.id) == [
        "a-lexically-earlier-new",
        "z-lexically-later-old",
    ]
    assert await repo.list_priority_assessments(snapshot.id) == [changed]


async def test_concurrent_priority_batch_order_matches_database_sequence(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    changed = assessment.model_copy(update={"selection_explanation": "Concurrent batch"})

    await asyncio.gather(
        repo.add_priority_assessments(snapshot.id, [assessment], batch_id="z-batch"),
        repo.add_priority_assessments(snapshot.id, [changed], batch_id="a-batch"),
    )

    async with aiosqlite.connect(repo.db_path) as db:
        rows = await (
            await db.execute(
                "SELECT batch_id FROM priority_assessment_batches "
                "WHERE portfolio_id = ? ORDER BY sequence DESC",
                (snapshot.id,),
            )
        ).fetchall()
    assert await repo.list_priority_assessment_batches(snapshot.id) == [
        row[0] for row in rows
    ]


async def test_priority_batch_rolls_back_if_any_loan_link_is_invalid(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    forged = assessment.model_copy(update={"external_loan_id": "missing-loan"})

    with pytest.raises(repository_module.RepositoryNotFoundError):
        await repo.add_priority_assessments(snapshot.id, [assessment, forged])

    assert await repo.list_priority_assessments(snapshot.id) == []
    assert await repo.list_priority_assessment_batches(snapshot.id) == []


async def test_investigation_selection_is_once_idempotent_and_portfolio_scoped(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    chosen = snapshot.loans[0].external_loan_id

    first, created = await repo.select_investigation(snapshot.id, chosen)
    second, created_again = await repo.select_investigation(snapshot.id, chosen)

    assert created is True
    assert created_again is False
    assert second == first == await repo.get_investigation(snapshot.id)
    assert first.portfolio_id == snapshot.id
    assert first.external_loan_id == chosen
    assert first.created_at.tzinfo is UTC

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.select_investigation(snapshot.id, snapshot.loans[1].external_loan_id)
    with pytest.raises(repository_module.RepositoryNotFoundError):
        await repo.select_investigation(snapshot.id, "FOREIGN-LOAN")


async def test_get_investigation_distinguishes_missing_portfolio_from_no_selection(
    repo: SQLiteRepository,
) -> None:
    with pytest.raises(repository_module.RepositoryNotFoundError):
        await repo.get_investigation("missing-portfolio")

    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assert await repo.get_investigation(snapshot.id) is None


async def test_concurrent_same_loan_selections_converge_on_one_record(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id

    results = await asyncio.gather(
        *(repo.select_investigation(snapshot.id, loan_id) for _ in range(4))
    )

    assert sum(created for _, created in results) == 1
    assert len({item.id for item, _ in results}) == 1
    assert all(item == results[0][0] for item, _ in results)
    async with aiosqlite.connect(repo.db_path) as db:
        count = await (
            await db.execute(
                "SELECT COUNT(*) FROM portfolio_investigations WHERE portfolio_id = ?",
                (snapshot.id,),
            )
        ).fetchone()
    assert count == (1,)


async def test_concurrent_different_loan_selections_have_one_clear_winner(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_ids = [loan.external_loan_id for loan in snapshot.loans[:2]]

    results = await asyncio.gather(
        *(repo.select_investigation(snapshot.id, loan_id) for loan_id in loan_ids),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert successes[0][1] is True
    assert len(failures) == 1
    assert isinstance(failures[0], repository_module.RepositoryConflictError)
    stored = await repo.get_investigation(snapshot.id)
    assert stored == successes[0][0]


def contradiction() -> ContradictionFinding:
    claims = [
        NormalizedClaim(
            id="claim_external",
            field="septic_replacement_year",
            value=2024,
            truth_class=TruthClass.EXTERNAL_CITED,
            source_name="county-records",
            citation_ids=("citation-1",),
            observed_at=AS_OF,
        ),
        NormalizedClaim(
            id="claim_seller",
            field="septic_replacement_year",
            value=2018,
            truth_class=TruthClass.SYNTHETIC,
            source_name="seller-fixture",
            observed_at=AS_OF,
        ),
    ]
    finding = ContradictionEngine().compare(*claims)
    assert finding is not None
    return finding


def vendor_selection() -> VendorSelection:
    return VendorScout().select(
        load_delaware_inspectors(),
        approved_names={"First State Environmental"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )


async def test_investigation_artifacts_roundtrip_with_truth_and_audit_fields(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    finding = contradiction()
    selection = vendor_selection()
    before = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=7_500,
        intervention_cost_cents=0,
    )
    after = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=1_800,
        intervention_cost_cents=48_000,
    )

    await repo.add_contradiction(snapshot.id, loan_id, finding)
    await repo.add_vendor_selection(snapshot.id, loan_id, selection)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", before)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "after_rescue", after)

    assert await repo.list_contradictions(snapshot.id, loan_id) == [finding]
    assert await repo.get_latest_vendor_selection(snapshot.id, loan_id) == selection
    assert await repo.get_exposure_estimate(snapshot.id, loan_id, "before_rescue") == before
    assert await repo.get_exposure_estimate(snapshot.id, loan_id, "after_rescue") == after
    assert finding.citation_ids == ("citation-1",)
    assert selection.truth_class is TruthClass.SYNTHETIC
    assert before.created_at.tzinfo is UTC


async def test_linked_snapshot_exact_replays_are_idempotent(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    finding = contradiction()
    selection = vendor_selection()
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )

    await repo.add_contradiction(snapshot.id, loan_id, finding)
    await repo.add_contradiction(snapshot.id, loan_id, finding)
    await repo.add_vendor_selection(snapshot.id, loan_id, selection)
    await repo.add_vendor_selection(snapshot.id, loan_id, selection)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", estimate)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", estimate)

    async with aiosqlite.connect(repo.db_path) as db:
        counts = {}
        for table in ("contradictions", "vendor_selections", "exposure_estimates"):
            counts[table] = (
                await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone()
            )[0]
    assert counts == {
        "contradictions": 1,
        "vendor_selections": 1,
        "exposure_estimates": 1,
    }


async def test_concurrent_linked_snapshot_exact_replays_are_idempotent(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    finding = contradiction()
    selection = vendor_selection()
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )

    await asyncio.gather(
        *(repo.add_contradiction(snapshot.id, loan_id, finding) for _ in range(4))
    )
    await asyncio.gather(
        *(repo.add_vendor_selection(snapshot.id, loan_id, selection) for _ in range(4))
    )
    await asyncio.gather(
        *(
            repo.add_exposure_estimate(
                snapshot.id, loan_id, "before_rescue", estimate
            )
            for _ in range(4)
        )
    )

    async with aiosqlite.connect(repo.db_path) as db:
        counts = [
            (
                await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone()
            )[0]
            for table in ("contradictions", "vendor_selections", "exposure_estimates")
        ]
    assert counts == [1, 1, 1]


async def test_concurrent_linked_snapshot_differences_have_one_winner(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    finding = contradiction()
    changed_finding = finding.model_copy(update={"summary": "Concurrent difference."})
    selection = vendor_selection()
    changed_selection = selection.model_copy(
        update={"selected_at": selection.selected_at.replace(microsecond=2)}
    )
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    ).model_copy(update={"id": "concurrent-exposure"})
    changed_estimate = ExposureEngine().estimate(
        delay_consequence_cents=200,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    ).model_copy(update={"id": "concurrent-exposure"})

    result_groups = [
        await asyncio.gather(
            repo.add_contradiction(snapshot.id, loan_id, finding),
            repo.add_contradiction(snapshot.id, loan_id, changed_finding),
            return_exceptions=True,
        ),
        await asyncio.gather(
            repo.add_vendor_selection(snapshot.id, loan_id, selection),
            repo.add_vendor_selection(snapshot.id, loan_id, changed_selection),
            return_exceptions=True,
        ),
        await asyncio.gather(
            repo.add_exposure_estimate(
                snapshot.id, loan_id, "before_rescue", estimate
            ),
            repo.add_exposure_estimate(
                snapshot.id, loan_id, "before_rescue", changed_estimate
            ),
            return_exceptions=True,
        ),
    ]

    for results in result_groups:
        assert sum(result is None for result in results) == 1
        conflicts = [result for result in results if isinstance(result, BaseException)]
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], repository_module.RepositoryConflictError)


async def test_linked_snapshot_identity_conflicts_never_overwrite(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    finding = contradiction()
    changed_finding = finding.model_copy(update={"summary": "Changed immutable summary."})
    selection = vendor_selection()
    changed_selection = selection.model_copy(
        update={"selected_at": selection.selected_at.replace(microsecond=1)}
    )
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )
    changed_estimate = ExposureEngine().estimate(
        delay_consequence_cents=200,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )

    await repo.add_contradiction(snapshot.id, loan_id, finding)
    await repo.add_vendor_selection(snapshot.id, loan_id, selection)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", estimate)

    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_contradiction(snapshot.id, loan_id, changed_finding)
    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_vendor_selection(snapshot.id, loan_id, changed_selection)
    with pytest.raises(repository_module.RepositoryConflictError):
        await repo.add_exposure_estimate(
            snapshot.id, loan_id, "before_rescue", changed_estimate
        )

    assert await repo.list_contradictions(snapshot.id, loan_id) == [finding]
    assert await repo.get_latest_vendor_selection(snapshot.id, loan_id) == selection
    assert await repo.get_exposure_estimate(snapshot.id, loan_id, "before_rescue") == estimate


async def test_exposure_before_and_after_stages_coexist(repo: SQLiteRepository) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    before = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=7_500,
        intervention_cost_cents=0,
    )
    after = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=1_800,
        intervention_cost_cents=48_000,
    )

    await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", before)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "after_rescue", after)

    assert await repo.get_exposure_estimate(snapshot.id, loan_id, "before_rescue") == before
    assert await repo.get_exposure_estimate(snapshot.id, loan_id, "after_rescue") == after


async def test_exposure_stage_validation_is_identical_for_reads_and_writes(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )

    with pytest.raises(ValueError, match="unsupported exposure stage"):
        await repo.add_exposure_estimate(
            snapshot.id, loan_id, "during_rescue", estimate  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="unsupported exposure stage"):
        await repo.get_exposure_estimate(
            snapshot.id, loan_id, "during_rescue"  # type: ignore[arg-type]
        )


async def test_reloaded_snapshots_remain_frozen_utc_and_auditable(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    finding = contradiction()
    selection = vendor_selection()
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )
    await repo.add_priority_assessments(snapshot.id, [assessment])
    await repo.select_investigation(snapshot.id, loan_id)
    await repo.add_contradiction(snapshot.id, loan_id, finding)
    await repo.add_vendor_selection(snapshot.id, loan_id, selection)
    await repo.add_exposure_estimate(snapshot.id, loan_id, "after_rescue", estimate)

    reloaded_priority = (await repo.list_priority_assessments(snapshot.id))[0]
    reloaded_investigation = await repo.get_investigation(snapshot.id)
    reloaded_finding = (await repo.list_contradictions(snapshot.id, loan_id))[0]
    reloaded_selection = await repo.get_latest_vendor_selection(snapshot.id, loan_id)
    reloaded_estimate = await repo.get_exposure_estimate(
        snapshot.id, loan_id, "after_rescue"
    )
    assert reloaded_investigation is not None
    assert reloaded_selection is not None
    assert reloaded_estimate is not None

    with pytest.raises(ValidationError, match="Instance is frozen"):
        reloaded_priority.input_signals.uncertainty_score = 0
    with pytest.raises(ValidationError, match="Instance is frozen"):
        reloaded_investigation.external_loan_id = "changed"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        reloaded_finding.claim_ids = ("changed",)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        reloaded_selection.considered[0].option.price_cents = 0
    with pytest.raises(ValidationError, match="Instance is frozen"):
        reloaded_estimate.limitations = ("changed",)

    assert reloaded_investigation.created_at.tzinfo is UTC
    assert reloaded_finding.created_at.tzinfo is UTC
    assert reloaded_selection.evaluated_at.tzinfo is UTC
    assert reloaded_selection.selected_at.tzinfo is UTC
    assert reloaded_selection.truth_class is TruthClass.SYNTHETIC
    assert reloaded_selection.considered[0].option.truth_class is TruthClass.SYNTHETIC
    assert reloaded_estimate.created_at.tzinfo is UTC
    assert reloaded_finding.kind.value == "direct"
    assert reloaded_priority.formula_version == "priority-v1"
    assert reloaded_priority.source_inputs == assessment.source_inputs

    async with aiosqlite.connect(repo.db_path) as db:
        priority_created_at = await (
            await db.execute(
                "SELECT created_at FROM priority_assessments WHERE portfolio_id = ?",
                (snapshot.id,),
            )
        ).fetchone()
    assert datetime.fromisoformat(priority_created_at[0]).tzinfo is UTC


async def test_repository_rejects_foreign_portfolio_and_loan_links(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    with pytest.raises(repository_module.RepositoryNotFoundError):
        await repo.add_contradiction("missing", snapshot.loans[0].external_loan_id, contradiction())
    with pytest.raises(repository_module.RepositoryNotFoundError):
        await repo.add_contradiction(snapshot.id, "missing", contradiction())


@pytest.mark.parametrize(
    "table",
    [
        "priority_assessments",
        "portfolio_investigations",
        "contradictions",
        "vendor_selections",
        "exposure_estimates",
    ],
)
async def test_snapshot_tables_reject_direct_update_and_delete(
    repo: SQLiteRepository, table: str
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    if table == "priority_assessments":
        await repo.add_priority_assessments(
            snapshot.id, PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)
        )
    elif table == "portfolio_investigations":
        await repo.select_investigation(snapshot.id, loan_id)
    elif table == "contradictions":
        await repo.add_contradiction(snapshot.id, loan_id, contradiction())
    elif table == "vendor_selections":
        await repo.add_vendor_selection(snapshot.id, loan_id, vendor_selection())
    else:
        estimate = ExposureEngine().estimate(
            delay_consequence_cents=100,
            delay_probability_bps=5_000,
            residual_probability_bps=1_000,
            intervention_cost_cents=5,
        )
        await repo.add_exposure_estimate(snapshot.id, loan_id, "before_rescue", estimate)

    async with aiosqlite.connect(repo.db_path) as db:
        with pytest.raises(aiosqlite.IntegrityError, match="immutable"):
            await db.execute(f"UPDATE {table} SET data = '{{}}'")
        with pytest.raises(aiosqlite.IntegrityError, match="immutable"):
            await db.execute(f"DELETE FROM {table}")


async def test_priority_batch_rows_reject_direct_update_and_delete(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    assessment = PriorityEngine().rank(snapshot.loans[:1], as_of=AS_OF_DATE)[0]
    await repo.add_priority_assessments(snapshot.id, [assessment])

    async with aiosqlite.connect(repo.db_path) as db:
        with pytest.raises(aiosqlite.IntegrityError, match="immutable"):
            await db.execute(
                "UPDATE priority_assessment_batches SET batch_id = 'changed'"
            )
        with pytest.raises(aiosqlite.IntegrityError, match="immutable"):
            await db.execute("DELETE FROM priority_assessment_batches")


async def test_malformed_stored_json_is_rejected_instead_of_coerced(
    repo: SQLiteRepository,
) -> None:
    snapshot = portfolio()
    await repo.create_portfolio(snapshot)
    loan_id = snapshot.loans[0].external_loan_id
    async with aiosqlite.connect(repo.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT INTO contradictions "
            "(id, portfolio_id, external_loan_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
            ("forged", snapshot.id, loan_id, "{}", AS_OF.isoformat()),
        )
        await db.commit()

    with pytest.raises(ValidationError):
        await repo.list_contradictions(snapshot.id, loan_id)


async def test_database_foreign_keys_are_enforced(repo: SQLiteRepository) -> None:
    async with aiosqlite.connect(repo.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(aiosqlite.IntegrityError, match="FOREIGN KEY"):
            await db.execute(
                "INSERT INTO contradictions "
                "(id, portfolio_id, external_loan_id, data, created_at) "
                "VALUES ('bad', 'missing', 'missing', '{}', ?)",
                (AS_OF.isoformat(),),
            )
