"""Architecture guards for the migrated Agenda inner layers."""

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
INNER_FILES = (
    BACKEND_ROOT / "app/modules/agenda/domain.py",
    BACKEND_ROOT / "app/modules/agenda/ports.py",
    BACKEND_ROOT / "app/modules/agenda/application.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "asyncpg",
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "app.database",
    "app.core.events",
    "app.modules.agenda.models",
    "app.modules.agenda.infrastructure",
    "app.modules.agenda.legacy",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                imports.add(f"app.modules.agenda.{node.module}")
            else:
                imports.add(node.module)

    return imports


@pytest.mark.parametrize("path", INNER_FILES, ids=lambda path: path.name)
def test_agenda_inner_layers_do_not_import_outer_implementations(path: Path) -> None:
    violations = {
        imported for imported in _imports(path) if imported.startswith(FORBIDDEN_IMPORT_PREFIXES)
    }
    assert violations == set()


def test_agenda_presentation_does_not_bypass_composition_boundary() -> None:
    router = BACKEND_ROOT / "app/modules/agenda/router.py"
    imports = _imports(router)
    assert "app.modules.agenda.infrastructure" not in imports
    assert "app.modules.agenda.legacy" not in imports
