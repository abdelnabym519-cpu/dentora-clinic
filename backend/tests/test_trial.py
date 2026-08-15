from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.trial import ensure_trial_active, get_trial_status


def test_trial_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRIAL_MODE", False)
    monkeypatch.setattr(settings, "TRIAL_STARTED_AT", "")

    trial = get_trial_status(now=datetime(2026, 8, 15, tzinfo=UTC))

    assert trial.enabled is False
    assert trial.expired is False
    assert trial.expires_at is None


def test_three_day_trial_reports_remaining_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRIAL_MODE", True)
    monkeypatch.setattr(settings, "TRIAL_STARTED_AT", "2026-08-15T12:00:00Z")
    monkeypatch.setattr(settings, "TRIAL_DAYS", 3)

    trial = get_trial_status(now=datetime(2026, 8, 16, 12, 0, tzinfo=UTC))

    assert trial.enabled is True
    assert trial.expired is False
    assert trial.expires_at == datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    assert trial.remaining_seconds == 2 * 24 * 60 * 60


def test_expired_trial_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRIAL_MODE", True)
    monkeypatch.setattr(settings, "TRIAL_STARTED_AT", "2020-01-01T00:00:00Z")
    monkeypatch.setattr(settings, "TRIAL_DAYS", 3)

    with pytest.raises(HTTPException) as exc_info:
        ensure_trial_active()

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "trial_expired"
