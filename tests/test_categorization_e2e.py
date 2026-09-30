"""End-to-end integration tests for ProjectCategorizationService and EventStore auditing."""

from pathlib import Path

from myagentos.categorization.models import ProfileStatus
from myagentos.categorization.service import ProjectCategorizationService
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore


def test_categorization_service_lifecycle_and_events(tmp_path: Path) -> None:
    """Verify full scan pipeline, EventStore emission, caching, and staleness detection."""
    # Setup test project files
    (tmp_path / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "fastapi-demo"
dependencies = ["fastapi", "pytest"]
[project.scripts]
demo-cli = "main:cli"
"""
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.12")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: Test\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_api.py").write_text("def test_ok(): pass")

    event_store = EventStore(root_dir=tmp_path / ".myagentos" / "jobs")
    service = ProjectCategorizationService(event_store=event_store)

    # 1. Initial Scan
    profile1 = service.scan_project(tmp_path, project_id="test-job-1")

    assert profile1.project_id == "test-job-1"
    assert profile1.status == ProfileStatus.FRESH
    assert "Python" in profile1.stack.languages
    assert "FastAPI" in profile1.stack.frameworks
    assert "Docker" in profile1.infrastructure.containers
    assert len(profile1.visible_tags) >= 2

    # Check persistence
    profile_file = tmp_path / ".myagentos" / "project_profile.json"
    assert profile_file.is_file()

    # Check EventStore events
    events1 = event_store.load_events(job_id="test-job-1")
    event_names = [e.event_name for e in events1]
    assert EventName.PROJECT_PROFILE_SCAN_STARTED in event_names
    assert EventName.PROJECT_PROFILE_SCANNED in event_names
    assert EventName.PROJECT_PROFILE_UPDATED in event_names
    # Verify actor is CATEGORIZER
    for e in events1:
        assert e.actor == EventActor.CATEGORIZER

    # 2. Cached scan (no changes)
    initial_event_count = len(events1)
    profile2 = service.scan_project(tmp_path, project_id="test-job-1")
    assert profile2.scan_hash == profile1.scan_hash

    # No new events should have been emitted
    events2 = event_store.load_events(job_id="test-job-1")
    assert len(events2) == initial_event_count

    # 3. Staleness / Hash change
    # Modify pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "fastapi-demo-updated"
dependencies = ["fastapi", "pytest", "redis"]
"""
    )

    profile3 = service.scan_project(tmp_path, project_id="test-job-1")
    assert profile3.scan_hash != profile1.scan_hash
    assert "Redis" in profile3.stack.databases

    events3 = event_store.load_events(job_id="test-job-1")
    event_names3 = [e.event_name for e in events3]
    assert EventName.PROJECT_PROFILE_STALE in event_names3


def test_categorization_service_on_current_repo() -> None:
    """Verify scanning the active myAgentOS repository."""
    service = ProjectCategorizationService()
    profile = service.scan_project(Path.cwd(), force=True)

    assert profile.repository == "myAgentOS"
    assert "Python" in profile.stack.languages
    assert any(t.label == "Python" for t in profile.visible_tags)
    assert any(t.label == "CLI" for t in profile.visible_tags)
