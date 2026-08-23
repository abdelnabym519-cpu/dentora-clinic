"""Architecture guards for the patients_clinical inner boundary."""

from pathlib import Path

import app.modules.patients_clinical as patients_clinical_pkg

MODULE_ROOT = Path(patients_clinical_pkg.__file__).resolve().parent

FORBIDDEN_INNER_IMPORTS = (
    "fastapi",
    "sqlalchemy",
    "app.database",
    "app.modules.patients_clinical.models",
    "app.modules.patients_clinical.infrastructure",
    "app.modules.patients_clinical.legacy",
    "app.modules.patients_clinical.service",
)


def _source(name: str) -> str:
    return (MODULE_ROOT / name).read_text(encoding="utf-8")


def test_patients_clinical_inner_layers_do_not_import_outer_implementations() -> None:
    for name in ("ports.py", "application.py"):
        source = _source(name)
        for forbidden in FORBIDDEN_INNER_IMPORTS:
            assert forbidden not in source, f"{name} imports outer dependency {forbidden}"


def test_patients_clinical_legacy_implementation_is_outside_inner_layers() -> None:
    assert (MODULE_ROOT / "legacy.py").exists()


def test_patients_clinical_service_is_a_compatibility_boundary() -> None:
    source = _source("service.py")
    assert "PatientsClinicalApplication" in source
    assert "SqlAlchemyPatientsClinicalGateway" in source
