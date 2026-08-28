from __future__ import annotations

import asyncio
import hmac
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from .config import Settings
from .contracts import Finding, InferenceResponse, Point, Uncertainty
from .dicom_input import InputArchiveError, prepare_dicom_archive
from .postprocess import extract_canal_findings
from .runtime import DentalSegmentatorRuntime, ModelRuntimeError

settings = Settings.from_env()
runtime = DentalSegmentatorRuntime(settings)
inference_lock = asyncio.Lock()
app = FastAPI(title="Dentora DentalSegmentator nerve inference", version="1.0")


def _authorized(authorization: str | None) -> bool:
    if not settings.service_token:
        return True
    expected = f"Bearer {settings.service_token}"
    return authorization is not None and hmac.compare_digest(authorization, expected)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model_configured": runtime.configured,
        "device": settings.device,
        "commercial_use_approved": settings.commercial_use_approved,
    }


@app.post("/v1/nerve-detection", response_model=InferenceResponse)
async def infer(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dentora_contract: str | None = Header(default=None),
    x_dentora_input_digest: str | None = Header(default=None),
) -> InferenceResponse:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    if x_dentora_contract != "nerve-detection-v1" or not x_dentora_input_digest:
        raise HTTPException(status_code=422, detail="invalid Dentora inference contract")
    if settings.environment == "production" and not settings.commercial_use_approved:
        raise HTTPException(status_code=409, detail="model commercial-use approval gate is not satisfied")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_request_bytes:
                raise HTTPException(status_code=413, detail="request body is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length header") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="request body is too large")
    payload = bytes(body)

    with TemporaryDirectory(prefix="dentora-nerve-") as directory:
        work_dir = Path(directory)
        try:
            prepared = prepare_dicom_archive(
                payload,
                expected_digest=x_dentora_input_digest,
                destination=work_dir / "dicom",
                max_request_bytes=settings.max_request_bytes,
            )
        except InputArchiveError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        async with inference_lock:
            try:
                model_output = await run_in_threadpool(runtime.infer, prepared.files, work_dir)
            except ModelRuntimeError as exc:
                status_code = 422 if exc.initialization else 500
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        processed = extract_canal_findings(
            model_output.segmentation_zyx,
            model_output.geometry,
            confidence=model_output.confidence,
            low_confidence_threshold=settings.low_confidence_threshold,
            min_component_voxels=settings.min_component_voxels,
        )
        findings = [
            Finding(
                side=item.side,
                confidence=item.confidence,
                uncertainty=Uncertainty(
                    value=item.uncertainty,
                    note=(
                        "1 - mean class-5 softmax on voxels predicted as mandibular canal; "
                        "not a calibrated clinical probability"
                    ),
                ),
                points_mm=[Point(x=x, y=y, z=z) for x, y, z in item.points_mm],
            )
            for item in processed.findings
        ]
        return InferenceResponse(
            status=processed.status,
            model_id=model_output.model_id,
            model_version=model_output.model_version,
            findings=findings,
        )
