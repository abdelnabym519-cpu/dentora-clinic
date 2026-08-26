"""Domain contract tests for Phase 3 automatic tooth segmentation.

Covers the ``ToothSegmentationProvider`` port contracts
(``segmentation.py``), the deterministic arch-partition adapter
(``infrastructure.py``), FDI mapping, confidence/evidence validation,
invalid-result rejection, the fixed safety flags — and the inner-layer
purity of the segmentation contracts (no framework imports, ADR 0019).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.infrastructure import (
    ArchPartitionSegmentationProvider,
    default_segmentation_provider,
)
from app.modules.dental_3d.schemas import DentalMesh, Tooth3D
from app.modules.dental_3d.segmentation import (
    SegmentationAnalysisResult,
    SegmentationEvidence,
    SegmentationRequest,
    SegmentationReviewUpdate,
    SegmentedTooth,
    ToothSegmentationProvider,
)

PERFORMED_AT = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)


def _request(
    teeth: list[Tooth3D] | None = None,
    meshes: list[DentalMesh] | None = None,
) -> SegmentationRequest:
    return SegmentationRequest(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        teeth=teeth if teeth is not None else [Tooth3D(tooth_number=11)],
        meshes=meshes or [],
        performed_at=PERFORMED_AT,
    )


class TestSegmentedToothContracts:
    def test_valid_proposal(self) -> None:
        tooth = SegmentedTooth(
            tooth_number=16,
            status="segmented",
            confidence=0.9,
            evidence=SegmentationEvidence(basis="arch_position", arch_region="Q1-molar"),
        )
        assert tooth.tooth_number == 16
        assert tooth.status == "segmented"

    @pytest.mark.parametrize("number", [0, 9, 10, 49, 50, 90, 99, 100])
    def test_invalid_fdi_rejected(self, number: int) -> None:
        with pytest.raises(ValidationError):
            SegmentedTooth(tooth_number=number, status="segmented", confidence=0.9)

    @pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0])
    def test_confidence_bounds_enforced(self, confidence: float) -> None:
        with pytest.raises(ValidationError):
            SegmentedTooth(tooth_number=11, status="segmented", confidence=confidence)

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SegmentedTooth(tooth_number=11, status="diagnosed", confidence=0.9)  # type: ignore[arg-type]

    def test_evidence_basis_is_closed_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            SegmentationEvidence(basis="gut_feeling", arch_region="Q1")  # type: ignore[arg-type]


class TestSafetyFlagsAreFixed:
    def test_result_cannot_be_clinical(self) -> None:
        result = SegmentationAnalysisResult(
            provider="p", method="m", teeth=[], performed_at=PERFORMED_AT
        )
        assert result.is_clinical is False
        assert result.requires_review is True
        # A provider trying to claim clinical status cannot even state it:
        with pytest.raises(ValidationError):
            SegmentationAnalysisResult.model_validate(
                {
                    "provider": "p",
                    "method": "m",
                    "teeth": [],
                    "performed_at": PERFORMED_AT,
                    "is_clinical": True,
                }
            )

    def test_response_disclaimer_is_always_present(self) -> None:
        from app.modules.dental_3d.segmentation import SegmentationAnalysisResponse

        response = SegmentationAnalysisResponse(
            id=uuid4(),
            patient_id=uuid4(),
            provider="p",
            method="m",
            teeth=[],
            performed_at=PERFORMED_AT,
        )
        assert "non-clinical" in response.disclaimer.lower()
        assert response.is_clinical is False
        assert response.requires_review is True

    def test_review_only_accepts_decision(self) -> None:
        assert SegmentationReviewUpdate(decision="accepted").decision == "accepted"
        with pytest.raises(ValidationError):
            SegmentationReviewUpdate(decision="final_diagnosis")  # type: ignore[arg-type]


class TestArchPartitionProvider:
    async def test_conforms_to_port(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        assert isinstance(provider, ToothSegmentationProvider)
        assert provider.name == "arch-partition"
        assert provider.input_kind == "scene"

    async def test_deterministic_for_identical_requests(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        request = _request(teeth=[Tooth3D(tooth_number=n) for n in (11, 16, 46)])
        first = await provider.segment(request)
        second = await provider.segment(request)
        assert first.model_dump() == second.model_dump()

    async def test_fdi_mapping_covers_full_permanent_dentition(self) -> None:
        from app.modules.odontogram.constants import PERMANENT_TEETH

        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(
            _request(teeth=[Tooth3D(tooth_number=n) for n in PERMANENT_TEETH])
        )
        assert [t.tooth_number for t in result.teeth] == sorted(PERMANENT_TEETH)
        # Quadrant derivation matches FDI: 1x/2x upper, 3x/4x lower.
        regions = {t.tooth_number: t.evidence.arch_region for t in result.teeth}
        assert regions[11].startswith("Q1-")
        assert regions[21].startswith("Q2-")
        assert regions[31].startswith("Q3-")
        assert regions[48].startswith("Q4-")
        # Units digit drives the size category.
        assert regions[11] == "Q1-incisor"
        assert regions[13] == "Q1-canine"
        assert regions[14] == "Q1-premolar"
        assert regions[18] == "Q1-molar"

    async def test_missing_tooth_flagged_from_odontogram_record(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(
            _request(teeth=[Tooth3D(tooth_number=46, present=False, condition="missing")])
        )
        tooth = result.teeth[0]
        assert tooth.status == "missing"
        assert tooth.evidence.basis == "odontogram_record"

    async def test_restored_tooth_is_uncertain(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        for condition in ("crown", "implant", "caries", "fracture"):
            result = await provider.segment(
                _request(teeth=[Tooth3D(tooth_number=16, condition=condition)])
            )
            assert result.teeth[0].status == "uncertain", condition
            assert result.teeth[0].confidence == 0.5

    async def test_mesh_backing_raises_confidence_and_records_documents(self) -> None:
        document_id = uuid4()
        mesh = DentalMesh(
            source="intraoral_scan",
            format="stl",
            document_id=document_id,
            url="/api/v1/media/documents/x/download",
        )
        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(_request(teeth=[Tooth3D(tooth_number=11)], meshes=[mesh]))
        tooth = result.teeth[0]
        assert tooth.status == "segmented"
        assert tooth.confidence == 0.9
        assert tooth.evidence.basis == "mesh_backed"
        assert tooth.evidence.backing_documents == [document_id]

    async def test_synthetic_only_confidence_and_deciduous_scale(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(
            _request(teeth=[Tooth3D(tooth_number=11), Tooth3D(tooth_number=55)])
        )
        by_number = {t.tooth_number: t for t in result.teeth}
        assert by_number[11].confidence == 0.75
        assert by_number[11].evidence.basis == "arch_position"
        assert by_number[55].confidence == 0.7  # deciduous mixed-dentition rule

    async def test_empty_scene_yields_empty_analysis(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(_request(teeth=[]))
        assert result.teeth == []
        assert result.provider == "arch-partition"
        assert result.method == "deterministic-arch-partition-v0"

    async def test_performed_at_is_passthrough_not_environment(self) -> None:
        provider = ArchPartitionSegmentationProvider()
        result = await provider.segment(_request())
        assert result.performed_at == PERFORMED_AT


class TestInvalidProviderResults:
    """A misbehaving adapter must be caught by the contracts, not trusted."""

    async def test_invalid_fdi_in_result_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SegmentationAnalysisResult(
                provider="bad",
                method="bad",
                teeth=[SegmentedTooth(tooth_number=99, status="segmented", confidence=0.9)],
                performed_at=PERFORMED_AT,
            )

    async def test_confidence_out_of_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SegmentedTooth(tooth_number=11, status="segmented", confidence=1.5)

    async def test_empty_provider_identity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SegmentationAnalysisResult(provider="", method="m", teeth=[], performed_at=PERFORMED_AT)


class TestCompositionRoot:
    def test_default_provider_is_arch_partition(self) -> None:
        provider = default_segmentation_provider()
        assert isinstance(provider, ArchPartitionSegmentationProvider)

    def test_replacing_the_provider_requires_no_contract_change(self) -> None:
        # A drop-in ML-shaped provider satisfies the same runtime protocol.
        class FutureMlProvider:
            name = "mesh-ml-v1"
            input_kind = "scene"  # type: ignore[assignment]

            async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
                return SegmentationAnalysisResult(
                    provider=self.name,
                    method="future-ml",
                    teeth=[],
                    performed_at=request.performed_at,
                )

        assert isinstance(FutureMlProvider(), ToothSegmentationProvider)


class TestInnerLayerPurity:
    """ADR 0019: the port file stays framework-free."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "app.modules.dental_3d.segmentation",
            "app.modules.dental_3d.sources",
        ],
    )
    def test_inner_contracts_import_no_frameworks(self, module_path: str) -> None:
        import importlib

        forbidden = ("fastapi", "sqlalchemy", "uvicorn", "torch", "tensorflow", "openai")
        module = importlib.import_module(module_path)
        source = inspect.getsource(module)
        for framework in forbidden:
            assert f"import {framework}" not in source, f"{module_path} imports {framework}"
            assert f"from {framework}" not in source, f"{module_path} imports {framework}"
