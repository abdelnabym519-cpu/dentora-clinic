from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[3]

MIGRATION_PATH = (
    BACKEND_ROOT
    / "app"
    / "modules"
    / "booking"
    / "migrations"
    / "versions"
    / "bk_0002_cloud_request_receipts.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "booking_bk_0002_cloud_request_receipts",
        MIGRATION_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load booking bk_0002 migration")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


class RecordingOp:
    def __init__(self) -> None:
        self.created_tables: list[tuple[str, tuple, dict]] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *args, **kwargs):
        # Bind columns and constraints to a temporary SQLAlchemy Table.
        # Alembic normally performs this binding internally; our recorder
        # must reproduce it so FK parents and UniqueConstraint columns
        # can be inspected accurately.
        table = sa.Table(
            name,
            sa.MetaData(),
            *args,
        )

        elements = (
            tuple(table.columns)
            + tuple(table.constraints)
        )

        self.created_tables.append(
            (name, elements, kwargs)
        )

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def test_bk_0002_migration_exists_and_chains_from_booking_root() -> None:
    assert MIGRATION_PATH.is_file()

    migration = _load_migration()

    assert migration.revision == "bk_0002"
    assert migration.down_revision == "bk_0001"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_bk_0002_creates_booking_cloud_requests_contract() -> None:
    migration = _load_migration()
    recorder = RecordingOp()

    migration.op = recorder

    migration.upgrade()

    assert len(recorder.created_tables) == 1

    table_name, elements, _ = recorder.created_tables[0]

    assert table_name == "booking_cloud_requests"

    columns = {
        element.name: element
        for element in elements
        if isinstance(element, sa.Column)
    }

    assert set(columns) == {
        "id",
        "clinic_id",
        "request_id",
        "status",
        "appointment_id",
        "rejection_code",
        "created_at",
        "updated_at",
    }

    assert columns["id"].nullable is False
    assert columns["clinic_id"].nullable is False
    assert columns["request_id"].nullable is False
    assert columns["status"].nullable is False

    assert columns["appointment_id"].nullable is True
    assert columns["rejection_code"].nullable is True

    assert isinstance(columns["request_id"].type, sa.String)
    assert columns["request_id"].type.length == 128

    assert isinstance(columns["status"].type, sa.String)
    assert columns["status"].type.length == 20

    assert isinstance(columns["rejection_code"].type, sa.String)
    assert columns["rejection_code"].type.length == 100


def test_bk_0002_has_idempotency_and_result_constraints() -> None:
    migration = _load_migration()
    recorder = RecordingOp()

    migration.op = recorder
    migration.upgrade()

    _, elements, _ = recorder.created_tables[0]

    constraint_names = {
        element.name
        for element in elements
        if isinstance(
            element,
            (
                sa.UniqueConstraint,
                sa.CheckConstraint,
            ),
        )
    }

    assert "uq_booking_cloud_requests_clinic_request" in constraint_names
    assert "ck_booking_cloud_requests_status" in constraint_names
    assert "ck_booking_cloud_requests_result_shape" in constraint_names

    unique_constraints = [
        element
        for element in elements
        if isinstance(element, sa.UniqueConstraint)
    ]

    assert len(unique_constraints) == 1

    unique_columns = tuple(
        column.name
        for column in unique_constraints[0].columns
    )

    assert unique_columns == (
        "clinic_id",
        "request_id",
    )


def test_bk_0002_references_clinic_and_appointment() -> None:
    migration = _load_migration()
    recorder = RecordingOp()

    migration.op = recorder
    migration.upgrade()

    _, elements, _ = recorder.created_tables[0]

    foreign_keys = [
        element
        for element in elements
        if isinstance(element, sa.ForeignKeyConstraint)
    ]

    targets = {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in foreign_keys
    }

    assert (
        ("clinic_id",),
        ("clinics.id",),
        "CASCADE",
    ) in targets

    assert (
        ("appointment_id",),
        ("appointments.id",),
        None,
    ) in targets


def test_bk_0002_downgrade_drops_receipt_table() -> None:
    migration = _load_migration()
    recorder = RecordingOp()

    migration.op = recorder
    migration.downgrade()

    assert recorder.dropped_tables == [
        "booking_cloud_requests",
    ]
