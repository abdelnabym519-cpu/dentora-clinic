"""Architecture guards for the patients_clinical inner boundary."""

import ast
from pathlib import Path


MODULE_DIR = Path(__file__).parents[3] / "app" / "modules" / "patients_clinical"
FORBIDDEN_ROOTS = {"fastapi", "sqlalchemy"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_patients_clinical_inner_layers_are_framework_free() -> None:
    for filename in ("application.py", "ports.py"):
        imports = _imports(MODULE_DIR / filename)
        assert not imports.intersection(FORBIDDEN_ROOTS), (filename, imports)
