from __future__ import annotations

from app.modules.booking import BookingModule
from app.modules.booking.models import BookingCloudRequest, BookingSettings


def test_booking_module_registers_all_database_models() -> None:
    models = BookingModule().get_models()

    assert BookingSettings in models
    assert BookingCloudRequest in models
