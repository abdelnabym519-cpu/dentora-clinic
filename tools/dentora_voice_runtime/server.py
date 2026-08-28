"""Loopback-only faster-whisper runtime for Dentora Voice.

Audio is written to a temporary file only for decoder compatibility and is
deleted before the response is returned. The server never logs transcript
content or file names.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel

HOST = "127.0.0.1"
PORT = int(os.getenv("DENTORA_VOICE_PORT", "8765"))
MODEL_PATH = Path(os.getenv("DENTORA_VOICE_MODEL_PATH", "models/faster-whisper-small"))
DEVICE = os.getenv("DENTORA_VOICE_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("DENTORA_VOICE_COMPUTE_TYPE", "int8")
MAX_AUDIO_BYTES = int(os.getenv("DENTORA_VOICE_MAX_AUDIO_BYTES", str(25 * 1024 * 1024)))

app = FastAPI(title="Dentora Voice Local Runtime", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["content-type"],
)

_model: WhisperModel | None = None
_model_loaded_ms: int | None = None

def model() -> WhisperModel:
    global _model, _model_loaded_ms
    if _model is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(
                f"Local faster-whisper model not found at {MODEL_PATH}. "
                "Dentora Voice runtime will not download models automatically."
            )
        started = time.perf_counter()
        _model = WhisperModel(
            str(MODEL_PATH),
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            local_files_only=True,
        )
        _model_loaded_ms = int((time.perf_counter() - started) * 1000)
    return _model

@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "engine": "faster-whisper",
        "model_path": MODEL_PATH.name,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "model_loaded_ms": _model_loaded_ms,
    }

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    raw = await audio.read(MAX_AUDIO_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="empty_audio")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")

    suffix = Path(audio.filename or "audio.webm").suffix[:10] or ".webm"
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="dentora-voice-", suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            path = tmp.name
        started = time.perf_counter()
        segments, info = model().transcribe(
            path,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        text = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()
        elapsed = time.perf_counter() - started
        return {
            "text": text,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration_seconds": getattr(info, "duration", None),
            "transcription_seconds": round(elapsed, 4),
        }
    finally:
        raw = b""
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, access_log=False)
