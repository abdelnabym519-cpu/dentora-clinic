"""Pathology detection service — orchestrates inference + persistence.

Flow (POST /analyses):
1. patient + media document validation (read-only imports of
   ``patients`` / ``media`` — no FK, keeps uninstall clean),
2. engine resolution (503 handling lives in the router),
3. image loaded from the storage backend and analyzed in a worker
   thread (CPU-bound torch inference must not block the event loop),
4. findings + FDI placement persisted, summary frozen,
5. failed runs persist as ``status="failed"`` with ``error`` so the
   clinical UI can show the attempt in history.
"""

from __future__ import annotations

import asyncio
import io
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.media.models import Document
from app.modules.media.storage import get_storage_backend
from app.modules.patients.models import Patient

from .constants import (
    ANALYZABLE_MEDIA_KINDS,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    summary_counts,
)
from .engine import EngineUnavailableError, get_engine
from .engine.postprocess import enumerate_fdi
from .models import PathologyAnalysis, PathologyFinding


def _finding_kwargs(enumerated) -> dict:
    data = enumerated.as_dict()
    return {
        "diagnosis": data["diagnosis"],
        "confidence": data["confidence"],
        "bbox": {
            "x1": data["x1"],
            "y1": data["y1"],
            "x2": data["x2"],
            "y2": data["y2"],
        },
        "tooth_number": data["tooth_number"],
        "quadrant": data["quadrant"],
        "position": data["position"],
    }


class PathologyDetectionService:
    """Thin service over the engine + persistence layer."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_patient(self, clinic_id: UUID, patient_id: UUID) -> Patient | None:
        stmt = select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
            Patient.status != "archived",
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_document(
        self,
        clinic_id: UUID,
        patient_id: UUID,
        document_id: UUID,
    ) -> Document | None:
        stmt = select(Document).where(
            Document.id == document_id,
            Document.clinic_id == clinic_id,
            Document.patient_id == patient_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def run_analysis(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        document_id: UUID,
        created_by: UUID,
        notes: str | None = None,
    ) -> PathologyAnalysis:
        """Validate inputs, run the engine, persist the analysis."""
        document = await self.get_document(clinic_id, patient_id, document_id)
        if document is None:
            raise KeyError("document")

        if document.media_kind not in ANALYZABLE_MEDIA_KINDS:
            raise ValueError(
                f"media_kind '{document.media_kind}' is not analyzable "
                f"(expected one of {', '.join(ANALYZABLE_MEDIA_KINDS)})"
            )

        # Resolve the engine *before* creating a history row so an
        # unprovisioned model yields a clean 503 with no stale record.
        engine = get_engine()

        analysis = PathologyAnalysis(
            clinic_id=clinic_id,
            patient_id=patient_id,
            document_id=document_id,
            created_by=created_by,
            status=STATUS_RUNNING,
            notes=notes,
        )
        self._db.add(analysis)
        await self._db.commit()
        await self._db.refresh(analysis)

        try:
            storage = get_storage_backend()
            raw = await storage.retrieve(document.storage_path)
            image = Image.open(io.BytesIO(raw))
            image.load()

            result = await asyncio.to_thread(engine.analyze, image)
            enumerated = enumerate_fdi(result.findings)

            analysis.status = STATUS_COMPLETED
            analysis.engine = result.engine
            analysis.model_version = result.model_version
            analysis.image_width, analysis.image_height = image.size
            analysis.findings_count = len(enumerated)
            analysis.inference_ms = result.inference_ms
            analysis.summary = summary_counts([e.as_dict() for e in enumerated])

            for item in enumerated:
                self._db.add(
                    PathologyFinding(
                        analysis_id=analysis.id,
                        **_finding_kwargs(item),
                    )
                )
            await self._db.commit()
        except (EngineUnavailableError, FileNotFoundError) as exc:
            await self._mark_failed(analysis, str(exc))
            raise
        except (UnidentifiedImageError, OSError) as exc:
            await self._mark_failed(analysis, f"image decode failed: {exc}")
            raise ValueError(f"image decode failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — persist + surface any failure
            await self._mark_failed(analysis, str(exc)[:2000])
            raise

        # Re-load with findings so the caller can serialize without any
        # lazy IO outside the async session.
        reloaded = await self.get_analysis(clinic_id, analysis.id)
        assert reloaded is not None
        return reloaded

    async def _mark_failed(self, analysis: PathologyAnalysis, message: str) -> None:
        analysis.status = STATUS_FAILED
        analysis.error = message[:2000]
        await self._db.commit()

    async def list_analyses(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> list[PathologyAnalysis]:
        stmt = (
            select(PathologyAnalysis)
            .where(
                PathologyAnalysis.clinic_id == clinic_id,
                PathologyAnalysis.patient_id == patient_id,
            )
            .order_by(PathologyAnalysis.created_at.desc())
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_analysis(
        self,
        clinic_id: UUID,
        analysis_id: UUID,
    ) -> PathologyAnalysis | None:
        stmt = (
            select(PathologyAnalysis)
            .options(selectinload(PathologyAnalysis.findings))
            .where(
                PathologyAnalysis.id == analysis_id,
                PathologyAnalysis.clinic_id == clinic_id,
            )
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def delete_analysis(self, analysis: PathologyAnalysis) -> None:
        await self._db.delete(analysis)
        await self._db.commit()
