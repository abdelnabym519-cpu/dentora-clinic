from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.autoscaling.config import PolicyError, load_policy
from scripts.autoscaling.domain import DirectionPolicy, QueuePolicy, ScaleAction, ScalingPolicy, ScalingSnapshot, ScalingState, Thresholds, evaluate
from scripts.autoscaling.docker_compose import _percent


def policy() -> ScalingPolicy:
    return ScalingPolicy(
        service="backend",
        min_replicas=1,
        max_replicas=4,
        cpu=Thresholds(70, 35),
        memory=Thresholds(75, 50),
        queue=QueuePolicy(False, 100, 20),
        scale_out=DirectionPolicy(1, 2, 60),
        scale_in=DirectionPolicy(1, 3, 300, 300),
        evaluation_interval_seconds=30,
        state_path=".dentora/state.json",
        metrics_path=None,
    )


class PolicyTests(unittest.TestCase):
    def test_scale_out_requires_breach_quorum(self) -> None:
        state = ScalingState()
        snap = ScalingSnapshot(1, 1, 85, 40)
        first = evaluate(policy(), snap, state, 1000)
        second = evaluate(policy(), snap, state, 1001)
        self.assertEqual(first.action, ScaleAction.NONE)
        self.assertEqual(second.action, ScaleAction.OUT)
        self.assertEqual(second.desired_replicas, 2)

    def test_memory_can_trigger_scale_out(self) -> None:
        decision = evaluate(policy(), ScalingSnapshot(2, 2, 20, 90), ScalingState(high_breaches=1), 1000)
        self.assertEqual(decision.action, ScaleAction.OUT)

    def test_scale_in_requires_all_replicas_healthy(self) -> None:
        state = ScalingState(low_breaches=2, last_scale_out_at=0)
        decision = evaluate(policy(), ScalingSnapshot(3, 2, 10, 10), state, 1000)
        self.assertEqual(decision.action, ScaleAction.NONE)
        self.assertIn("unhealthy", decision.reason)

    def test_scale_in_obeys_stabilization(self) -> None:
        state = ScalingState(low_breaches=2, last_scale_out_at=900)
        decision = evaluate(policy(), ScalingSnapshot(3, 3, 10, 10), state, 1000)
        self.assertEqual(decision.action, ScaleAction.NONE)
        self.assertIn("stabilization", decision.reason)

    def test_scale_in_after_sustained_low_pressure(self) -> None:
        state = ScalingState(low_breaches=2, last_scale_out_at=0)
        decision = evaluate(policy(), ScalingSnapshot(3, 3, 10, 10), state, 1000)
        self.assertEqual(decision.action, ScaleAction.IN)
        self.assertEqual(decision.desired_replicas, 2)

    def test_min_and_max_are_bounds(self) -> None:
        low = evaluate(policy(), ScalingSnapshot(0, 0, None, None), ScalingState(), 1000)
        high = evaluate(policy(), ScalingSnapshot(4, 4, 99, 99), ScalingState(high_breaches=2), 1000)
        self.assertEqual((low.action, low.desired_replicas), (ScaleAction.OUT, 1))
        self.assertEqual((high.action, high.desired_replicas), (ScaleAction.NONE, 4))

    def test_queue_signal_is_optional_and_extensible(self) -> None:
        base = policy()
        queued = ScalingPolicy(**{**base.__dict__, "queue": QueuePolicy(True, 100, 10)})
        decision = evaluate(queued, ScalingSnapshot(2, 2, 10, 10, 150), ScalingState(high_breaches=1), 1000)
        self.assertEqual(decision.action, ScaleAction.OUT)

    def test_missing_metrics_fail_closed(self) -> None:
        decision = evaluate(policy(), ScalingSnapshot(2, 2, None, 20), ScalingState(), 1000)
        self.assertEqual(decision.action, ScaleAction.NONE)

    def test_percent_parser(self) -> None:
        self.assertEqual(_percent("12.5%"), 12.5)


class ConfigTests(unittest.TestCase):
    def test_repository_policy_loads(self) -> None:
        repository_policy = Path(__file__).resolve().parents[3] / "infra/autoscaling/policy.json"
        loaded = load_policy(repository_policy)
        self.assertLess(loaded.cpu.scale_in_percent, loaded.cpu.scale_out_percent)

    def test_invalid_threshold_order_is_rejected(self) -> None:
        raw = {
            "service": "backend", "min_replicas": 1, "max_replicas": 4,
            "cpu": {"scale_out_percent": 50, "scale_in_percent": 70},
            "memory": {"scale_out_percent": 75, "scale_in_percent": 50},
            "queue": {"enabled": False, "scale_out_depth": 100, "scale_in_depth": 20},
            "scale_out": {"step": 1, "breaches": 2, "cooldown_seconds": 60},
            "scale_in": {"step": 1, "breaches": 5, "cooldown_seconds": 300, "stabilization_seconds": 300},
            "evaluation_interval_seconds": 30,
            "state_path": ".dentora/state.json", "metrics_path": None,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(PolicyError):
                load_policy(path)


if __name__ == "__main__":
    unittest.main()
