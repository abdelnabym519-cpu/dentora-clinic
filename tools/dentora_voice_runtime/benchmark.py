"""Benchmark local faster-whisper base vs small for Dentora Voice.

No model downloads occur: each model argument must be a local CTranslate2
model directory. Audio samples stay local and only aggregate timing/resource
metrics are written to the JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import psutil
from faster_whisper import WhisperModel


def _rss_mb(process: psutil.Process) -> float:
    return process.memory_info().rss / (1024 * 1024)


def _sample_peak_rss(stop: threading.Event, process: psutil.Process, output: list[float]) -> None:
    peak = _rss_mb(process)
    while not stop.wait(0.05):
        peak = max(peak, _rss_mb(process))
    output.append(peak)


def benchmark_model(name: str, model_path: Path, samples: list[Path]) -> dict[str, Any]:
    if not model_path.is_dir():
        raise SystemExit(f"{name} model directory does not exist: {model_path}")

    process = psutil.Process(os.getpid())
    before_mb = _rss_mb(process)
    started = time.perf_counter()
    model = WhisperModel(
        str(model_path),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - started
    loaded_mb = _rss_mb(process)

    rows: list[dict[str, Any]] = []
    for sample in samples:
        if not sample.is_file():
            raise SystemExit(f"Audio sample does not exist: {sample}")

        peak_values: list[float] = []
        stop = threading.Event()
        sampler = threading.Thread(
            target=_sample_peak_rss,
            args=(stop, process, peak_values),
            daemon=True,
        )
        sampler.start()
        started = time.perf_counter()
        segments, info = model.transcribe(
            str(sample),
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        elapsed = time.perf_counter() - started
        stop.set()
        sampler.join()
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        rows.append(
            {
                "sample": sample.name,
                "language": info.language,
                "latency_seconds": round(elapsed, 4),
                "audio_duration_seconds": round(duration, 4),
                "real_time_factor": round(elapsed / duration, 4) if duration > 0 else None,
                "peak_rss_mb": round(max(peak_values or [_rss_mb(process)]), 2),
                "recognized_characters": len(text),
            }
        )

    return {
        "engine": "faster-whisper",
        "model": name,
        "model_directory": model_path.name,
        "device": "cpu",
        "compute_type": "int8",
        "load_seconds": round(load_seconds, 4),
        "rss_before_mb": round(before_mb, 2),
        "rss_after_load_mb": round(loaded_mb, 2),
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--small-model", type=Path, required=True)
    parser.add_argument("--sample", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dentora-voice-benchmark.json"))
    args = parser.parse_args()

    report = {
        "base": benchmark_model("base-multilingual", args.base_model, args.sample),
        "small": benchmark_model("small-multilingual", args.small_model, args.sample),
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
