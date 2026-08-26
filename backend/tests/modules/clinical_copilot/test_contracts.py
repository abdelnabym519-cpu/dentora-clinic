from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.clinical_copilot.contracts import ClinicalCopilotAsk


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
