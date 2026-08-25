"""Docker Compose adapter for metrics collection and replica management."""

from __future__ import annotations

import json
import subprocess

from .domain import ScalingSnapshot


class DockerComposeAdapter:
    def __init__(self, compose_file: str, env_file: str | None = None, project_directory: str | None = None):
        self.compose_file = compose_file
        self.env_file = env_file
        self.project_directory = project_directory

    def _compose(self, *args: str, capture: bool = True) -> str:
        command = ["docker", "compose", "-f", self.compose_file]
        if self.env_file:
            command[2:2] = ["--env-file", self.env_file]
        if self.project_directory:
            command[2:2] = ["--project-directory", self.project_directory]
        completed = subprocess.run([*command, *args], check=True, capture_output=capture, text=True)
        return completed.stdout.strip() if capture else ""

    def snapshot(self, service: str) -> ScalingSnapshot:
        ids = [line for line in self._compose("ps", "-q", service).splitlines() if line]
        if not ids:
            return ScalingSnapshot(0, 0, None, None)

        inspect = subprocess.run(["docker", "inspect", *ids], check=True, capture_output=True, text=True)
        details = json.loads(inspect.stdout)
        healthy = 0
        for item in details:
            state = item.get("State", {})
            health = state.get("Health", {}).get("Status")
            if state.get("Running") and health in (None, "healthy"):
                healthy += 1

        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemPerc}}", *ids],
            check=True,
            capture_output=True,
            text=True,
        )
        cpu_values: list[float] = []
        mem_values: list[float] = []
        for line in stats.stdout.splitlines():
            if not line.strip():
                continue
            cpu_raw, mem_raw = line.split("\t", 1)
            cpu_values.append(_percent(cpu_raw))
            mem_values.append(_percent(mem_raw))
        if not cpu_values or not mem_values:
            return ScalingSnapshot(len(ids), healthy, None, None)
        return ScalingSnapshot(
            replicas=len(ids),
            healthy_replicas=healthy,
            cpu_percent=sum(cpu_values) / len(cpu_values),
            memory_percent=sum(mem_values) / len(mem_values),
        )

    def scale(self, service: str, replicas: int) -> None:
        self._compose("scale", "--no-deps", f"{service}={replicas}", capture=False)


def _percent(value: str) -> float:
    return float(value.strip().removesuffix("%"))
