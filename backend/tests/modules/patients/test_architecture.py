"""Architecture guards for the migrated patient application boundary."""

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_FILES = (
    BACKEND_ROOT / "app/modules/patients/domain.py",
    BACKEND_ROOT / "app/modules/patients/ports.py",
    BACKEND_ROOT / "app/modules/patients/service.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "asyncpg",
    "fastapi",
    "sqlalchemy",
    "app.database",
    "app.core.events",
    "app.modules.patients.models",
    "app.modules.patients.repository",
    "app.modules.patients.event_publisher",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                imports.add(f"app.modules.patients.{node.module}")
            else:
                imports.add(node.module)

    return imports


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=lambda path: path.name)
def test_patient_inner_layers_do_not_import_outer_implementations(path: Path) -> None:
    """Keep DB/framework/provider details out of migrated inner layers."""
    violations = {
        imported
        for imported in _imports(path)
        if imported.startswith(FORBIDDEN_IMPORT_PREFIXES)
    }

    assert violations == set()
