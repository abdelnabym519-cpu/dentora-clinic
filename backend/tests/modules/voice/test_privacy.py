"""Privacy tests for Dentora Voice audit sanitization."""

from app.modules.voice.privacy import sanitize_audit_payload


def test_sanitizer_redacts_patient_search_and_contact_fields() -> None:
    payload = {
        "query": "أحمد محمد",
        "patients": [
            {
                "patient_id": "0bb65ca4-eef3-44bd-b6ef-e9e37479ba3c",
                "full_name": "أحمد محمد",
                "phone": "+201234567890",
                "email": "patient@example.com",
                "status": "active",
            }
        ],
    }
    sanitized = sanitize_audit_payload(payload)
    assert sanitized["query"] == "[REDACTED]"
    patient = sanitized["patients"][0]
    assert patient["patient_id"] == "[REDACTED]"
    assert patient["full_name"] == "[REDACTED]"
    assert patient["phone"] == "[REDACTED]"
    assert patient["email"] == "[REDACTED]"
    assert patient["status"] == "active"


def test_sanitizer_does_not_mutate_non_phi_control_fields() -> None:
    payload = {"action": "show_nerve", "payload": {"route": "/patients/example"}}
    assert sanitize_audit_payload(payload) == payload
