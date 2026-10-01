"""Unit tests for setup models (§15)."""

from myagentos.setup.models import (
    MyaHomeConfig,
    SetupConfig,
    SetupMeta,
    UIConfig,
    UserConfig,
)


def test_default_setup_config() -> None:
    config = SetupConfig()
    assert config.schema_version == 1
    assert config.setup.completed is False
    assert config.setup_completed is False
    assert config.user.display_name == ""
    assert config.ui.theme == "default"
    assert config.ui.motion == "full"
    assert config.mya.home == ""


def test_setup_config_serialization() -> None:
    config = SetupConfig(
        schema_version=1,
        setup=SetupMeta(completed=True, completed_at="2026-10-01T00:00:00Z"),
        user=UserConfig(display_name="Andrés"),
        ui=UIConfig(theme="dark", motion="full"),
        mya=MyaHomeConfig(home="/Users/andres/.agenticos"),
    )
    dumped = config.model_dump(mode="json")
    assert dumped["setup"]["completed"] is True
    assert dumped["user"]["display_name"] == "Andrés"
    assert dumped["ui"]["theme"] == "dark"
    assert dumped["mya"]["home"] == "/Users/andres/.agenticos"

    reloaded = SetupConfig.model_validate(dumped)
    assert reloaded.setup_completed is True
    assert reloaded.user.display_name == "Andrés"
    assert reloaded.ui.theme == "dark"


def test_setup_completed_property_setter() -> None:
    config = SetupConfig()
    assert not config.setup_completed
    config.setup_completed = True
    assert config.setup.completed is True
    assert config.setup_completed is True
