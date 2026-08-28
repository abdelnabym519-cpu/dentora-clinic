from app.contracts import Finding, InferenceResponse, Point


def test_backend_contract_shape_accepts_detected_and_no_detection() -> None:
    detected = InferenceResponse(
        status="detected",
        model_id="DentalSegmentator/Dataset112",
        model_version="v100-checkpoint-abcdef123456",
        findings=[
            Finding(
                side="left",
                confidence=0.9,
                points_mm=[Point(x=1, y=2, z=3), Point(x=2, y=3, z=4)],
            )
        ],
    )
    assert detected.model_dump(mode="json")["findings"][0]["side"] == "left"
    empty = InferenceResponse(
        status="no_detection",
        model_id="DentalSegmentator/Dataset112",
        model_version="v100-checkpoint-abcdef123456",
    )
    assert empty.findings == []
