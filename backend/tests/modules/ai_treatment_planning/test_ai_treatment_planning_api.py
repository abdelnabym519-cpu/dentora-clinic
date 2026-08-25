import json

import pytest
from sqlalchemy import func, select

from app.core.auth.models import ClinicMembership
from app.core.llm.base import Done, TextDelta
from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
from app.modules.ai_treatment_planning.service import AITreatmentPlanningService
from app.modules.treatment_plan.models import TreatmentPlan


class CapturingPlanningProvider:
    def __init__(self):
        self.user_payload = None

    async def complete(self, **kwargs):
        self.user_payload = json.loads(kwargs["messages"][0].content[0].text)
        case = self.user_payload["case"]
        evidence_ids = list(case["evidence"])
        risk_factor_ids = [
            factor["factor_id"] for factor in self.user_payload["risk_context"]["factors"]
        ]
        gaps = [
            {"section": name, "status": section["status"]}
            for name, section in case["sections"].items()
            if section["status"] in {"not_available", "invalid_or_stale"}
        ]
        options = []
        if evidence_ids and risk_factor_ids:
            options.append(
                {
                    "option_id": "O1",
                    "title": "Evidence-grounded staged option",
                    "clinical_intent": "Support dentist review of the documented case state.",
                    "rationale": "The option is tied to structured case evidence and risk context.",
                    "evidence_ids": [evidence_ids[0]],
                    "risk_factor_ids": [risk_factor_ids[0]],
                    "steps": [
                        {
                            "step_id": "S1",
                            "description": "Review the structured finding before selecting treatment.",
                            "purpose": "Keep the final clinical choice with the dentist.",
                            "evidence_ids": [evidence_ids[0]],
                            "risk_factor_ids": [risk_factor_ids[0]],
                        }
                    ],
                    "uncertainties": [],
                    "alternatives_or_tradeoffs": [
                        "Defer final treatment selection when additional evidence is needed."
                    ],
                }
            )
        yield TextDelta(json.dumps({"options": options, "data_gaps": gaps}))
        yield Done("stop")


@pytest.mark.asyncio
async def test_generate_is_redacted_append_only_and_never_creates_canonical_plan(
    client,
    db_session,
    auth_headers,
    test_clinic,
    test_patient,
    monkeypatch,
):
    provider = CapturingPlanningProvider()
    monkeypatch.setattr(
        AITreatmentPlanningService,
        "provider_factory",
        staticmethod(lambda _name: provider),
    )
    before_count = await db_session.scalar(select(func.count()).select_from(TreatmentPlan))

    response = await client.post(
        f"/api/v1/ai_treatment_planning/patients/{test_patient.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    planning = response.json()["data"]
    assert planning["review_status"] == "pending_review"
    assert planning["clinical_output"] is False
    assert planning["canonical_treatment_plan_created"] is False
    assert planning["content"]["advisory_only"] is True
    assert planning["content"]["no_automatic_execution"] is True
    assert planning["case_reference"]["case_snapshot_version"] == 1
    assert planning["case_reference"]["risk_result_digest"].startswith("sha256:")
    assert planning["provenance"]["input_digest"].startswith("sha256:")
    assert planning["provenance"]["output_digest"].startswith("sha256:")

    outgoing = json.dumps(provider.user_payload)
    assert str(test_patient.id) not in outgoing
    assert test_patient.email not in outgoing
    patient_data = provider.user_payload["case"]["sections"]["patient"]["data"]
    for forbidden_key in (
        "id",
        "patient_id",
        "clinic_id",
        "first_name",
        "last_name",
        "full_name",
        "email",
        "phone",
        "mobile",
        "date_of_birth",
    ):
        assert forbidden_key not in patient_data

    after_count = await db_session.scalar(select(func.count()).select_from(TreatmentPlan))
    assert after_count == before_count

    row = await db_session.scalar(select(AITreatmentPlanningRecord))
    assert row is not None
    history = await client.get(
        f"/api/v1/ai_treatment_planning/patients/{test_patient.id}/history",
        headers=auth_headers,
    )
    assert history.status_code == 200, history.text
    assert len(history.json()["data"]) == 1

    review = await client.post(
        f"/api/v1/ai_treatment_planning/results/{row.id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert review.status_code == 403

    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
    )
    membership.role = "dentist"
    await db_session.commit()
    review = await client.post(
        f"/api/v1/ai_treatment_planning/results/{row.id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert review.status_code == 200, review.text
    reviewed = review.json()["data"]
    assert reviewed["review_status"] == "accepted"
    assert reviewed["clinical_output"] is True
    assert reviewed["canonical_treatment_plan_created"] is False

    final_count = await db_session.scalar(select(func.count()).select_from(TreatmentPlan))
    assert final_count == before_count
