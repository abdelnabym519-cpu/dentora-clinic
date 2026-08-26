"""Architecture guards for the Billing clean-architecture boundary."""

from pathlib import Path

import app.modules.billing as billing_pkg

MODULE_ROOT = Path(billing_pkg.__file__).resolve().parent

FORBIDDEN_INNER_IMPORTS = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "app.database",
    "app.core.events",
    "app.modules.billing.models",
    "app.modules.billing.infrastructure",
    "app.modules.billing.legacy",
    "app.modules.billing.legacy_workflow",
)


def _source(name: str) -> str:
    return (MODULE_ROOT / name).read_text(encoding="utf-8")


def test_billing_inner_layers_do_not_import_outer_implementations() -> None:
    for name in ("domain.py", "ports.py", "application.py"):
        source = _source(name)
        for forbidden in FORBIDDEN_INNER_IMPORTS:
            assert forbidden not in source, f"{name} imports outer dependency {forbidden}"


def test_billing_presentation_does_not_bypass_composition_boundary() -> None:
    router_source = _source("router.py")
    assert "from .legacy import" not in router_source
    assert "from .legacy_workflow import" not in router_source
    assert "app.modules.billing.legacy" not in router_source


def test_billing_legacy_implementation_is_outside_inner_layers() -> None:
    assert (MODULE_ROOT / "legacy.py").exists()
    assert (MODULE_ROOT / "legacy_workflow.py").exists()
