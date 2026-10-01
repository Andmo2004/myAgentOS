"""Build factual, non-sensitive context for Mya's conversation channel."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from myagentos.projects.models import Project
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectFact:
    name: str
    state: str
    tags: tuple[str, ...]
    languages: tuple[str, ...] = ()
    application_types: tuple[str, ...] = ()
    path: str | None = None


@dataclass(frozen=True)
class ConversationContext:
    active_project: ProjectFact | None
    projects: tuple[ProjectFact, ...]
    projects_available: bool
    project_count: int
    trashed_projects: tuple[ProjectFact, ...]
    trash_available: bool
    branch: str | None
    commit: str | None
    working_tree_status: str | None
    current_job_id: str | None

    def to_prompt(self) -> str:
        """Render verified session and project facts for an LLM system message."""
        lines = [
            "## Agentic OS factual context",
            "The following information comes from Agentic OS and is factual "
            "session/application context.",
            "Use it when relevant. Do not invent projects, tasks or repository facts.",
            "If requested information is not present here, say so clearly.",
            "",
            "## Active project",
        ]
        if self.active_project:
            lines.append(f"name: {self.active_project.name}")
            if self.active_project.state:
                lines.append(f"project_state: {self.active_project.state}")
        else:
            lines.append("name: unavailable")
        lines.append(f"branch: {self.branch or 'unavailable'}")
        lines.append(f"commit: {self.commit or 'unavailable'}")
        lines.append(f"status: {self.working_tree_status or 'unavailable'}")
        if self.active_project and self.active_project.tags:
            lines.append(f"tags: {', '.join(self.active_project.tags)}")
        if self.active_project and self.active_project.languages:
            lines.append(f"languages: {', '.join(self.active_project.languages)}")
        if self.active_project and self.active_project.application_types:
            lines.append(f"application_type: {', '.join(self.active_project.application_types)}")

        lines.extend(["", f"## Registered projects ({self.project_count})"])
        if not self.projects_available:
            lines.append("Project registry: unavailable")
        elif not self.projects:
            lines.append("No registered projects")
        else:
            for project in self.projects:
                tags = f"; tags: {', '.join(project.tags)}" if project.tags else ""
                path = f"; path: {project.path}" if project.path else ""
                lines.append(f"- name: {project.name}; state: {project.state}{tags}{path}")
            if self.project_count > len(self.projects):
                lines.append(
                    "Additional registered projects not shown: "
                    f"{self.project_count - len(self.projects)}"
                )

        if self.trash_available:
            lines.extend(["", f"## Trashed projects ({len(self.trashed_projects)})"])
            if self.trashed_projects:
                lines.extend(
                    f"- name: {project.name}; state: {project.state}"
                    for project in self.trashed_projects
                )
            else:
                lines.append("Trash is empty")

        lines.extend(["", "## Work tracking"])
        if self.current_job_id:
            lines.append(f"Current session job: {self.current_job_id}")
        else:
            lines.append("Current session job: none")
        lines.append("Open-job listing: unavailable")
        lines.append("Task backlog: unavailable")
        return "\n".join(lines)


class ConversationContextService:
    """Collect project facts through ProjectManagerService for Mya conversations."""

    def __init__(
        self,
        project_service: ProjectManagerService | None = None,
        max_projects: int = 20,
    ) -> None:
        self._project_service = project_service
        self.max_projects = max_projects

    @property
    def project_service(self) -> ProjectManagerService:
        if self._project_service is None:
            from myagentos.projects.service import ProjectManagerService as ProjectServiceFactory

            self._project_service = ProjectServiceFactory()
        return self._project_service

    def build_context(
        self,
        session: Session | None,
        user_input: str = "",
    ) -> ConversationContext:
        include_paths = any(
            token in user_input.lower() for token in ("path", "ruta", "ubicación", "ubicacion")
        )
        try:
            registered = self.project_service.list_projects()
        except Exception:
            logger.exception("Could not load registered projects for Mya conversation")
            registered = None

        trash_requested = any(
            term in user_input.lower() for term in ("papelera", "trash", "trashed")
        )
        trashed: list[Project] | None = None
        if trash_requested:
            try:
                trashed = self.project_service.list_trash()
            except Exception:
                logger.exception("Could not load project trash for Mya conversation")

        projects = tuple(
            self._project_fact(project, include_path=include_paths)
            for project in (registered or [])[: self.max_projects]
        )
        active_project = self._find_active_project(session, registered or [])
        session_profile = session.project_profile if session else None
        active_fact = (
            self._project_fact(active_project, include_path=include_paths)
            if active_project
            else None
        )
        if active_fact is None and session and session.repository:
            tags = (
                tuple(tag.label for tag in session_profile.visible_tags[:5])
                if session_profile
                else ()
            )
            active_fact = ProjectFact(
                name=session.repository,
                state="unknown",
                tags=tags,
                languages=tuple(session_profile.stack.languages) if session_profile else (),
                application_types=(
                    tuple(session_profile.architecture.application_type) if session_profile else ()
                ),
                path=str(session.repo_root) if include_paths else None,
            )

        return ConversationContext(
            active_project=active_fact,
            projects=projects,
            projects_available=registered is not None,
            project_count=len(registered or []),
            trashed_projects=tuple(
                self._project_fact(project, include_path=False)
                for project in (trashed or [])[: self.max_projects]
            ),
            trash_available=trash_requested and trashed is not None,
            branch=(session.branch if session else None)
            or (active_project.branch if active_project else None),
            commit=(session.commit_short if session else None)
            or (active_project.commit_short if active_project else None),
            working_tree_status=(
                ("clean" if session.working_tree_clean else "dirty") if session else None
            ),
            current_job_id=session.current_job_id if session else None,
        )

    @staticmethod
    def _project_fact(project: Project, include_path: bool) -> ProjectFact:
        profile = project.profile
        return ProjectFact(
            name=project.name,
            state=project.state.value,
            tags=tuple(tag.label for tag in project.visible_tags[:5]),
            languages=tuple(profile.stack.languages) if profile else (),
            application_types=tuple(profile.architecture.application_type) if profile else (),
            path=project.path if include_path else None,
        )

    @staticmethod
    def _find_active_project(session: Session | None, projects: list[Project]) -> Project | None:
        if not session:
            return None

        identifiers = {
            value.strip().lower() for value in (session.project_id, session.repository) if value
        }
        for project in projects:
            if (
                project.project_id.lower() in identifiers
                or project.name.strip().lower() in identifiers
            ):
                return project

        if session.repo_root:
            session_root = session.repo_root.resolve()
            for project in projects:
                try:
                    if Path(project.path).resolve() == session_root:
                        return project
                except OSError:
                    continue
        return None
