"""Unit tests for the BenchmarkHarness."""

from pathlib import Path

from myagentos.benchmark import BenchmarkHarness, BenchmarkTask
from myagentos.core.models.risk import RiskLevel
from myagentos.router.models import RoutingIntent


def test_benchmark_harness_execution(tmp_path: Path) -> None:
    harness = BenchmarkHarness(store_dir=tmp_path)

    task = BenchmarkTask(
        task_id="t-test",
        prompt="Fix calculation bug in billing",
        target_files=["src/billing.py"],
        expected_intent=RoutingIntent.PLANNED_CODE,
        expected_risk=RiskLevel.HIGH,
    )

    metric = harness.run_task(task)
    assert metric.task_id == "t-test"
    assert metric.false_direct is False
    assert metric.risk_monotonically_preserved is True
    assert metric.hash_chain_intact is True
    assert metric.duration_seconds > 0
