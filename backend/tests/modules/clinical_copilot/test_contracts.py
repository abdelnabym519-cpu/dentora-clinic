from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.clinical_copilot.contracts import ClinicalCopilotAsk
from app.modules.clinical_copilot.router import _enforce_dentist_control


def test_clinical_copilot_accepts_only_finite_focus() -> None:
    request = ClinicalCopilotAsk(patient_id=uuid4(), focus="risk_context")
    assert request.focus == "risk_context"


def test_clinical_copilot_rejects_unrestricted_question_text() -> None:
    with pytest.raises(ValidationError):
        ClinicalCopilotAsk.model_validate(
            {
                "patient_id": str(uuid4()),
                "focus": "case_review",
                "question": "unrestricted clinical free text",
            }
        )


def test_dentist_control_rejects_non_dentist_even_with_broader_rbac() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _enforce_dentist_control("admin")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"code": "dentist_control_required"}
    _enforce_dentist_control("dentist")
