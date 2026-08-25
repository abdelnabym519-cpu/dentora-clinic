from __future__ import annotations

from uuid import uuid4

from app.modules.media.service import DocumentService


def test_object_key_is_tenant_scoped_unique_and_filename_independent() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()

    first = DocumentService.generate_storage_path(clinic_id, patient_id, "patient-name-report.pdf")
    second = DocumentService.generate_storage_path(clinic_id, patient_id, "another-name.pdf")

    assert first.startswith(f"{clinic_id}/{patient_id}/")
    assert second.startswith(f"{clinic_id}/{patient_id}/")
    assert first.endswith(".pdf")
    assert second.endswith(".pdf")
    assert first != second
    assert "patient-name-report" not in first
    assert "another-name" not in second


def test_object_key_does_not_allow_filename_path_components() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()

    path = DocumentService.generate_storage_path(
        clinic_id,
        patient_id,
        "sensitive.pdf/../../other-clinic/object",
    )

    assert path.startswith(f"{clinic_id}/{patient_id}/")
    assert ".." not in path
    assert "other-clinic" not in path
    assert "sensitive" not in path
