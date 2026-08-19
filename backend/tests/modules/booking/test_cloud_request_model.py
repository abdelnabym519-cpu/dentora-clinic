from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.modules.booking import models as booking_models


def _model():
    return booking_models.BookingCloudRequest


def test_booking_cloud_request_uses_dedicated_table() -> None:
    model = _model()

    assert model.__tablename__ == "booking_cloud_requests"


def test_booking_cloud_request_has_durable_idempotency_columns() -> None:
    model = _model()

    columns = model.__table__.columns

    expected = {
        "id",
        "clinic_id",
        "request_id",
        "status",
        "appointment_id",
        "rejection_code",
        "created_at",
        "updated_at",
    }

    assert expected.issubset(set(columns.keys()))

    assert columns["clinic_id"].nullable is False
    assert columns["request_id"].nullable is False
    assert columns["status"].nullable is False

    assert columns["appointment_id"].nullable is True
    assert columns["rejection_code"].nullable is True


def test_booking_cloud_request_is_unique_per_clinic_and_cloud_request() -> None:
    model = _model()

    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("clinic_id", "request_id") in unique_sets


def test_booking_cloud_request_has_status_and_result_shape_guards() -> None:
    model = _model()

    check_names = {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_booking_cloud_requests_status" in check_names
    assert "ck_booking_cloud_requests_result_shape" in check_names


def test_booking_cloud_request_references_clinic_and_appointment() -> None:
    model = _model()

    clinic_targets = {
        foreign_key.target_fullname
        for foreign_key in model.__table__.columns["clinic_id"].foreign_keys
    }

    appointment_targets = {
        foreign_key.target_fullname
        for foreign_key in model.__table__.columns["appointment_id"].foreign_keys
    }

    assert clinic_targets == {"clinics.id"}
    assert appointment_targets == {"appointments.id"}
