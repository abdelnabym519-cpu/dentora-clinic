"""Application use case for CBCT/DICOM ingestion.

The service depends only on the framework-free inner-boundary port. FastAPI,
SQLAlchemy, media storage and pydicom belong to presentation/infrastructure.
"""

from __future__ import annotations

from uuid import UUID

from .cbct import DicomIngestionPort, DicomIngestionReceipt, DicomIngestionRequest


class CbctIngestionService:
    """Orchestrate one patient-scoped DICOM ingestion through an injected port."""

    def __init__(self, ingestion: DicomIngestionPort) -> None:
        self._ingestion = ingestion

    async def ingest(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        request: DicomIngestionRequest,
    ) -> DicomIngestionReceipt:
        return await self._ingestion.ingest(
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            request=request,
        )
