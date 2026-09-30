"""In-memory registry and Just-in-Time skill matcher (§20)."""

from fnmatch import fnmatch
from pathlib import Path

from myagentos.skills.loader import SkillLoader
from myagentos.skills.models import SkillManifest


class SkillRegistry:
    """Registry maintaining active skills and matching triggers Just-in-Time (§20)."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillManifest] = {}

    def register(self, skill: SkillManifest) -> None:
        """Registers a skill manifest."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillManifest | None:
        """Fetches a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillManifest]:
        """Returns all registered skills."""
        return list(self._skills.values())

    def load_from_directory(self, skills_dir: Path) -> int:
        """Discovers and registers all skills from a directory root."""
        loaded = SkillLoader.load_skills_from_root(skills_dir)
        for s in loaded:
            self.register(s)
        return len(loaded)

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

            # Path pattern match
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

            # Extension match
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
