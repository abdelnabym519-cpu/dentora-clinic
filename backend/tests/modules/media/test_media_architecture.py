"""Architecture guards for the Media clean-architecture boundary."""

from pathlib import Path

import app.modules.media as media_pkg

MODULE_ROOT = Path(media_pkg.__file__).resolve().parent

FORBIDDEN_INNER_IMPORTS = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "app.database",
    "app.core.events",
    "app.modules.media.models",
    "app.modules.media.infrastructure",
    "app.modules.media.legacy",
    "app.modules.media.service",
    "app.modules.media.storage",
)


def _source(name: str) -> str:
    return (MODULE_ROOT / name).read_text(encoding="utf-8")


def test_media_inner_layers_do_not_import_outer_implementations() -> None:
    for name in ("ports.py", "application.py"):
        source = _source(name)
        for forbidden in FORBIDDEN_INNER_IMPORTS:
            assert forbidden not in source, f"{name} imports outer dependency {forbidden}"


def test_media_presentation_does_not_bypass_composition_boundary() -> None:
    router_source = _source("router.py")
    assert "from .legacy import" not in router_source
    assert "app.modules.media.legacy" not in router_source


def test_media_legacy_implementation_is_outside_inner_layers() -> None:
    assert (MODULE_ROOT / "legacy.py").exists()


def test_media_service_is_a_compatibility_boundary() -> None:
    source = _source("service.py")
    assert "MediaApplication" in source
    assert "SqlAlchemyMediaGateway" in source
