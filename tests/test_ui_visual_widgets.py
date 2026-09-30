"""Tests for UI widgets rendering (§6, §11, §12, §14, §15)."""

from myagentos.ui.theme.symbols import CostTier, FileActivityState, VisualStatus
from myagentos.ui.visual.state import (
    AgentViewModel,
    FileActivityViewModel,
    JobViewModel,
    VerificationCheck,
    VerificationViewModel,
)
from myagentos.ui.widgets import (
    AgentTreeWidget,
    FileActivityWidget,
    JobMonitorWidget,
    MyaAvatarWidget,
    MyaPanelWidget,
    TokenMeterWidget,
    VerificationPanelWidget,
)


def test_mya_avatar_widget_render() -> None:
    widget = MyaAvatarWidget(avatar_mode="dot", expression="focused")
    rendered = widget.render()
    assert "Mya" in rendered
    assert "[focused]" in rendered


def test_mya_panel_widget_render() -> None:
    widget = MyaPanelWidget(message="Processing your request")
    rendered = widget.render()
    assert "Processing your request" in rendered


def test_agent_tree_widget_render() -> None:
    agents = [
        AgentViewModel(
            agent_id="w1",
            role="Worker",
            display_name="Worker-01",
            status=VisualStatus.RUNNING,
            current_activity="Editing repo",
            files=["src/db.py"],
        )
    ]
    widget = AgentTreeWidget(agents)
    rendered = widget.render()
    assert "Worker-01" in rendered
    assert "Editing repo" in rendered
    assert "src/db.py" in rendered


def test_file_activity_widget_render() -> None:
    activities = [
        FileActivityViewModel(
            file_path="src/main.py",
            state=FileActivityState.READ,
            agent_id="WORKER",
        ),
        FileActivityViewModel(
            file_path="src/repo.py",
            state=FileActivityState.MODIFIED,
            agent_id="WORKER",
        ),
    ]
    widget = FileActivityWidget(activities)
    rendered = widget.render()
    assert "src/main.py" in rendered
    assert "src/repo.py" in rendered
    assert "[READ]" in rendered
    assert "[MODIFIED]" in rendered


def test_token_meter_widget_render() -> None:
    widget = TokenMeterWidget(
        used_tokens=15000,
        budget_tokens=50000,
        cost_usd=0.035,
        cost_tier=CostTier.LOW,
    )
    rendered = widget.render()
    assert "15,000 / 50,000" in rendered
    assert "$0.0350" in rendered
    assert "[LOW]" in rendered


def test_verification_panel_widget_render() -> None:
    vm = VerificationViewModel(
        overall_status=VisualStatus.SUCCESS,
        checks=[
            VerificationCheck(
                name="test_suite",
                label="test suite",
                status=VisualStatus.SUCCESS,
            )
        ],
    )
    widget = VerificationPanelWidget(vm)
    rendered = widget.render()
    assert "test suite" in rendered
    assert "✓" in rendered


def test_job_monitor_composite_widget() -> None:
    job = JobViewModel(job_id="job-1", title="Test Job", status=VisualStatus.RUNNING)
    widget = JobMonitorWidget(job=job)
    rendered = widget.render()
    assert "JOB job-1" in rendered
    assert "Test Job" in rendered
