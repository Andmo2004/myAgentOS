"""Least-privilege permission enforcer for skills (§20, §23, AUD-027)."""

from datetime import UTC, datetime, timedelta

from myagentos.core.models.data_policy import TrustTag
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits
from myagentos.skills.models import SkillManifest


class SkillPermissionEnforcer:
    """Enforces least-privilege token intersection, monotonic risk, and additive protected paths."""

    @classmethod
    def skill_to_ceiling_token(
        cls,
        skill: SkillManifest,
        job_id: str,
        worker_id: str,
        base_commit: str,
    ) -> CapabilityToken:
        """Converts requested skill permissions into an upper-bound ceiling token (§20)."""
        return CapabilityToken(
            job_id=job_id,
            worker_id=worker_id,
            risk_level=skill.min_risk_level,
            read_scope=list(skill.permissions_requested.read),
            write_scope=list(skill.permissions_requested.write),
            execute_scope=list(skill.permissions_requested.execute),
            network_scope=NetworkScope.NONE,
            limits=TokenLimits(max_files=10, max_diff_lines=500, max_steps=20),
            trust=TrustTag.UNTRUSTED,
            skills=[skill.identifier],
            base_commit=base_commit,
            expires_at=datetime.now(UTC) + timedelta(minutes=60),
        )

    @classmethod
    def intersect_token_with_skills(
        cls,
        base_token: CapabilityToken,
        skills: list[SkillManifest],
    ) -> CapabilityToken:
        """Applies AUD-027 normative permission formula:

        skill_permissions = requested_permissions ∩ approved_scope ∩ project_policy

        A skill's requested permissions represent a CEILING; a skill can NEVER expand permissions.
        """
        if not skills:
            return base_token

        current_token = base_token
        skill_ids: list[str] = list(base_token.skills)

        for skill in skills:
            ceiling = cls.skill_to_ceiling_token(
                skill=skill,
                job_id=base_token.job_id,
                worker_id=base_token.worker_id,
                base_commit=base_token.base_commit,
            )
            # Intersect preserves only common paths/commands and enforces ceilings
            current_token = current_token.intersect_with(ceiling)
            if skill.identifier not in skill_ids:
                skill_ids.append(skill.identifier)

        # Monotonically elevate risk if any skill has higher minimum risk
        effective_risk = cls.compute_effective_risk(base_token.risk_level, skills)

        return current_token.model_copy(
            update={
                "risk_level": effective_risk,
                "skills": skill_ids,
            }
        )

    @classmethod
    def compute_effective_risk(
        cls,
        base_risk: RiskLevel,
        skills: list[SkillManifest],
    ) -> RiskLevel:
        """Enforces monotonic risk rule (§20, AUD-027):

        skill can increase risk, skill cannot reduce risk.
        """
        effective = base_risk
        for s in skills:
            if s.min_risk_level > effective:
                effective = s.min_risk_level
        return effective

    @classmethod
    def compute_additive_protected_paths(
        cls,
        base_protected_paths: list[str],
        skills: list[SkillManifest],
    ) -> list[str]:
        """Skills can ADD protected paths, but can NEVER remove them (§13.2, §20)."""
        combined = list(base_protected_paths)
        for s in skills:
            for p in s.verification.protected_paths_add:
                if p not in combined:
                    combined.append(p)
        return combined

    @classmethod
    def build_skill_instructions_prefix(cls, skills: list[SkillManifest]) -> str:
        """Formats active skill instructions into the stable prefix for prompts (§9.3, §20)."""
        if not skills:
            return ""

        sections: list[str] = ["# Active Domain Skills & Guidelines (§20)\n"]
        for s in skills:
            sections.append(f"## Skill: {s.name} (v{s.version})")
            if s.description:
                sections.append(f"_{s.description}_\n")
            if s.instructions:
                sections.append(s.instructions.strip())
            sections.append("")
        return "\n".join(sections).strip() + "\n\n"
