"""Tests for continuity synthesis, markdown rendering, persistence, and freshness."""

from pathlib import Path

from myagentos.continuity.discovery import run_static_discovery
from myagentos.continuity.models import ContinuationFreshnessState
from myagentos.continuity.snapshot import create_project_snapshot
from myagentos.continuity.store import ContinuityStore
from myagentos.continuity.synthesizer import (
    render_continuation_markdown,
    synthesize_continuation_report,
)


def test_synthesizer_and_markdown_generation() -> None:
    """Verifies that synthesis and human markdown rendering follow §17 and §19."""
    repo_root = Path(__file__).parent.parent
    snapshot = create_project_snapshot(repo_root)
    arch, findings = run_static_discovery(repo_root, snapshot)

    report = synthesize_continuation_report(
        snapshot=snapshot,
        architecture=arch,
        findings=findings,
    )

    assert report.summary != ""
    assert report.context_digest is not None
    assert len(report.context_digest) == 64
    assert len(report.recommended_next_steps) > 0

    md = render_continuation_markdown(snapshot, arch, report)
    assert "# Project Continuation Context" in md
    assert "## Snapshot" in md
    assert "## Executive Summary" in md
    assert "## Project Shape" in md
    assert "## Recommended Continuation" in md


def test_continuity_store_save_load_and_freshness(tmp_path: Path) -> None:
    """Verifies saving bundles under .myagentos/projects/<id>/continuity
    and evaluating freshness.
    """
    store = ContinuityStore(repo_root=tmp_path)
    snapshot = create_project_snapshot(tmp_path)
    arch, findings = run_static_discovery(tmp_path, snapshot)
    report = synthesize_continuation_report(snapshot, arch, findings)

    target_dir = store.save_pack(
        project_id="test-proj",
        snapshot=snapshot,
        architecture=arch,
        findings=findings,
        report=report,
    )

    assert (target_dir / "snapshot.json").is_file()
    assert (target_dir / "architecture.json").is_file()
    assert (target_dir / "findings.json").is_file()
    assert (target_dir / "continuation_report.json").is_file()
    assert (target_dir / "CONTINUATION_CONTEXT.md").is_file()
    assert (target_dir / "manifest.json").is_file()

    # Load latest report
    loaded = store.load_latest_report("test-proj")
    assert loaded is not None
    assert loaded.context_digest == report.context_digest

    # Freshness evaluation: same snapshot -> VALID
    freshness = store.evaluate_freshness(snapshot, snapshot, report)
    assert freshness.state == ContinuationFreshnessState.VALID
    assert freshness.stale_reason is None

    # Altered commit -> STALE
    modified_snapshot = snapshot.model_copy(update={"base_commit": "new_commit_hash"})
    stale_freshness = store.evaluate_freshness(modified_snapshot, snapshot, report)
    assert stale_freshness.state == ContinuationFreshnessState.STALE
    assert stale_freshness.stale_reason is not None
    assert "Base commit changed" in stale_freshness.stale_reason


def test_synthesizer_with_gateway_mock() -> None:
    """Verifies synthesis with an active ModelGateway using MockProviderAdapter."""
    from myagentos.gateway import MockProviderAdapter, ModelGateway

    gateway = ModelGateway()
    mock_adapter = MockProviderAdapter()
    mock_adapter.set_response("", "Enhanced AI summary of project findings.")
    gateway.register_adapter("mock", mock_adapter)

    repo_root = Path(__file__).parent.parent
    snapshot = create_project_snapshot(repo_root)
    arch, findings = run_static_discovery(repo_root, snapshot)

    report = synthesize_continuation_report(
        snapshot=snapshot,
        architecture=arch,
        findings=findings,
        gateway=gateway,
        model_id="mock-model",
    )

    assert report.summary == "Enhanced AI summary of project findings."
    assert report.context_digest is not None
    assert len(report.context_digest) == 64
