"""Production Alembic graph discovery must not drift from module migrations."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.plugins.alembic_paths import discover_version_locations

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
MAIN_LINEAR = BACKEND_ROOT / "alembic" / "versions"
MODULES_ROOT = BACKEND_ROOT / "app" / "modules"


def _configured_locations() -> set[Path]:
    config = Config(str(ALEMBIC_INI))
    raw = config.get_main_option("version_locations")
    return {(BACKEND_ROOT / location).resolve() for location in raw.split(":") if location}


def test_static_cli_locations_match_runtime_discovery() -> None:
    """CLI pre-load and env.py runtime discovery cover exactly the same branches."""
    discovered = {
        Path(location).resolve()
        for location in discover_version_locations(MAIN_LINEAR, MODULES_ROOT)
    }
    assert _configured_locations() == discovered


def test_ai_case_summary_chain_is_visible_to_cli_graph() -> None:
    """Case Intelligence and AI Case Summary revisions must be visible before env.py."""
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert script.get_revision("ci_0001") is not None
    assert script.get_revision("acs_0001") is not None
