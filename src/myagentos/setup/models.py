"""Data models for Mya First Run and Setup configuration (§15).

Follows docs/new_features/agentic-os-feature-mya-first-run-setup.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SetupMeta(BaseModel):
    """Metadata about first-run setup completion status."""

    model_config = ConfigDict(extra="ignore")

    completed: bool = False
    completed_at: str | None = None
    version: int = 1


class UserConfig(BaseModel):
    """User interface and identity preferences."""

    model_config = ConfigDict(extra="ignore")

    display_name: str = ""


class UIConfig(BaseModel):
    """UI display preferences."""

    model_config = ConfigDict(extra="ignore")

    theme: str = "default"
    motion: str = "full"


class MyaHomeConfig(BaseModel):
    """Mya home location and persistent environment metadata."""

    model_config = ConfigDict(extra="ignore")

    home: str = ""


class SetupConfig(BaseModel):
    """Root configuration for Mya and Agentic OS persistent environment."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    setup: SetupMeta = Field(default_factory=SetupMeta)
    user: UserConfig = Field(default_factory=UserConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    mya: MyaHomeConfig = Field(default_factory=MyaHomeConfig)

    @property
    def setup_completed(self) -> bool:
        """Convenience property for checking setup completion."""
        return self.setup.completed

    @setup_completed.setter
    def setup_completed(self, value: bool) -> None:
        self.setup.completed = value
