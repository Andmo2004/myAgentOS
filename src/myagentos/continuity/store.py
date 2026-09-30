"""Persistence, retrieval, and freshness evaluation for Continuity Context Packs (§20, §24)."""

import json
from pathlib import Path
from typing import Any

from myagentos.continuity.models import (
    ArchitectureMap,
    ContinuationFreshness,
    ContinuationFreshnessState,
    ContinuationReport,
    Finding,
    ProjectBaseline,
    ProjectSnapshot,
)
from myagentos.continuity.synthesizer import render_continuation_markdown


class ContinuityStore:
    """Manages versioned continuation packs under .myagentos/projects/<id>/continuity/ (§20)."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.base_dir = self.repo_root / ".myagentos" / "projects"

    def get_continuity_dir(self, project_id: str, snapshot_id: str) -> Path:
        return self.base_dir / project_id / "continuity" / snapshot_id

    def save_pack(
        self,
        project_id: str,
        snapshot: ProjectSnapshot,
        architecture: ArchitectureMap,
        findings: list[Finding],
        report: ContinuationReport,
        baseline: ProjectBaseline | None = None,
    ) -> Path:
        """Persists the complete continuation bundle and manifest (§20)."""
        target_dir = self.get_continuity_dir(project_id, snapshot.snapshot_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. snapshot.json
        (target_dir / "snapshot.json").write_text(
            json.dumps(snapshot.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

        # 2. architecture.json
        (target_dir / "architecture.json").write_text(
            json.dumps(architecture.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

        # 3. findings.json
        (target_dir / "findings.json").write_text(
            json.dumps([f.model_dump(mode="json") for f in findings], indent=2),
            encoding="utf-8",
        )

        # 4. baseline.json (optional)
        if baseline:
            (target_dir / "baseline.json").write_text(
                json.dumps(baseline.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )

        # 5. continuation_report.json
        (target_dir / "continuation_report.json").write_text(
            json.dumps(report.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

        # 6. CONTINUATION_CONTEXT.md
        md_text = render_continuation_markdown(snapshot, architecture, report, baseline)
        (target_dir / "CONTINUATION_CONTEXT.md").write_text(md_text, encoding="utf-8")

        # 7. manifest.json
        manifest: dict[str, Any] = {
            "snapshot_id": snapshot.snapshot_id,
            "project_id": project_id,
            "base_commit": snapshot.base_commit,
            "snapshot_hash": snapshot.calculate_snapshot_hash(),
            "architecture_hash": architecture.calculate_architecture_hash(),
            "report_hash": report.calculate_report_hash(),
            "context_digest": report.context_digest,
            "created_at": snapshot.created_at.isoformat(),
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        return target_dir

    def load_latest_report(self, project_id: str) -> ContinuationReport | None:
        """Finds and loads the most recent continuation report for a project."""
        pdir = self.base_dir / project_id / "continuity"
        if not pdir.is_dir():
            return None

        snapshot_dirs = [d for d in pdir.iterdir() if d.is_dir()]
        if not snapshot_dirs:
            return None

        # Sort by modification time descending
        snapshot_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        latest = snapshot_dirs[0]

        report_file = latest / "continuation_report.json"
        if not report_file.is_file():
            return None

        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            return ContinuationReport.model_validate(data)
        except Exception:
            return None

    def evaluate_freshness(
        self,
        current_snapshot: ProjectSnapshot,
        saved_snapshot: ProjectSnapshot,
        saved_report: ContinuationReport,
    ) -> ContinuationFreshness:
        """Evaluates whether a cached continuation context is VALID or STALE (§24)."""
        is_stale = False
        stale_reasons: list[str] = []

        if current_snapshot.base_commit != saved_snapshot.base_commit:
            is_stale = True
            old_c = saved_snapshot.base_commit[:7]
            new_c = current_snapshot.base_commit[:7]
            stale_reasons.append(f"Base commit changed ({old_c} -> {new_c})")

        if current_snapshot.working_tree.content_hash != saved_snapshot.working_tree.content_hash:
            is_stale = True
            stale_reasons.append("Working tree content hash has changed")

        # Check lockfile changes
        if current_snapshot.dependency_lock_hashes != saved_snapshot.dependency_lock_hashes:
            is_stale = True
            stale_reasons.append("Dependency lockfile hashes have changed")

        state = ContinuationFreshnessState.STALE if is_stale else ContinuationFreshnessState.VALID
        stale_reason_str = "; ".join(stale_reasons) if stale_reasons else None

        return ContinuationFreshness(
            base_commit=current_snapshot.base_commit,
            working_tree_hash=current_snapshot.working_tree.content_hash,
            dependency_hash=str(hash(frozenset(current_snapshot.dependency_lock_hashes.items()))),
            architecture_hash=saved_report.context_digest or "unknown",
            policy_version=current_snapshot.policy_version,
            state=state,
            stale_reason=stale_reason_str,
        )
