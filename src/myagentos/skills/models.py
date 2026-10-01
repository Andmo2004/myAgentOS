"""Domain models and schemas for Just-in-Time Skills (§20, AUD-027)."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.risk import RiskLevel


class SkillMatchCriteria(BaseModel):
    """Declarative criteria for activating a skill Just-in-Time (§20)."""

    model_config = ConfigDict(frozen=True)

    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords in prompt/task triggering this skill",
    )
    paths: list[str] = Field(
        default_factory=list,
        description="File path glob patterns associated with this skill",
    )
    extensions: list[str] = Field(
        default_factory=list,
        description="File extensions triggering this skill (e.g. '.sql')",
    )


class SkillPermissions(BaseModel):
    """Permissions requested by a skill, acting strictly as a ceiling (§20, AUD-027)."""

    model_config = ConfigDict(frozen=True)

    read: list[str] = Field(
        default_factory=list,
        description="Glob patterns of files readable by this skill",
    )
    write: list[str] = Field(
        default_factory=list,
        description="Glob patterns of files writable by this skill",
    )
    execute: list[str] = Field(
        default_factory=list,
        description="Commands allowed to be executed by this skill",
    )


class SkillVerification(BaseModel):
    """Verification constraints and additive protected paths (§20, §13.2)."""

    model_config = ConfigDict(frozen=True)

    protected_paths_add: list[str] = Field(
        default_factory=list,
        description="Additive protected paths enforced during skill execution",
    )
    commands: list[str] = Field(
        default_factory=list,
        description="Verification commands required by this skill",
    )


class SkillManifest(BaseModel):
    """Canonical specification and metadata of an Agentic OS skill (§20)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Unique slug name of the skill")
    version: str = Field(default="1.0.0", description="Semantic version string")
    source: str = Field(default="local", description="Origin source or URI")
    content_hash: str = Field(default="", description="SHA-256 hash of instructions and metadata")
    signature: str | None = Field(default=None, description="Optional cryptographic signature")
    description: str = Field(default="", description="Purpose and scope of this skill")

    min_risk_level: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Minimum risk level; a skill can only increase risk, never decrease it (§20)",
    )
    preferred_worker_capabilities: list[str] = Field(
        default_factory=list,
        description="Capabilities required from worker models",
    )

    match: SkillMatchCriteria = Field(default_factory=SkillMatchCriteria)
    permissions_requested: SkillPermissions = Field(default_factory=SkillPermissions)
    network_code_execution: str = Field(default="none")
    verification: SkillVerification = Field(default_factory=SkillVerification)
    instructions: str = Field(default="", description="Procedural system prompt instructions")
    skill_dir: Path | None = Field(default=None, description="Source directory if loaded from disk")

    @property
    def identifier(self) -> str:
        """Returns canonical versioned skill identifier."""
        short_hash = self.content_hash[:8] if self.content_hash else "nohash"
        return f"{self.name}@{self.version}#{short_hash}"

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA-256 digest of metadata and instructions."""
        payload: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "min_risk_level": self.min_risk_level.value,
            "match": self.match.model_dump(),
            "permissions_requested": self.permissions_requested.model_dump(),
            "verification": self.verification.model_dump(),
            "instructions": self.instructions.strip(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


from dataclasses import dataclass, field
from typing import Literal

from myagentos.core.errors import MyAgentOSError


class SkillError(MyAgentOSError):
    """Base exception for skill system operations."""


class CircularDependencyError(SkillError):
    """Raised when a circular dependency is detected in the skill graph (§17)."""


class SkillDependencyDepthError(SkillError):
    """Raised when skill dependency depth exceeds allowed threshold (§18)."""


SkillSource = Literal["builtin", "user", "project"]


@dataclass(frozen=True)
class SkillDefinition:
    """Lightweight definition of a skill loaded during discovery without full content (§14)."""

    id: str
    name: str
    description: str
    version: str
    tags: tuple[str, ...]
    triggers: tuple[str, ...]
    source: SkillSource
    path: Path
    requires: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    risk_floor: str = "LOW"
    protected_paths_add: tuple[str, ...] = ()
    requires_network: bool = False
    content_hash: str = ""

    @property
    def tag_set(self) -> set[str]:
        return {t.lower().lstrip("#") for t in self.tags}

    @property
    def trigger_set(self) -> set[str]:
        return {tr.lower() for tr in self.triggers}


@dataclass(frozen=True)
class ActiveSkill:
    """Fully loaded skill with its procedural instructions, activated Just-in-Time (§16)."""

    id: str
    name: str
    content: str
    source: str
    version: str = "1.0.0"
    tags: tuple[str, ...] = ()
    loaded_because: str = ""


@dataclass(frozen=True)
class ActiveSkillContext:
    """Aggregated active skills payload ready for ContextBuilder injection (§16, §23)."""

    skills: tuple[ActiveSkill, ...] = ()
    formatted: str = ""

