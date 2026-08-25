"""Ports for infrastructure adapters used by the autoscaling use case."""

from __future__ import annotations

from typing import Protocol

from .domain import ScalingSnapshot


class MetricsSource(Protocol):
    def snapshot(self, service: str) -> ScalingSnapshot: ...


class ReplicaManager(Protocol):
    def scale(self, service: str, replicas: int) -> None: ...
