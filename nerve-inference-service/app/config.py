from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str
    model_dir: Path
    service_token: str
    device: str
    cpu_threads: int
    max_request_bytes: int
    min_component_voxels: int
    low_confidence_threshold: float
    commercial_use_approved: bool

    @classmethod
    def from_env(cls) -> "Settings":
        device = os.getenv("DENTORA_NERVE_DEVICE", "cpu").strip().lower()
        if device not in {"cpu", "cuda"}:
            raise ValueError("DENTORA_NERVE_DEVICE must be cpu or cuda")
        cpu_threads = int(os.getenv("DENTORA_NERVE_CPU_THREADS", "12"))
        max_request_bytes = int(os.getenv("DENTORA_NERVE_MAX_REQUEST_BYTES", "268435456"))
        min_component_voxels = int(os.getenv("DENTORA_NERVE_MIN_COMPONENT_VOXELS", "1"))
        low_confidence_threshold = float(os.getenv("DENTORA_NERVE_LOW_CONFIDENCE_THRESHOLD", "0.6"))
        if cpu_threads < 1 or cpu_threads > 128:
            raise ValueError("DENTORA_NERVE_CPU_THREADS must be between 1 and 128")
        if max_request_bytes < 1024:
            raise ValueError("DENTORA_NERVE_MAX_REQUEST_BYTES is too small")
        if min_component_voxels < 1:
            raise ValueError("DENTORA_NERVE_MIN_COMPONENT_VOXELS must be positive")
        if not 0.0 <= low_confidence_threshold <= 1.0:
            raise ValueError("DENTORA_NERVE_LOW_CONFIDENCE_THRESHOLD must be in [0, 1]")
        return cls(
            environment=os.getenv("ENVIRONMENT", "development").strip().lower(),
            model_dir=Path(os.getenv("DENTORA_NERVE_MODEL_DIR", "/models/model")),
            service_token=os.getenv("DENTORA_NERVE_SERVICE_TOKEN", ""),
            device=device,
            cpu_threads=cpu_threads,
            max_request_bytes=max_request_bytes,
            min_component_voxels=min_component_voxels,
            low_confidence_threshold=low_confidence_threshold,
            commercial_use_approved=_env_bool("DENTORA_NERVE_COMMERCIAL_USE_APPROVED", False),
        )
