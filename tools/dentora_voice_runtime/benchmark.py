"""Hardware benchmark for local Dentora Voice faster-whisper models.

The benchmark is validation-only. It never downloads models and never writes
recognized text, audio bytes, PHI, or source file names to the JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import psutil
from faster_whisper import WhisperModel


def _rss_mb(process: psutil.Process) -> float:
    return process.memory_info().rss / (1024 * 1024)


def _directory_size_mb(path: Path) -> float:
    total = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return total / (1024 * 1024)


def _cpu_name() -> str:
    return (
        os.getenv("PROCESSOR_IDENTIFIER")
        or platform.processor()
        or platform.machine()
        or "unknown"
    )


def _sample_process(
    stop: threading.Event,
    process: psutil.Process,
    rss_values: list[float],
    cpu_values: list[float],
) -> None:
    process.cpu_percent(interval=None)
    while not stop.wait(0.05):
        rss_values.append(_rss_mb(process))
        cpu_values.append(process.cpu_percent(interval=None))


def _transcribe(model: WhisperModel, sample: Path) -> tuple[float, float]:
    started = time.perf_counter()
    segments, info = model.transcribe(
        str(sample),
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    # Exhaust the generator so inference completes, but deliberately discard text.
    for _segment in segments:
        pass
    elapsed = time.perf_counter() - started
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    return elapsed, duration


def benchmark_model(name: str, model_path: Path, samples: list[Path]) -> dict[str, Any]:
    if not model_path.is_dir():
        raise SystemExit(f"{name} model directory does not exist: {model_path}")
    if not (model_path / "model.bin").is_file():
        raise SystemExit(f"{name} is not a local CTranslate2 model directory: {model_path}")

    for sample in samples:
        if not sample.is_file():
            raise SystemExit(f"Audio sample does not exist: {sample}")

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

    # One private warm-up pass. No transcript or filename is retained.
    warmup_seconds, _ = _transcribe(model, samples[0])

    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        rss_values: list[float] = [_rss_mb(process)]
        cpu_values: list[float] = []
        stop = threading.Event()
        sampler = threading.Thread(
            target=_sample_process,
            args=(stop, process, rss_values, cpu_values),
            daemon=True,
        )
        sampler.start()
        elapsed, duration = _transcribe(model, sample)
        stop.set()
        sampler.join()
        rows.append(
            {
                "sample_index": index,
                "sample_bytes": sample.stat().st_size,
                "audio_duration_seconds": round(duration, 4),
                "warm_transcription_latency_seconds": round(elapsed, 4),
                "real_time_factor": round(elapsed / duration, 4) if duration > 0 else None,
                "peak_rss_mb": round(max(rss_values), 2),
                "process_cpu_percent_avg": round(statistics.fmean(cpu_values), 2)
                if cpu_values
                else 0.0,
                "process_cpu_percent_peak": round(max(cpu_values), 2) if cpu_values else 0.0,
            }
        )

    warm_latencies = [row["warm_transcription_latency_seconds"] for row in rows]
    return {
        "engine": "faster-whisper",
        "model": name,
        "model_directory": model_path.name,
        "model_size_mb": round(_directory_size_mb(model_path), 2),
        "device": "cpu",
        "compute_type": "int8",
        "local_files_only": True,
        "model_load_seconds": round(load_seconds, 4),
        "warmup_seconds": round(warmup_seconds, 4),
        "warm_latency_mean_seconds": round(statistics.fmean(warm_latencies), 4),
        "rss_before_mb": round(before_mb, 2),
        "rss_after_load_mb": round(loaded_mb, 2),
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--small-model", type=Path, required=True)
    parser.add_argument("--sample", action="append", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dentora-voice-benchmark.json"),
    )
    args = parser.parse_args()

    system = {
        "platform": platform.platform(),
        "cpu": _cpu_name(),
        "physical_cpu_cores": psutil.cpu_count(logical=False),
        "logical_cpu_cores": psutil.cpu_count(logical=True),
        "total_ram_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
    }
    report = {
        "privacy": {
            "transcript_logged": False,
            "audio_logged": False,
            "source_file_names_logged": False,
            "phi_allowed": False,
        },
        "system": system,
        "base": benchmark_model("base-multilingual", args.base_model, args.sample),
        "small": benchmark_model("small-multilingual", args.small_model, args.sample),
    }
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
