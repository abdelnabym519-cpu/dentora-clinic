"""Pure autoscaling domain models and policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ScaleAction(str, Enum):
    NONE = "none"
    OUT = "scale_out"
    IN = "scale_in"


@dataclass(frozen=True)
class Thresholds:
    scale_out_percent: float
    scale_in_percent: float


@dataclass(frozen=True)
class DirectionPolicy:
    step: int
    breaches: int
    cooldown_seconds: int
    stabilization_seconds: int = 0


@dataclass(frozen=True)
class QueuePolicy:
    enabled: bool
    scale_out_depth: int
    scale_in_depth: int


@dataclass(frozen=True)
class ScalingPolicy:
    service: str
    min_replicas: int
    max_replicas: int
    cpu: Thresholds
    memory: Thresholds
    queue: QueuePolicy
    scale_out: DirectionPolicy
    scale_in: DirectionPolicy
    evaluation_interval_seconds: int
    state_path: str
    metrics_path: str | None


@dataclass(frozen=True)
class ScalingSnapshot:
    replicas: int
    healthy_replicas: int
    cpu_percent: float | None
    memory_percent: float | None
    queue_depth: int | None = None


@dataclass
class ScalingState:
    high_breaches: int = 0
    low_breaches: int = 0
    last_scale_out_at: float | None = None
    last_scale_in_at: float | None = None


@dataclass(frozen=True)
class ScalingDecision:
    action: ScaleAction
    desired_replicas: int
    reason: str
    state: ScalingState = field(compare=False)


def _elapsed(now: float, then: float | None) -> float:
    return float("inf") if then is None else max(0.0, now - then)


def evaluate(policy: ScalingPolicy, snapshot: ScalingSnapshot, state: ScalingState, now: float) -> ScalingDecision:
    """Return one safe scaling decision without side effects."""
    if snapshot.replicas < policy.min_replicas:
        state.high_breaches = 0
        state.low_breaches = 0
        return ScalingDecision(ScaleAction.OUT, policy.min_replicas, "replica count below configured minimum", state)

    if snapshot.replicas <= 0 or snapshot.cpu_percent is None or snapshot.memory_percent is None:
        state.high_breaches = 0
        state.low_breaches = 0
        return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "resource metrics unavailable", state)

    queue_high = policy.queue.enabled and snapshot.queue_depth is not None and snapshot.queue_depth >= policy.queue.scale_out_depth
    high = snapshot.cpu_percent >= policy.cpu.scale_out_percent or snapshot.memory_percent >= policy.memory.scale_out_percent or queue_high
    queue_low = not policy.queue.enabled or (snapshot.queue_depth is not None and snapshot.queue_depth <= policy.queue.scale_in_depth)
    low = snapshot.cpu_percent <= policy.cpu.scale_in_percent and snapshot.memory_percent <= policy.memory.scale_in_percent and queue_low

    if high:
        state.high_breaches += 1
        state.low_breaches = 0
        if snapshot.replicas >= policy.max_replicas:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "at configured maximum replicas", state)
        if state.high_breaches < policy.scale_out.breaches:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "waiting for scale-out breach quorum", state)
        if _elapsed(now, state.last_scale_out_at) < policy.scale_out.cooldown_seconds:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "scale-out cooldown active", state)
        desired = min(policy.max_replicas, snapshot.replicas + policy.scale_out.step)
        state.high_breaches = 0
        state.last_scale_out_at = now
        return ScalingDecision(ScaleAction.OUT, desired, "high resource or queue pressure", state)

    if low:
        state.low_breaches += 1
        state.high_breaches = 0
        if snapshot.replicas <= policy.min_replicas:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "at configured minimum replicas", state)
        if snapshot.healthy_replicas != snapshot.replicas:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "scale-in blocked: one or more replicas unhealthy", state)
        if state.low_breaches < policy.scale_in.breaches:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "waiting for scale-in breach quorum", state)
        if _elapsed(now, state.last_scale_in_at) < policy.scale_in.cooldown_seconds:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "scale-in cooldown active", state)
        if _elapsed(now, state.last_scale_out_at) < policy.scale_in.stabilization_seconds:
            return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "scale-in stabilization window active", state)
        desired = max(policy.min_replicas, snapshot.replicas - policy.scale_in.step)
        state.low_breaches = 0
        state.last_scale_in_at = now
        return ScalingDecision(ScaleAction.IN, desired, "sustained low resource and queue pressure", state)

    state.high_breaches = 0
    state.low_breaches = 0
    return ScalingDecision(ScaleAction.NONE, snapshot.replicas, "within configured scaling band", state)
