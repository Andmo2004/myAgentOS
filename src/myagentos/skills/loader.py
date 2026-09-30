"""Loader and filesystem scanner for Just-in-Time Skills (§20)."""

import json
from pathlib import Path
from typing import Any

from myagentos.core.errors import MyAgentOSError
from myagentos.core.models.risk import RiskLevel
from myagentos.skills.models import (
    SkillManifest,
    SkillMatchCriteria,
    SkillPermissions,
    SkillVerification,
)


class SkillLoadError(MyAgentOSError):
    """Raised when loading or validating a skill manifest fails."""


class SkillLoader:
    """Discovers, parses, and validates skills from standard directory layouts (§20)."""

    @classmethod
    def load_skill_from_dir(cls, skill_dir: Path) -> SkillManifest:
        """Loads a single skill from directory containing metadata and instructions."""
        if not skill_dir.is_dir():
            raise SkillLoadError(f"Skill path is not a directory: {skill_dir}")

        meta_data: dict[str, Any] = {}
        meta_yaml = skill_dir / "metadata.yaml"
        meta_yml = skill_dir / "metadata.yml"
        meta_json = skill_dir / "metadata.json"
        skill_json = skill_dir / "skill.json"

        if meta_yaml.is_file():
            meta_data = cls._parse_yaml_or_json(meta_yaml)
        elif meta_yml.is_file():
            meta_data = cls._parse_yaml_or_json(meta_yml)
        elif meta_json.is_file():
            meta_data = cls._parse_yaml_or_json(meta_json)
        elif skill_json.is_file():
            meta_data = cls._parse_yaml_or_json(skill_json)
        else:
            raise SkillLoadError(f"No metadata file found in {skill_dir}")

        instructions_file = skill_dir / "instructions.md"
        instructions = (
            instructions_file.read_text(encoding="utf-8") if instructions_file.is_file() else ""
        )

        return cls.create_manifest(meta_data, instructions=instructions, skill_dir=skill_dir)

    @classmethod
    def load_skills_from_root(cls, skills_root: Path) -> list[SkillManifest]:
        """Discovers all valid skills located under a skills directory."""
        if not skills_root.is_dir():
            return []

        skills: list[SkillManifest] = []
        for child in sorted(skills_root.iterdir()):
            if child.is_dir() and not child.name.startswith((".", "_")):
                try:
                    skill = cls.load_skill_from_dir(child)
                    skills.append(skill)
                except Exception:
                    continue
        return skills

    @classmethod
    def create_manifest(
        cls,
        data: dict[str, Any],
        instructions: str = "",
        skill_dir: Path | None = None,
    ) -> SkillManifest:
        """Builds and hashes a SkillManifest from dictionary data."""
        name = data.get("name")
        if not name or not isinstance(name, str):
            raise SkillLoadError("Skill manifest must include a valid 'name'")

        version = str(data.get("version", "1.0.0"))
        source = str(data.get("source", "local"))
        description = str(data.get("description", ""))

        risk_val = data.get("min_risk_level", "LOW")
        min_risk = (
            RiskLevel(risk_val.upper())
            if isinstance(risk_val, str) and risk_val.upper() in RiskLevel.__members__
            else RiskLevel.LOW
        )

        match_data = data.get("match", {})
        match = SkillMatchCriteria(
            keywords=match_data.get("keywords", []),
            paths=match_data.get("paths", []),
            extensions=match_data.get("extensions", []),
        )

        perms_data = data.get("permissions_requested", {})
        perms = SkillPermissions(
            read=perms_data.get("read", []),
            write=perms_data.get("write", []),
            execute=perms_data.get("execute", []),
        )

        verif_data = data.get("verification", {})
        verification = SkillVerification(
            protected_paths_add=verif_data.get("protected_paths_add", []),
            commands=verif_data.get("commands", []),
        )

        temp_manifest = SkillManifest(
            name=name,
            version=version,
            source=source,
            content_hash="",
            signature=data.get("signature"),
            description=description,
            min_risk_level=min_risk,
            preferred_worker_capabilities=data.get("preferred_worker_capabilities", []),
            match=match,
            permissions_requested=perms,
            network_code_execution=data.get("network_code_execution", "none"),
            verification=verification,
            instructions=instructions or data.get("instructions", ""),
            skill_dir=skill_dir,
        )

        content_hash = data.get("content_hash") or temp_manifest.compute_content_hash()
        return temp_manifest.model_copy(update={"content_hash": content_hash})

    @classmethod
    def _parse_yaml_or_json(cls, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")

        # 1. Try PyYAML if installed
        try:
            import yaml  # type: ignore[import-untyped]

            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

        # 2. Try JSON parse
        try:
            loaded_json = json.loads(text)
            if isinstance(loaded_json, dict):
                return loaded_json
        except Exception:
            pass

        # 3. Built-in lightweight YAML parser fallback
        try:
            parsed_yaml = cls._parse_simple_yaml(text)
            if isinstance(parsed_yaml, dict) and parsed_yaml:
                return parsed_yaml
        except Exception as e:
            raise SkillLoadError(f"Failed to parse skill metadata file {path}: {e}") from e

        if path.suffix.lower() in (".yaml", ".yml"):
            parsed_yaml = cls._parse_simple_yaml(text)
            if isinstance(parsed_yaml, dict):
                return parsed_yaml

        raise SkillLoadError(f"Failed to parse skill metadata file {path}: invalid format")

    @classmethod
    def _parse_simple_yaml(cls, text: str) -> dict[str, Any]:
        """Lightweight fallback YAML parser supporting dictionaries, lists, and scalars."""
        raw_lines = text.splitlines()
        cleaned_lines: list[tuple[int, str]] = []
        for line in raw_lines:
            s = line.rstrip()
            if not s.strip() or s.strip().startswith("#"):
                continue
            indent = len(s) - len(s.lstrip())
            content = s.strip()
            if "#" in content and not (
                content.startswith(('"', "'")) and content.endswith(('"', "'"))
            ):
                parts = content.split("#", 1)
                content = parts[0].rstrip()
            cleaned_lines.append((indent, content))

        if not cleaned_lines:
            return {}

        def _clean_scalar(val: str) -> Any:
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                return val[1:-1]
            if val.lower() == "true":
                return True
            if val.lower() == "false":
                return False
            if val.lower() in ("null", "~"):
                return None
            try:
                if "." in val:
                    return float(val)
                return int(val)
            except ValueError:
                return val

        def parse_block(index: int, base_indent: int) -> tuple[Any, int]:
            if index >= len(cleaned_lines):
                return {}, index

            _, first_content = cleaned_lines[index]
            if first_content.startswith("- "):
                result_list: list[Any] = []
                curr = index
                while curr < len(cleaned_lines):
                    ind, cont = cleaned_lines[curr]
                    if ind < base_indent:
                        break
                    if ind == base_indent and cont.startswith("- "):
                        val_scalar = cont[2:].strip()
                        result_list.append(_clean_scalar(val_scalar))
                        curr += 1
                    elif ind > base_indent:
                        curr += 1
                    else:
                        break
                return result_list, curr
            else:
                result_dict: dict[str, Any] = {}
                curr = index
                while curr < len(cleaned_lines):
                    ind, cont = cleaned_lines[curr]
                    if ind < base_indent:
                        break
                    if ind == base_indent and ":" in cont:
                        k, _, v = cont.partition(":")
                        key = k.strip().strip("'\"")
                        val_str = v.strip()
                        if val_str:
                            result_dict[key] = _clean_scalar(val_str)
                            curr += 1
                        else:
                            if curr + 1 < len(cleaned_lines):
                                next_indent, _ = cleaned_lines[curr + 1]
                                if next_indent > ind:
                                    sub_val, next_curr = parse_block(curr + 1, next_indent)
                                    result_dict[key] = sub_val
                                    curr = next_curr
                                else:
                                    result_dict[key] = None
                                    curr += 1
                            else:
                                result_dict[key] = None
                                curr += 1
                    else:
                        curr += 1
                return result_dict, curr

        res, _ = parse_block(0, cleaned_lines[0][0])
        return res if isinstance(res, dict) else {}
