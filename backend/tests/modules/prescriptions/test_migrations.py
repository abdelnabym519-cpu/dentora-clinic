"""Regression coverage for the Electronic Prescription Alembic branch."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_prescriptions_migration_is_visible_to_alembic_cli() -> None:
    """The CLI graph must include the module branch before env.py is loaded."""
    backend_root = Path(__file__).resolve().parents[3]
    script = ScriptDirectory.from_config(Config(str(backend_root / "alembic.ini")))

    revision = script.get_revision("rx_0001")
    assert revision is not None
    assert (
        Path(revision.path).resolve().parent
        == (backend_root / "app/modules/prescriptions/migrations/versions").resolve()
    )
    assert "rx_0001" in script.get_heads()
