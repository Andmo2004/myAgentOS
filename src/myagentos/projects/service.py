"""Project Manager service coordinating creation, discovery, soft delete, and lifecycle.

Follows §5, §6, §7, §8, §13, §14, §15, §16, §18 of
docs/agentic-os-feature-project-manager-explorer.md.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from myagentos.categorization.service import ProjectCategorizationService
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.projects.models import (
    Project,
    ProjectFilter,
    ProjectState,
)
from myagentos.projects.registry import ProjectRegistry

logger = logging.getLogger(__name__)


def _detect_git_metadata(repo_path: Path) -> tuple[dict[str, str], str | None, str | None]:
    """Inspects Git remotes, current branch, and commit hash."""
    remotes: dict[str, str] = {}
    branch: str | None = None
    commit: str | None = None

    try:
        # Branch
        res_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_branch.returncode == 0 and res_branch.stdout.strip():
            branch = res_branch.stdout.strip()

        # Commit
        res_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_commit.returncode == 0 and res_commit.stdout.strip():
            commit = res_commit.stdout.strip()

        # Remotes
        res_remotes = subprocess.run(
            ["git", "remote", "-v"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_remotes.returncode == 0:
            for line in res_remotes.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    remotes[parts[0]] = parts[1]
    except Exception:
        pass

    return remotes, branch, commit


class ProjectManagerService:
    """Canonical service managing Project registry, lifecycle states, and Mya integration."""

    def __init__(
        self,
        registry: ProjectRegistry | None = None,
        categorizer: ProjectCategorizationService | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self.registry = registry or ProjectRegistry()
        self.categorizer = categorizer or ProjectCategorizationService(event_store=event_store)
        self.event_store = event_store

    def create_project(
        self,
        name: str,
        path: str | Path,
        template: str | None = None,
        initialize_git: bool = True,
    ) -> Project:
        """Creates a new project directory, registers it, and scans profile (§6)."""
        root = Path(path).resolve()
        root.mkdir(parents=True, exist_ok=True)

        existing = self.registry.get_by_path(root)
        if existing and existing.state != ProjectState.DELETED:
            raise ValueError(f"A project is already registered at path: {root}")

        if initialize_git and not (root / ".git").is_dir():
            try:
                subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
            except Exception:
                pass

        p_id = f"proj-{uuid.uuid4().hex[:12]}"
        remotes, branch, commit = _detect_git_metadata(root)

        # Initial Project Profile & Categorization
        profile = self.categorizer.scan_project(root, project_id=p_id, force=True)

        now = datetime.now(UTC)
        project = Project(
            project_id=p_id,
            name=name.strip(),
            description=f"Created via Project Manager (template: {template or 'empty'})",
            path=str(root),
            state=ProjectState.ACTIVE,
            remotes=remotes,
            branch=branch,
            commit=commit,
            commit_short=commit[:7] if commit else None,
            mya_enabled=True,
            mya_namespace_id=f"/vault/Proyectos/{p_id}",
            profile=profile,
            visible_tags=profile.visible_tags,
            created_at=now,
            updated_at=now,
        )

        self.registry.save_project(project)
        self._initialize_project_memory(
            project_root=root,
            project_name=name,
            project_id=p_id,
            profile=profile,
        )
        self._emit_event(
            project_id=p_id,
            event_name=EventName.PROJECT_CREATED,
            payload={"name": name, "path": str(root), "template": template},
        )
        return project

    def add_project(self, path: str | Path, name: str | None = None) -> Project:
        """Adds an existing repository to Agentic OS and Mya (§7)."""
        root = Path(path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {root}")

        existing = self.registry.get_by_path(root)
        if existing and existing.state != ProjectState.DELETED:
            if existing.state == ProjectState.TRASHED:
                # Prompt/Action to restore existing rather than duplicate
                raise ValueError(
                    f"Project '{existing.name}' is already registered at {root} (in Trash). "
                    "Use restore instead."
                )
            raise ValueError(f"Project '{existing.name}' is already registered at {root}.")

        proj_name = name.strip() if name else root.name
        p_id = f"proj-{uuid.uuid4().hex[:12]}"
        remotes, branch, commit = _detect_git_metadata(root)

        profile = self.categorizer.scan_project(root, project_id=p_id, force=True)

        now = datetime.now(UTC)
        project = Project(
            project_id=p_id,
            name=proj_name,
            description="Added existing repository",
            path=str(root),
            state=ProjectState.ACTIVE,
            remotes=remotes,
            branch=branch,
            commit=commit,
            commit_short=commit[:7] if commit else None,
            mya_enabled=True,
            mya_namespace_id=f"/vault/Proyectos/{p_id}",
            profile=profile,
            visible_tags=profile.visible_tags,
            created_at=now,
            updated_at=now,
        )

        self.registry.save_project(project)
        self._initialize_project_memory(
            project_root=root,
            project_name=proj_name,
            project_id=p_id,
            profile=profile,
        )
        self._emit_event(
            project_id=p_id,
            event_name=EventName.PROJECT_ADDED,
            payload={"name": proj_name, "path": str(root)},
        )
        return project

    @classmethod
    def ensure_project_mya_environment(
        cls,
        project_root: Path | str,
        project_name: str | None = None,
        project_id: str | None = None,
        profile: Any = None,
    ) -> dict[str, Any]:
        """Verify and create project-local files and directories required for Mya.

        Checks whether files and directories needed for Mya's operation already exist in the
        project folder (not in Mya's global home directory):
        - MYA.md (project instructions with rules, workflow, preferred skills)
        - .mya/skills/ (project-local skills directory)
        - .myagentos/memory/ (canonical project memory root)
        - .myagentos/vault/projects/<project_id> (project vault/notes)
        - .myagentos/memory/projects/<safe_project_id>/notes (canonical notes directory)

        If an item already exists, it is NOT overwritten.
        """
        root = Path(project_root).resolve()
        if not root.is_dir():
            return {"status": "error", "reason": f"Path is not a directory: {root}"}

        name = (project_name or root.name).strip()
        created_items: list[str] = []
        checked_items: list[str] = []

        # 1. Check & create MYA.md in project root
        mya_file = root / "MYA.md"
        checked_items.append("MYA.md")
        if not mya_file.is_file():
            # Derive preferred skills from detected profile if available
            preferred_skills: list[str] = ["#testing"]
            if profile:
                stack = getattr(profile, "stack", None)
                langs = (
                    [str(lang).lower() for lang in getattr(stack, "languages", [])] if stack else []
                )
                tags = [
                    getattr(t, "label", str(t)).lower()
                    for t in getattr(profile, "visible_tags", [])
                ]
                all_markers = set(langs + tags)
                if any("python" in m for m in all_markers):
                    preferred_skills.insert(0, "#python")
                if any(
                    m in ("javascript", "typescript", "node", "react", "vue") for m in all_markers
                ):
                    preferred_skills.insert(0, "#javascript")
                if any(
                    m in ("sql", "postgres", "sqlite", "database", "mysql") for m in all_markers
                ):
                    preferred_skills.append("#database")
                if any(m in ("security", "auth", "oauth") for m in all_markers):
                    preferred_skills.append("#cybersecurity")
            if "#python" not in preferred_skills and "#javascript" not in preferred_skills:
                preferred_skills.insert(0, "#python")

            skills_block = "\n".join(f"- {s}" for s in preferred_skills)
            starter_content = (
                "# MYA.md\n\n"
                f"## Project\n\n{name}\n\n"
                "## Rules\n\n"
                "- Keep changes minimal, safe, and well-tested.\n"
                "- Never bypass project policy or security constraints.\n"
                "- Review diffs before committing.\n\n"
                "## Workflow\n\n"
                "Inspect → Plan → Implement → Verify → Report.\n\n"
                f"## Preferred Skills\n\n{skills_block}\n"
            )
            try:
                mya_file.write_text(starter_content, encoding="utf-8")
                created_items.append("MYA.md")
            except OSError as exc:
                logger.warning("Could not create MYA.md in %s: %s", root, exc)

        # 2. Check & create project-local skills directory (.mya/skills)
        skills_dir = root / ".mya" / "skills"
        checked_items.append(".mya/skills")
        if not skills_dir.is_dir():
            try:
                skills_dir.mkdir(parents=True, exist_ok=True)
                created_items.append(".mya/skills")
                readme_path = skills_dir / "README.md"
                if not readme_path.exists():
                    readme_path.write_text(
                        "# Project Skills\n\n"
                        "Place project-specific skills here. Each skill should be in its own "
                        "directory with a `SKILL.md`.\n",
                        encoding="utf-8",
                    )
            except OSError as exc:
                logger.warning("Could not create skills dir in %s: %s", root, exc)

        # 3. Check & create canonical project memory directory (.myagentos/memory)
        memory_dir = root / ".myagentos" / "memory"
        checked_items.append(".myagentos/memory")
        if not memory_dir.is_dir():
            try:
                memory_dir.mkdir(parents=True, exist_ok=True)
                created_items.append(".myagentos/memory")
            except OSError as exc:
                logger.warning("Could not create memory dir in %s: %s", root, exc)
        try:
            memory_dir.chmod(0o700)
        except OSError:
            pass

        # 4. Check & create canonical notes/vault directories
        target_id = project_id
        if not target_id:
            try:
                reg_proj = ProjectRegistry().get_by_path(root)
                if reg_proj:
                    target_id = reg_proj.project_id
            except Exception:
                pass
        target_id = target_id or root.name
        safe_p_id = re.sub(r"[^a-zA-Z0-9_-]", "_", target_id)

        notes_dir = root / ".myagentos" / "memory" / "projects" / safe_p_id / "notes"
        checked_items.append(f".myagentos/memory/projects/{safe_p_id}/notes")
        if not notes_dir.is_dir():
            try:
                notes_dir.mkdir(parents=True, exist_ok=True)
                created_items.append(f".myagentos/memory/projects/{safe_p_id}/notes")
            except OSError as exc:
                logger.warning("Could not create notes dir in %s: %s", root, exc)

        vault_dir = root / ".myagentos" / "vault" / "projects" / safe_p_id
        checked_items.append(f".myagentos/vault/projects/{safe_p_id}")
        if not vault_dir.is_dir():
            try:
                vault_dir.mkdir(parents=True, exist_ok=True)
                created_items.append(f".myagentos/vault/projects/{safe_p_id}")
            except OSError as exc:
                logger.warning("Could not create vault dir in %s: %s", root, exc)

        # 5. Check & update .gitignore in project root
        gitignore_res = cls.ensure_gitignore_entries(root)
        checked_items.append(".gitignore")
        if gitignore_res.get("added"):
            created_items.append(f".gitignore ({', '.join(gitignore_res['added'])})")

        return {
            "status": "ok",
            "project_root": str(root),
            "checked": checked_items,
            "created": created_items,
            "gitignore": gitignore_res,
        }

    @classmethod
    def ensure_gitignore_entries(
        cls,
        project_root: Path | str,
        entries: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ensure that Mya project directories and files are ignored in .gitignore."""
        root = Path(project_root).resolve()
        if not root.is_dir():
            return {"status": "error", "reason": f"Path is not a directory: {root}"}

        target_entries = entries or [
            ".myagentos/",
            ".mya/",
            "MYA.md",
            "MYA.md.bak",
        ]

        gitignore_path = root / ".gitignore"
        patterns: list[str] = []

        if gitignore_path.is_file():
            try:
                content = gitignore_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        patterns.append(stripped)
            except OSError as exc:
                logger.warning("Could not read .gitignore in %s: %s", root, exc)

        missing_entries: list[str] = []
        for entry in target_entries:
            entry_clean = entry.rstrip("/")
            is_covered = False
            for pat in patterns:
                pat_clean = pat.rstrip("/")
                if pat_clean.lower() == entry_clean.lower():
                    is_covered = True
                    break
                if fnmatch.fnmatch(entry.lower(), pat.lower()) or fnmatch.fnmatch(
                    entry_clean.lower(), pat_clean.lower()
                ):
                    is_covered = True
                    break
            if not is_covered:
                missing_entries.append(entry)

        if not missing_entries:
            return {
                "status": "ok",
                "added": [],
                "already_present": target_entries,
                "gitignore_path": str(gitignore_path),
            }

        try:
            append_lines: list[str] = []
            if gitignore_path.is_file() and gitignore_path.stat().st_size > 0:
                raw = gitignore_path.read_text(encoding="utf-8")
                if not raw.endswith("\n\n"):
                    if not raw.endswith("\n"):
                        append_lines.append("")
                    append_lines.append("")

            append_lines.append("# Mya / Agentic OS")
            append_lines.extend(missing_entries)
            append_lines.append("")

            with gitignore_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(append_lines))

            return {
                "status": "ok",
                "added": missing_entries,
                "already_present": [e for e in target_entries if e not in missing_entries],
                "gitignore_path": str(gitignore_path),
            }
        except OSError as exc:
            logger.warning("Could not update .gitignore in %s: %s", root, exc)
            return {"status": "error", "reason": str(exc)}

    @classmethod
    def reset_project_mya_environment(
        cls,
        project_root: Path | str,
        project_name: str | None = None,
        project_id: str | None = None,
        profile: Any = None,
    ) -> dict[str, Any]:
        """Reset and recreate project-local files and directories required for Mya.

        If MYA.md exists, creates a backup (MYA.md.bak) before regenerating a clean starter MYA.md.
        Ensures .mya/skills/ (and README.md), .myagentos/memory/, and vault/notes directories exist.
        """
        root = Path(project_root).resolve()
        if not root.is_dir():
            return {"status": "error", "reason": f"Path is not a directory: {root}"}

        mya_file = root / "MYA.md"
        backup_created: str | None = None
        if mya_file.is_file():
            backup_path = root / "MYA.md.bak"
            try:
                backup_path.write_bytes(mya_file.read_bytes())
                backup_created = backup_path.name
                mya_file.unlink()
            except OSError as exc:
                logger.warning("Could not backup existing MYA.md in %s: %s", root, exc)

        result = cls.ensure_project_mya_environment(
            project_root=root,
            project_name=project_name,
            project_id=project_id,
            profile=profile,
        )
        if backup_created:
            result["backup"] = backup_created
            result["reset"] = True
        return result

    @classmethod
    def _initialize_project_memory(
        cls,
        project_root: Path,
        project_name: str | None = None,
        project_id: str | None = None,
        profile: Any = None,
    ) -> Path:
        """Create the canonical, project-local memory and Mya files without touching legacy data."""
        cls.ensure_project_mya_environment(
            project_root=project_root,
            project_name=project_name,
            project_id=project_id,
            profile=profile,
        )
        return project_root / ".myagentos" / "memory"

    def clone_repository(
        self,
        url: str,
        destination: str | Path,
        name: str | None = None,
    ) -> Project:
        """Clones a remote git repository and registers it as untrusted project (§8)."""
        dest = Path(destination).resolve()
        if dest.exists() and any(dest.iterdir()):
            raise ValueError(f"Destination directory already exists and is not empty: {dest}")

        dest.parent.mkdir(parents=True, exist_ok=True)

        self._emit_event(
            project_id=name or dest.name,
            event_name=EventName.PROJECT_CLONE_STARTED,
            payload={"url": url, "destination": str(dest)},
        )

        try:
            res = subprocess.run(
                ["git", "clone", url, str(dest)],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"Git clone failed: {res.stderr.strip()}")
        except Exception as exc:
            logger.error("Clone execution error: %s", exc)
            raise

        project = self.add_project(path=dest, name=name)
        self._emit_event(
            project_id=project.project_id,
            event_name=EventName.PROJECT_CLONED,
            payload={"url": url, "path": str(dest)},
        )
        return project

    def get_project(self, project_id_or_name: str) -> Project | None:
        """Looks up a project by its stable identifier or name."""
        proj = self.registry.get_project(project_id_or_name)
        if proj:
            return proj
        return self.registry.get_by_name(project_id_or_name)

    def get_project_by_name(self, name: str) -> Project | None:
        """Looks up a project specifically by name."""
        return self.registry.get_by_name(name)

    def get_project_by_path(self, path: str | Path) -> Project | None:
        """Looks up a project by canonical filesystem path."""
        return self.registry.get_by_path(path)

    def list_projects(
        self,
        filter_criteria: ProjectFilter | None = None,
        include_trashed: bool = False,
    ) -> list[Project]:
        """Lists projects matching criteria, hiding trashed/deleted by default (§5, §22)."""
        all_projs = self.registry.list_projects()
        results: list[Project] = []

        for p in all_projs:
            if not include_trashed and p.state in (ProjectState.TRASHED, ProjectState.DELETED):
                continue

            # Update DISCONNECTED state dynamically if path missing on disk
            if p.state == ProjectState.ACTIVE and not Path(p.path).is_dir():
                p = self._update_project_state(p, ProjectState.DISCONNECTED)

            if filter_criteria:
                if filter_criteria.state and p.state != filter_criteria.state:
                    continue

                if filter_criteria.query:
                    q = filter_criteria.query.lower()
                    name_match = q in p.name.lower()
                    path_match = q in p.path.lower()
                    tag_match = any(q in t.label.lower() for t in p.visible_tags)
                    if not (name_match or path_match or tag_match):
                        continue

                if filter_criteria.tag:
                    target_tag = filter_criteria.tag.lower()
                    if not any(t.label.lower() == target_tag for t in p.visible_tags):
                        continue

                if filter_criteria.language and p.profile:
                    target_lang = filter_criteria.language.lower()
                    if not any(lang.lower() == target_lang for lang in p.profile.stack.languages):
                        continue

            results.append(p)

        results.sort(key=lambda x: x.name.lower())
        return results

    def list_trash(self) -> list[Project]:
        """Lists soft-deleted projects waiting in the Trash (§14)."""
        all_projs = self.registry.list_projects()
        trash = [p for p in all_projs if p.state == ProjectState.TRASHED]
        trash.sort(key=lambda x: x.trashed_at or x.updated_at, reverse=True)
        return trash

    def move_to_trash(self, project_id: str, reason: str = "user_action") -> Project:
        """Soft delete: moves project to Trash without touching repository files (§13)."""
        project = self.registry.get_project(project_id)
        if not project:
            raise KeyError(f"Project not found: {project_id}")

        if project.state == ProjectState.TRASHED:
            return project

        now = datetime.now(UTC)
        updated = Project(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            path=project.path,
            state=ProjectState.TRASHED,
            remotes=project.remotes,
            branch=project.branch,
            commit=project.commit,
            commit_short=project.commit_short,
            mya_enabled=False,
            mya_namespace_id=project.mya_namespace_id,
            profile=project.profile,
            visible_tags=project.visible_tags,
            created_at=project.created_at,
            updated_at=now,
            trashed_at=now,
        )

        self.registry.save_project(updated)
        self._emit_event(
            project_id=project.project_id,
            event_name=EventName.PROJECT_MOVED_TO_TRASH,
            payload={
                "previous_state": project.state.value,
                "new_state": ProjectState.TRASHED.value,
                "reason": reason,
                "repository_untouched": True,
            },
        )
        return updated

    def restore_project(self, project_id: str) -> Project:
        """Restores a soft-deleted project from Trash back to ACTIVE (§15)."""
        project = self.registry.get_project(project_id)
        if not project:
            raise KeyError(f"Project not found: {project_id}")

        if project.state != ProjectState.TRASHED:
            return project

        now = datetime.now(UTC)
        target_state = (
            ProjectState.ACTIVE if Path(project.path).is_dir() else ProjectState.DISCONNECTED
        )

        updated = Project(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            path=project.path,
            state=target_state,
            remotes=project.remotes,
            branch=project.branch,
            commit=project.commit,
            commit_short=project.commit_short,
            mya_enabled=True,
            mya_namespace_id=project.mya_namespace_id,
            profile=project.profile,
            visible_tags=project.visible_tags,
            created_at=project.created_at,
            updated_at=now,
            trashed_at=None,
        )

        self.registry.save_project(updated)
        self._emit_event(
            project_id=project.project_id,
            event_name=EventName.PROJECT_RESTORED,
            payload={"previous_state": ProjectState.TRASHED.value, "new_state": target_state.value},
        )
        return updated

    def delete_permanently(self, project_id: str, confirm: bool = False) -> bool:
        """Permanently deletes Agentic OS registration and Mya namespace (§16).

        INVARIANT: Repository files on disk are NEVER deleted.
        """
        if not confirm:
            raise ValueError(
                "Explicit confirmation is required to permanently delete a project registration. "
                "Provide confirm=True or use --confirm in CLI."
            )

        project = self.registry.get_project(project_id)
        if not project:
            raise KeyError(f"Project not found: {project_id}")

        self._emit_event(
            project_id=project.project_id,
            event_name=EventName.PROJECT_PERMANENT_DELETE_REQUESTED,
            payload={"confirmed": True},
        )

        self.registry.remove_project(project_id)

        self._emit_event(
            project_id=project_id,
            event_name=EventName.PROJECT_PERMANENTLY_DELETED,
            payload={
                "previous_state": project.state.value,
                "confirmation": "explicit",
                "repository_deleted": False,
                "memory_deleted": True,
            },
        )
        return True

    def reconnect_repository(self, project_id: str, new_path: str | Path) -> Project:
        """Updates repository path for a disconnected project (§20)."""
        project = self.registry.get_project(project_id)
        if not project:
            raise KeyError(f"Project not found: {project_id}")

        root = Path(new_path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"New repository path is not a directory: {root}")

        remotes, branch, commit = _detect_git_metadata(root)
        profile = self.categorizer.scan_project(root, project_id=project.project_id, force=True)

        now = datetime.now(UTC)
        updated = Project(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            path=str(root),
            state=ProjectState.ACTIVE,
            remotes=remotes,
            branch=branch,
            commit=commit,
            commit_short=commit[:7] if commit else None,
            mya_enabled=True,
            mya_namespace_id=project.mya_namespace_id,
            profile=profile,
            visible_tags=profile.visible_tags,
            created_at=project.created_at,
            updated_at=now,
            trashed_at=None,
        )

        self.registry.save_project(updated)
        self._emit_event(
            project_id=project.project_id,
            event_name=EventName.PROJECT_ACTIVATED,
            payload={"new_path": str(root)},
        )
        return updated

    def _update_project_state(self, project: Project, new_state: ProjectState) -> Project:
        updated = Project(
            project_id=project.project_id,
            name=project.name,
            description=project.description,
            path=project.path,
            state=new_state,
            remotes=project.remotes,
            branch=project.branch,
            commit=project.commit,
            commit_short=project.commit_short,
            mya_enabled=project.mya_enabled,
            mya_namespace_id=project.mya_namespace_id,
            profile=project.profile,
            visible_tags=project.visible_tags,
            created_at=project.created_at,
            updated_at=datetime.now(UTC),
            trashed_at=project.trashed_at,
            deleted_at=project.deleted_at,
        )
        self.registry.save_project(updated)
        return updated

    def _emit_event(
        self,
        project_id: str,
        event_name: EventName,
        payload: dict[str, Any],
    ) -> None:
        if not self.event_store:
            return
        try:
            self.event_store.append(
                job_id=project_id,
                actor=EventActor.PROJECT_MANAGER,
                state="PROJECT_SNAPSHOT",
                event_name=event_name,
                payload=payload,
            )
        except Exception as exc:
            logger.debug("EventStore append error in ProjectManagerService: %s", exc)
