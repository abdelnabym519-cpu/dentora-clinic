"""Loopback-only faster-whisper runtime for Dentora Voice.

Audio is written to a temporary file only for decoder compatibility and is
deleted before the response is returned. The server never logs transcript
content or file names.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass
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
SHORT_AUDIO_SECONDS = float(os.getenv("DENTORA_VOICE_SHORT_AUDIO_SECONDS", "6.0"))
LOW_LANGUAGE_CONFIDENCE = float(os.getenv("DENTORA_VOICE_LOW_LANGUAGE_CONFIDENCE", "0.60"))
SHORT_AUDIO_FALLBACK_LANGUAGES = ("en", "ar")

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


@dataclass(frozen=True)
class TranscriptionCandidate:
    text: str
    language: str
    language_probability: float
    duration_seconds: float | None
    transcription_seconds: float
    average_log_probability: float


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


def _transcribe_once(path: str, *, language: str | None = None) -> TranscriptionCandidate:
    started = time.perf_counter()
    segments, info = model().transcribe(
        path,
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    materialized = [segment for segment in segments if segment.text.strip()]
    text = " ".join(segment.text.strip() for segment in materialized).strip()
    elapsed = time.perf_counter() - started

    if materialized:
        weights = [max(segment.end - segment.start, 0.001) for segment in materialized]
        total_weight = sum(weights)
        average_log_probability = sum(
            segment.avg_logprob * weight
            for segment, weight in zip(materialized, weights, strict=True)
        ) / total_weight
    else:
        average_log_probability = float("-inf")

    return TranscriptionCandidate(
        text=text,
        language=info.language,
        language_probability=float(info.language_probability),
        duration_seconds=getattr(info, "duration", None),
        transcription_seconds=elapsed,
        average_log_probability=average_log_probability,
    )


def _needs_short_audio_language_fallback(candidate: TranscriptionCandidate) -> bool:
    duration = candidate.duration_seconds
    return bool(
        candidate.text
        and duration is not None
        and duration <= SHORT_AUDIO_SECONDS
        and candidate.language_probability < LOW_LANGUAGE_CONFIDENCE
    )


def _repetition_penalty(text: str) -> float:
    """Penalize obvious short-utterance hallucination loops without logging text."""
    tokens = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    if len(tokens) < 4:
        return 0.0

    repeated_fraction = 1.0 - (len(set(tokens)) / len(tokens))
    penalty = repeated_fraction * 0.8

    if len(tokens) % 2 == 0:
        midpoint = len(tokens) // 2
        if tokens[:midpoint] == tokens[midpoint:]:
            penalty += 0.35

    return penalty


def _collapse_repeated_utterance(text: str) -> str:
    """Collapse exact consecutive STT loops while preserving one spoken command."""
    compact = re.sub(r"\s+", " ", text).strip()
    words = re.findall(r"[^\W_]+", compact, flags=re.UNICODE)
    if len(words) < 4:
        return compact

    normalized = [word.casefold() for word in words]
    for repeats in range(4, 1, -1):
        if len(normalized) % repeats:
            continue
        width = len(normalized) // repeats
        chunk = normalized[:width]
        if all(normalized[index * width : (index + 1) * width] == chunk for index in range(repeats)):
            return " ".join(words[:width])

    return compact


def _candidate_score(candidate: TranscriptionCandidate) -> float:
    return candidate.average_log_probability - _repetition_penalty(candidate.text)


def _transcribe_with_short_audio_fallback(path: str) -> tuple[TranscriptionCandidate, float]:
    started = time.perf_counter()
    automatic = _transcribe_once(path)
    candidates = [automatic]

    if _needs_short_audio_language_fallback(automatic):
        for language in SHORT_AUDIO_FALLBACK_LANGUAGES:
            candidates.append(_transcribe_once(path, language=language))

    selected = max(candidates, key=_candidate_score)
    return selected, time.perf_counter() - started


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

        selected, elapsed = _transcribe_with_short_audio_fallback(path)
        return {
            "text": _collapse_repeated_utterance(selected.text),
            "language": selected.language,
            "language_probability": selected.language_probability,
            "duration_seconds": selected.duration_seconds,
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
