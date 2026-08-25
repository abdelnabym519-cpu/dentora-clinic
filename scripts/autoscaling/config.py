"""Autoscaling policy loading and semantic validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import DirectionPolicy, QueuePolicy, ScalingPolicy, Thresholds


class PolicyError(ValueError):
    """Raised when the autoscaling policy is unsafe or incomplete."""


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise PolicyError(f"missing required key: {key}")
    return mapping[key]


def _direction(raw: dict[str, Any], *, scale_in: bool) -> DirectionPolicy:
    return DirectionPolicy(
        step=int(_require(raw, "step")),
        breaches=int(_require(raw, "breaches")),
        cooldown_seconds=int(_require(raw, "cooldown_seconds")),
        stabilization_seconds=int(raw.get("stabilization_seconds", 0)) if scale_in else 0,
    )


def load_policy(path: str | Path) -> ScalingPolicy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    policy = ScalingPolicy(
        service=str(_require(data, "service")),
        min_replicas=int(_require(data, "min_replicas")),
        max_replicas=int(_require(data, "max_replicas")),
        cpu=Thresholds(**_require(data, "cpu")),
        memory=Thresholds(**_require(data, "memory")),
        queue=QueuePolicy(**_require(data, "queue")),
        scale_out=_direction(_require(data, "scale_out"), scale_in=False),
        scale_in=_direction(_require(data, "scale_in"), scale_in=True),
        evaluation_interval_seconds=int(_require(data, "evaluation_interval_seconds")),
        state_path=str(_require(data, "state_path")),
        metrics_path=data.get("metrics_path"),
    )
    validate_policy(policy)
    return policy


def validate_policy(policy: ScalingPolicy) -> None:
    errors: list[str] = []
    if not policy.service.strip():
        errors.append("service must not be empty")
    if policy.min_replicas < 1:
        errors.append("min_replicas must be >= 1")
    if policy.max_replicas < policy.min_replicas:
        errors.append("max_replicas must be >= min_replicas")
    for name, threshold in (("cpu", policy.cpu), ("memory", policy.memory)):
        if not 0 <= threshold.scale_in_percent < threshold.scale_out_percent <= 100:
            errors.append(f"{name} thresholds must satisfy 0 <= scale_in < scale_out <= 100")
    if policy.queue.scale_in_depth < 0 or policy.queue.scale_out_depth < 0:
        errors.append("queue depths must be non-negative")
    if policy.queue.enabled and policy.queue.scale_in_depth >= policy.queue.scale_out_depth:
        errors.append("enabled queue thresholds must satisfy scale_in_depth < scale_out_depth")
    for name, direction in (("scale_out", policy.scale_out), ("scale_in", policy.scale_in)):
        if direction.step < 1:
            errors.append(f"{name}.step must be >= 1")
        if direction.breaches < 1:
            errors.append(f"{name}.breaches must be >= 1")
        if direction.cooldown_seconds < 0:
            errors.append(f"{name}.cooldown_seconds must be >= 0")
    if policy.scale_in.stabilization_seconds < 0:
        errors.append("scale_in.stabilization_seconds must be >= 0")
    if policy.evaluation_interval_seconds < 5:
        errors.append("evaluation_interval_seconds must be >= 5")
    if errors:
        raise PolicyError("; ".join(errors))
