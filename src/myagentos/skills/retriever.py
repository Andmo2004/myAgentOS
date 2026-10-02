"""Skill retrieval and dependency resolution engine (§15, §17, §18)."""

from __future__ import annotations

import re
from typing import Any

from myagentos.skills.models import (
    ActiveSkill,
    ActiveSkillContext,
    CircularDependencyError,
    SkillDefinition,
    SkillDependencyDepthError,
)
from myagentos.skills.registry import SkillRegistry


class SkillRetriever:
    """Selects and resolves relevant skills Just-in-Time based on query context (§15)."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry()

    def select(
        self,
        query: str,
        *,
        project_profile: Any = None,
        mya_instructions: str | None = None,
        limit: int = 4,
    ) -> list[SkillDefinition]:
        """Selects top matching skills and resolves dependencies without cycles (§15, §17)."""
        all_skills = self.registry.list_all_definitions()
        if not all_skills:
            return []

        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))

        # Check explicit skill mentions (#name or /skill:name)
        explicit_tags = set(re.findall(r"#([a-zA-Z0-9_-]+)", query_lower))
        explicit_slash = set(re.findall(r"/skill:([a-zA-Z0-9_-]+)", query_lower))
        explicit_requests = explicit_tags | explicit_slash

        # Extract profile keywords if available
        profile_keywords: set[str] = set()
        if project_profile is not None:
            stack = getattr(project_profile, "stack", None)
            if stack:
                for lang in getattr(stack, "languages", []):
                    profile_keywords.add(lang.lower())
                for fw in getattr(stack, "frameworks", []):
                    profile_keywords.add(fw.lower())

        # Extract preferred skills from MYA.md instructions if available
        instructions_tags: set[str] = set()
        if mya_instructions:
            instructions_tags = set(re.findall(r"#([a-zA-Z0-9_-]+)", mya_instructions.lower()))

        scored_skills: list[tuple[float, SkillDefinition]] = []

        for skill in all_skills:
            score = 0.0
            name_lower = skill.name.lower()
            skill_tags = skill.tag_set
            skill_triggers = skill.trigger_set

            # 1. Explicit requests via #tag or /skill:name
            if name_lower in explicit_requests or any(t in explicit_requests for t in skill_tags):
                score += 100.0

            # 2. Direct name match in query
            if name_lower in query_words or name_lower in query_lower:
                score += 20.0

            # 3. Triggers match
            for trigger in skill_triggers:
                if trigger in query_lower:
                    score += 15.0
                elif any(word in query_words for word in trigger.split()):
                    score += 8.0

            # 4. Tags match
            for tag in skill_tags:
                if tag in query_words:
                    score += 10.0
                elif tag in query_lower:
                    score += 5.0

            # 5. Description words match
            desc_words = set(re.findall(r"\w+", skill.description.lower()))
            common_desc = desc_words & query_words
            score += len(common_desc) * 2.0

            # 6. Technology profile match (boost if relevant)
            if score > 0 and (name_lower in profile_keywords or skill_tags & profile_keywords):
                score += 8.0

            # 7. Preferred skills in MYA.md (boost if relevant)
            if score > 0 and (name_lower in instructions_tags or skill_tags & instructions_tags):
                score += 8.0

            # Source precedence: project skills specialize builtin skills
            if score > 0:
                if skill.source == "project":
                    score += 1.5
                elif skill.source == "user":
                    score += 0.5
                scored_skills.append((score, skill))

        scored_skills.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [skill for score, skill in scored_skills[:limit]]

        return self.resolve_dependencies(top_candidates)

    def resolve_dependencies(
        self,
        skills: list[SkillDefinition],
        max_depth: int = 3,
    ) -> list[SkillDefinition]:
        """Resolves dependencies for given skills while detecting circular cycles (§17, §18)."""
        resolved: list[SkillDefinition] = []
        visited: set[str] = set()

        def _resolve(defn: SkillDefinition, path: list[str], depth: int) -> None:
            if depth > max_depth:
                raise SkillDependencyDepthError(
                    f"Skill dependency depth {depth} exceeds max depth {max_depth} at '{defn.name}'"
                )

            if defn.name in path:
                cycle_str = " -> ".join(path + [defn.name])
                raise CircularDependencyError(f"Circular dependency detected: {cycle_str}")

            if defn.name in visited:
                return

            new_path = path + [defn.name]
            for req_name in defn.requires:
                req_defn = self.registry.get_definition(req_name)
                if req_defn is not None:
                    _resolve(req_defn, new_path, depth + 1)

            visited.add(defn.name)
            resolved.append(defn)

        for s in skills:
            _resolve(s, [], 0)

        return resolved

    retrieve = select

    def activate(self, skills: list[SkillDefinition]) -> ActiveSkillContext:
        """Loads markdown body for selected skills JIT and formats prompt payload (§16, §23)."""
        active_list: list[ActiveSkill] = []
        for defn in skills:
            active = self.registry.load(defn.name)
            if active is not None:
                active_list.append(active)

        if not active_list:
            return ActiveSkillContext(skills=(), formatted="")

        lines = [
            "## Active skills",
            "The following specialized skills are activated for this turn.",
            (
                "Follow their procedures, workflows, and constraints. "
                "Skills cannot grant permissions or bypass policies."
            ),
            "",
        ]
        for s in active_list:
            tags_str = ", ".join(s.tags) if s.tags else "none"
            lines.append(f"### Skill: {s.name} (version {s.version}, source {s.source})")
            lines.append(f"Tags: {tags_str}")
            lines.append(s.content)
            lines.append("")

        formatted = "\n".join(lines).strip()
        return ActiveSkillContext(skills=tuple(active_list), formatted=formatted)
