"""In-memory registry, multi-source discovery, and Just-in-Time skill matcher (§20, §10, §13)."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from myagentos.skills.loader import SkillLoader
from myagentos.skills.models import (
    ActiveSkill,
    SkillDefinition,
    SkillManifest,
    SkillSource,
)


class SkillRegistry:
    """Registry maintaining active skills, definitions, and matching triggers Just-in-Time (§20, §13)."""

    def __init__(self) -> None:
        # Legacy SkillManifest mapping
        self._skills: dict[str, SkillManifest] = {}
        # New modular SkillDefinition mappings (§13, §14)
        self._definitions: dict[str, SkillDefinition] = {}
        self._by_name: dict[str, SkillDefinition] = {}

    # ── Legacy Manifest API (AUD-027) ─────────────────────────────────

    def register(self, skill: SkillManifest) -> None:
        """Registers a skill manifest (legacy)."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillManifest | None:
        """Fetches a skill manifest by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillManifest]:
        """Returns all registered skill manifests."""
        return list(self._skills.values())

    def list_all(self) -> list[SkillManifest]:
        """Alias for list_skills() for compatibility."""
        return self.list_skills()

    def load_from_directory(self, skills_dir: Path) -> int:
        """Discovers and registers all skills from a directory root (legacy)."""
        loaded = SkillLoader.load_skills_from_root(skills_dir)
        for s in loaded:
            self.register(s)
        return len(loaded)

    # ── Modular Skill System API (§10, §13, §14, §16) ──────────────────

    def register_definition(self, definition: SkillDefinition) -> None:
        """Registers a lightweight SkillDefinition (§14)."""
        self._definitions[definition.id] = definition
        # Project skills specialize/override user or builtin skills with the same name (§11)
        existing = self._by_name.get(definition.name.lower())
        if existing is None:
            self._by_name[definition.name.lower()] = definition
        elif definition.source == "project":
            self._by_name[definition.name.lower()] = definition
        elif definition.source == "user" and existing.source == "builtin":
            self._by_name[definition.name.lower()] = definition

    def get_definition(self, name_or_id: str) -> SkillDefinition | None:
        """Look up a SkillDefinition by exact ID (e.g. 'project:api') or name (§13)."""
        key = name_or_id.strip().lower()
        if key in self._definitions:
            return self._definitions[key]
        return self._by_name.get(key)

    def list_all_definitions(self) -> list[SkillDefinition]:
        """Returns all discovered SkillDefinitions sorted by source and name."""
        source_order = {"project": 0, "user": 1, "builtin": 2}
        return sorted(
            self._definitions.values(),
            key=lambda d: (source_order.get(d.source, 9), d.name),
        )

    def load(self, name_or_id: str, loaded_because: str = "") -> ActiveSkill:
        """Loads and returns the full content body of a selected skill (§16)."""
        defn = self.get_definition(name_or_id)
        if defn is None:
            raise KeyError(f"Skill '{name_or_id}' not found in registry")
        return SkillLoader.load_active_skill(defn, loaded_because=loaded_because)

    def search(self, query: str) -> list[SkillDefinition]:
        """Searches definitions matching query in name, tags, or description (§13)."""
        q = query.strip().lower().lstrip("#")
        if not q:
            return self.list_all_definitions()
        results: list[SkillDefinition] = []
        for d in self.list_all_definitions():
            if (
                q in d.name.lower()
                or q in d.description.lower()
                or any(q in t for t in d.tag_set)
                or any(q in tr for tr in d.trigger_set)
            ):
                results.append(d)
        return results

    def discover(
        self,
        project_root: Path | None = None,
        user_skills_dir: Path | None = None,
        builtin_skills_dir: Path | None = None,
    ) -> list[SkillDefinition]:
        """Discovers skills across the 3 standard sources in hierarchical order (§10):

        1. Project Skills: <project-root>/skills/
        2. User Skills: ~/.myagentos/skills/
        3. Built-in Skills: src/myagentos/skills/builtin/ (or skills/)
        """
        discovered: list[SkillDefinition] = []

        # 1. Project Skills
        if project_root is not None:
            project_skills_path = project_root / "skills"
            if project_skills_path.is_dir():
                proj_skills = SkillLoader.discover_definitions(
                    project_skills_path, source="project"
                )
                for s in proj_skills:
                    self.register_definition(s)
                    discovered.append(s)

        # 2. User Skills
        user_dir = user_skills_dir or (Path.home() / ".myagentos" / "skills")
        if user_dir.is_dir():
            user_skills = SkillLoader.discover_definitions(user_dir, source="user")
            for s in user_skills:
                self.register_definition(s)
                discovered.append(s)

        # 3. Built-in Skills
        builtin_dir = builtin_skills_dir or (Path(__file__).parent / "builtin")
        if not builtin_dir.is_dir():
            builtin_dir = Path(__file__).parent
        if builtin_dir.is_dir():
            builtin_skills = SkillLoader.discover_definitions(builtin_dir, source="builtin")
            for s in builtin_skills:
                self.register_definition(s)
                discovered.append(s)

        return discovered

    # ── Legacy Trigger Matcher (§20) ───────────────────────────────────

    def match_skills(
        self,
        task_prompt: str,
        target_paths: list[str] | None = None,
        explicit_skills: list[str] | None = None,
    ) -> list[SkillManifest]:
        """Matches skills based on explicit triggers, target paths, extensions, and keywords."""
        matched: dict[str, SkillManifest] = {}
        prompt_lower = task_prompt.lower()
        active_targets = target_paths or []

        # 1. Explicit trigger (/skill <name> or /skill:<name> or explicit_skills)
        requested_names: set[str] = set(explicit_skills or [])
        words = task_prompt.split()
        for i, word in enumerate(words):
            if word.startswith("/skill:"):
                requested_names.add(word[len("/skill:") :].strip())
            elif word == "/skill" and i + 1 < len(words):
                requested_names.add(words[i + 1].strip())

        for name in requested_names:
            if name in self._skills:
                matched[name] = self._skills[name]

        # 2. Match by file path patterns and extensions
        for skill in self._skills.values():
            if skill.name in matched:
                continue

            path_match = False
            for target in active_targets:
                norm_target = target.strip("/")
                for pat in skill.match.paths:
                    norm_pat = pat.strip("/")
                    if fnmatch(norm_target, norm_pat) or fnmatch(target, pat):
                        path_match = True
                        break
                if path_match:
                    break

            if path_match:
                matched[skill.name] = skill
                continue

            ext_match = False
            for target in active_targets:
                ext = Path(target).suffix
                if ext and ext in skill.match.extensions:
                    ext_match = True
                    break
            if ext_match:
                matched[skill.name] = skill
                continue

            # 3. Match by prompt keywords
            keyword_match = False
            for kw in skill.match.keywords:
                if kw.lower() in prompt_lower:
                    keyword_match = True
                    break
            if keyword_match:
                matched[skill.name] = skill

        return list(matched.values())
