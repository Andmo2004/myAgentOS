"""Project Categorization Service orchestrating discovery, detection, inference, and persistence.

Follows §5, §8, §13, and §19 of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from myagentos.categorization.detector import detect_repository_facts
from myagentos.categorization.fingerprint import calculate_fingerprint
from myagentos.categorization.inferencer import SemanticInferencer
from myagentos.categorization.models import (
    Inference,
    PresentationOverrides,
    ProfileStatus,
    ProjectProfile,
    TagCategory,
    TagSource,
)
from myagentos.categorization.selector import ScoredCandidate, select_visible_tags
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.client import ModelGateway

logger = logging.getLogger(__name__)


class ProjectCategorizationService:
    """Canonical service managing Project Profile scans, incremental caching, and tag selection."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        event_store: EventStore | None = None,
        model_id: str = "mock-categorizer",
    ) -> None:
        self.gateway = gateway or ModelGateway()
        self.event_store = event_store
        self.inferencer = SemanticInferencer(gateway=self.gateway, model_id=model_id)

    def scan_project(
        self,
        repo_root: Path,
        project_id: str | None = None,
        force: bool = False,
        overrides: PresentationOverrides | None = None,
    ) -> ProjectProfile:
        """Executes full categorization pipeline or returns cached fresh profile (§8, §13)."""
        repo_root = repo_root.resolve()
        p_id = project_id or repo_root.name
        profile_file = repo_root / ".myagentos" / "project_profile.json"

        # 1. Compute fingerprint
        fingerprint = calculate_fingerprint(repo_root)

        # 2. Check cached profile if not forced (§13)
        if not force and profile_file.is_file():
            try:
                cached_data = json.loads(profile_file.read_text(encoding="utf-8"))
                cached = ProjectProfile.model_validate(cached_data)
                if cached.scan_hash == fingerprint.combined_hash:
                    return cached
                # If hash changed, mark stale and continue to re-scan
                if self.event_store:
                    self._emit_event(
                        job_id=p_id,
                        state="PROJECT_SNAPSHOT",
                        event_name=EventName.PROJECT_PROFILE_STALE,
                        payload={"reason": "fingerprint_changed"},
                    )
            except Exception as exc:
                logger.debug("Failed reading cached profile: %s", exc)

        # 3. Emit SCAN_STARTED
        if self.event_store:
            self._emit_event(
                job_id=p_id,
                state="PROJECT_SNAPSHOT",
                event_name=EventName.PROJECT_PROFILE_SCAN_STARTED,
                payload={"repo": repo_root.name},
            )

        # 4. Phase B: Deterministic detection (§8)
        detection = detect_repository_facts(repo_root)

        # 5. Phase D: Semantic domain inference (§8, §24)
        top_paths = [p.name for p in repo_root.iterdir() if not p.name.startswith(".")]
        domain_inference = self.inferencer.infer_domain(
            repo_name=repo_root.name,
            detected_stack=detection.stack.languages + detection.stack.frameworks,
            detected_apps=detection.architecture.application_type,
            key_paths=top_paths,
        )

        inferences: list[Inference] = []
        if domain_inference.status == "accepted":
            inferences.append(domain_inference)

        # 6. Gather all candidates for 3-5 tags selection (§10)
        candidates: list[ScoredCandidate] = []

        # Domain candidate
        if domain_inference.status == "accepted":
            candidates.append(
                ScoredCandidate(
                    label=domain_inference.value,
                    category=TagCategory.DOMAIN,
                    confidence=domain_inference.confidence,
                    source=TagSource.INFERRED,
                    evidence=domain_inference.evidence,
                )
            )

        # Application candidates
        for app in detection.architecture.application_type:
            candidates.append(
                ScoredCandidate(
                    label=app,
                    category=TagCategory.APPLICATION,
                    confidence=1.0,
                    source=TagSource.DETERMINISTIC,
                    evidence=detection.evidence_by_tag.get(app, ["Detected application pattern"]),
                )
            )

        # Framework candidates
        for fw in detection.stack.frameworks:
            candidates.append(
                ScoredCandidate(
                    label=fw,
                    category=TagCategory.FRAMEWORK,
                    confidence=1.0,
                    source=TagSource.DETERMINISTIC,
                    evidence=detection.evidence_by_tag.get(fw, ["Manifest dependency"]),
                )
            )

        # Language / Technology candidates
        for lang in detection.stack.languages[:2]:
            candidates.append(
                ScoredCandidate(
                    label=lang,
                    category=TagCategory.TECHNOLOGY,
                    confidence=0.95,
                    source=TagSource.DETERMINISTIC,
                    evidence=detection.evidence_by_tag.get(lang, ["Source files"]),
                )
            )

        # Infrastructure / Database candidates
        for db in detection.stack.databases:
            candidates.append(
                ScoredCandidate(
                    label=db,
                    category=TagCategory.INFRASTRUCTURE,
                    confidence=0.9,
                    source=TagSource.DETERMINISTIC,
                    evidence=detection.evidence_by_tag.get(db, ["Database driver dependency"]),
                )
            )

        # Production lifecycle candidate
        if "Production" in detection.evidence_by_tag:
            candidates.append(
                ScoredCandidate(
                    label="Production",
                    category=TagCategory.LIFECYCLE,
                    confidence=0.85,
                    source=TagSource.DETERMINISTIC,
                    evidence=detection.evidence_by_tag.get("Production", []),
                )
            )

        # 7. Select 3-5 visible tags (§10)
        visible_tags = select_visible_tags(candidates, overrides=overrides)

        # 8. Build canonical ProjectProfile (§6)
        profile = ProjectProfile(
            project_id=p_id,
            repository=repo_root.name,
            base_revision="HEAD",
            analyzed_at=datetime.now(UTC),
            status=ProfileStatus.FRESH,
            stack=detection.stack,
            architecture=detection.architecture,
            infrastructure=detection.infrastructure,
            quality=detection.quality,
            inferences=inferences,
            visible_tags=visible_tags,
            presentation_overrides=overrides or PresentationOverrides(),
            scan_hash=fingerprint.combined_hash,
            categorizer_version="1.0",
        )

        # 9. Emit events to EventStore (§19)
        if self.event_store:
            self._emit_event(
                job_id=p_id,
                state="PROJECT_SNAPSHOT",
                event_name=EventName.PROJECT_PROFILE_SCANNED,
                payload={"facts_count": detection.observed_facts_count},
            )
            self._emit_event(
                job_id=p_id,
                state="PROJECT_SNAPSHOT",
                event_name=EventName.PROJECT_PROFILE_UPDATED,
                payload={"tags": [t.label for t in visible_tags]},
            )

        # 10. Persist profile to .myagentos/project_profile.json
        try:
            profile_file.parent.mkdir(parents=True, exist_ok=True)
            profile_file.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed saving project profile: %s", exc)

        return profile

    def _emit_event(
        self,
        job_id: str,
        state: str,
        event_name: EventName,
        payload: dict[str, Any],
    ) -> None:
        if not self.event_store:
            return
        try:
            self.event_store.append(
                job_id=job_id,
                actor=EventActor.CATEGORIZER,
                state=state,
                event_name=event_name,
                payload=payload,
            )
        except Exception as exc:
            logger.debug("EventStore append error: %s", exc)
