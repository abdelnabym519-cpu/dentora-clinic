#!/usr/bin/env python3
"""Run the Dentora host-side autoscaling control loop."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from dataclasses import asdict
from pathlib import Path

from .config import load_policy
from .docker_compose import DockerComposeAdapter
from .domain import ScaleAction, ScalingDecision, ScalingSnapshot, ScalingState, evaluate

LOG = logging.getLogger("dentora.autoscaling")


def _load_state(path: Path) -> ScalingState:
    if not path.exists():
        return ScalingState()
    try:
        return ScalingState(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        LOG.warning("state_load_failed", extra={"path": str(path)})
        return ScalingState()


def _save_state(path: Path, state: ScalingState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _write_metrics(path: Path, snapshot: ScalingSnapshot, decision: ScalingDecision) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cpu = "NaN" if snapshot.cpu_percent is None else f"{snapshot.cpu_percent:.3f}"
    memory = "NaN" if snapshot.memory_percent is None else f"{snapshot.memory_percent:.3f}"
    queue = "NaN" if snapshot.queue_depth is None else str(snapshot.queue_depth)
    action = {ScaleAction.NONE: 0, ScaleAction.OUT: 1, ScaleAction.IN: -1}[decision.action]
    body = (
        "# HELP dentora_autoscaler_replicas Current API replicas.\n"
        "# TYPE dentora_autoscaler_replicas gauge\n"
        f"dentora_autoscaler_replicas {snapshot.replicas}\n"
        "# HELP dentora_autoscaler_healthy_replicas Healthy API replicas.\n"
        "# TYPE dentora_autoscaler_healthy_replicas gauge\n"
        f"dentora_autoscaler_healthy_replicas {snapshot.healthy_replicas}\n"
        "# HELP dentora_autoscaler_cpu_percent Average container CPU utilization.\n"
        "# TYPE dentora_autoscaler_cpu_percent gauge\n"
        f"dentora_autoscaler_cpu_percent {cpu}\n"
        "# HELP dentora_autoscaler_memory_percent Average container memory utilization.\n"
        "# TYPE dentora_autoscaler_memory_percent gauge\n"
        f"dentora_autoscaler_memory_percent {memory}\n"
        "# HELP dentora_autoscaler_queue_depth Optional queue depth signal.\n"
        "# TYPE dentora_autoscaler_queue_depth gauge\n"
        f"dentora_autoscaler_queue_depth {queue}\n"
        "# HELP dentora_autoscaler_last_action Last decision: -1 in, 0 none, 1 out.\n"
        "# TYPE dentora_autoscaler_last_action gauge\n"
        f"dentora_autoscaler_last_action {action}\n"
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def run_once(policy_path: str, compose_file: str, env_file: str | None, project_directory: str | None, dry_run: bool) -> ScalingDecision:
    policy = load_policy(policy_path)
    state_path = Path(policy.state_path)
    state = _load_state(state_path)
    adapter = DockerComposeAdapter(compose_file, env_file, project_directory)
    snapshot = adapter.snapshot(policy.service)
    decision = evaluate(policy, snapshot, state, time.time())
    if decision.action is not ScaleAction.NONE and decision.desired_replicas != snapshot.replicas:
        if dry_run:
            LOG.info("dry_run_scale", extra={"desired_replicas": decision.desired_replicas})
        else:
            adapter.scale(policy.service, decision.desired_replicas)
    _save_state(state_path, decision.state)
    if policy.metrics_path:
        _write_metrics(Path(policy.metrics_path), snapshot, decision)
    print(json.dumps({
        "action": decision.action.value,
        "desired_replicas": decision.desired_replicas,
        "reason": decision.reason,
        "snapshot": asdict(snapshot),
        "dry_run": dry_run,
    }, sort_keys=True))
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="infra/autoscaling/policy.json")
    parser.add_argument("--compose-file", default="docker-compose.prod.yml")
    parser.add_argument("--env-file")
    parser.add_argument("--project-directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    policy = load_policy(args.policy)
    stop = False

    def _stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not stop:
        try:
            run_once(args.policy, args.compose_file, args.env_file, args.project_directory, args.dry_run)
        except Exception:
            LOG.exception("autoscaling_evaluation_failed")
            if args.once:
                return 1
        if args.once:
            return 0
        deadline = time.monotonic() + policy.evaluation_interval_seconds
        while not stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
