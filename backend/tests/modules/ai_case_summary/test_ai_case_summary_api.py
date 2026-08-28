import json

import pytest
from sqlalchemy import select

from app.core.auth.models import ClinicMembership
from app.core.llm.base import Done, TextDelta
from app.modules.ai_case_summary.models import AICaseSummaryRecord
from app.modules.ai_case_summary.service import AICaseSummaryService


class CapturingProvider:
    def __init__(self):
        self.user_payload = None

    async def complete(self, **kwargs):
        self.user_payload = json.loads(kwargs["messages"][0].content[0].text)
        evidence_ids = list(self.user_payload["evidence"])
        gaps = [
            {"section": name, "status": section["status"]}
            for name, section in self.user_payload["sections"].items()
            if section["status"] in {"not_available", "invalid_or_stale"}
        ]
        claims = []
        if evidence_ids:
            claims.append(
                {
                    "claim_id": "C1",
                    "text": "Structured case data is available.",
                    "evidence_ids": [evidence_ids[0]],
                }
            )
        yield TextDelta(json.dumps({"claims": claims, "data_gaps": gaps}))
        yield Done("stop")


@pytest.mark.asyncio
async def test_generate_is_redacted_traceable_and_requires_dentist_review(
    client,
    db_session,
    auth_headers,
    test_clinic,
    test_patient,
    monkeypatch,
):
    provider = CapturingProvider()
    monkeypatch.setattr(
        AICaseSummaryService,
        "provider_factory",
        staticmethod(lambda _name: provider),
    )
    response = await client.post(
        f"/api/v1/ai_case_summary/patients/{test_patient.id}", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    summary = response.json()["data"]
    assert summary["review_status"] == "pending_review"
    assert summary["clinical_output"] is False
    assert summary["unified_case"]["case_snapshot_version"] == 1
    assert summary["provenance"]["provider"] == "openai"
    assert summary["provenance"]["input_digest"].startswith("sha256:")
    assert summary["provenance"]["output_digest"].startswith("sha256:")
    outgoing = json.dumps(provider.user_payload)
    assert str(test_patient.id) not in outgoing
    assert test_patient.email not in outgoing
    assert test_patient.first_name not in outgoing
    assert test_patient.last_name not in outgoing
    row = await db_session.scalar(select(AICaseSummaryRecord))
    assert row is not None
    review = await client.post(
        f"/api/v1/ai_case_summary/summaries/{row.id}/review",
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
        f"/api/v1/ai_case_summary/summaries/{row.id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert review.status_code == 200, review.text
    reviewed = review.json()["data"]
    assert reviewed["review_status"] == "accepted"
    assert reviewed["clinical_output"] is True
    assert reviewed["reviewed_by"] is not None
