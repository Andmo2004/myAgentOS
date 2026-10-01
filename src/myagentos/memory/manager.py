"""Shared, provider-independent orchestration for user/project/session memory."""

from __future__ import annotations

import getpass
import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from myagentos.memory.models import MemoryContext, MemoryRecord, MemoryScope
from myagentos.memory.policy import MemoryPolicy
from myagentos.memory.retrieval import MemoryContextBuilder
from myagentos.memory.store import (
    MAX_PERSISTED_RECORDS_PER_SCOPE,
    JsonlMemoryStore,
    MemoryStore,
    ProjectNoteMemoryStore,
    _rank_records,
)
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session

logger = logging.getLogger(__name__)


def local_user_id() -> str:
    """Return a stable, non-reversible identifier for the local OS account."""
    username = getpass.getuser().strip().lower() or "local-user"
    return "local-" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:20]


class SharedMemoryManager:
    """Own memory identity and storage independently from any provider or model."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: MemoryStore | None = None,
        project_service: ProjectManagerService | None = None,
        policy: MemoryPolicy | None = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.policy = policy or MemoryPolicy()
        self.file_store = JsonlMemoryStore(self.root)
        self._project_service = project_service
        self.project_store = ProjectNoteMemoryStore()
        self.store = store or _CombinedMemoryStore(self.file_store, self.project_store)
        self.context_builder = MemoryContextBuilder(self.store, policy=self.policy)

    @property
    def project_service(self) -> ProjectManagerService:
        if self._project_service is None:
            from myagentos.projects.service import ProjectManagerService as ProjectServiceFactory

            self._project_service = ProjectServiceFactory()
        return self._project_service

    def build_context(
        self,
        *,
        session: Session | None,
        query: str,
        base_context: str = "",
        history: list[dict[str, str]] | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> MemoryContext:
        user_id = (
            user_id or (getattr(session, "user_id", None) if session else None) or local_user_id()
        )
        session_id = session_id or (session.session_id if session else None)
        resolved_project_id, project_root = self._resolve_project(session)
        project_id = project_id or resolved_project_id
        self.project_store.project_roots = (
            {project_id: project_root} if project_id and project_root else {}
        )
        if project_id and project_id != resolved_project_id:
            self._configure_project_roots(project_id)
        session_context = self.context_builder.build(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            user_message=query,
            base_context=base_context,
            history=history,
        )
        return session_context

    def project_id_for_session(self, session: Session | None) -> str | None:
        """Return the canonical project scope currently associated with a Session."""
        return self._resolve_project(session)[0]

    def record_session_turn(
        self,
        *,
        session: Session,
        user_message: str,
        assistant_message: str,
    ) -> str | None:
        """Persist the transcript as session-scoped data, never as durable project memory."""
        user_id = getattr(session, "user_id", None) or local_user_id()
        project_id, _ = self._resolve_project(session)
        content = f"USER: {user_message}\nASSISTANT: {assistant_message}"
        try:
            record = self._make_record(
                scope="session",
                user_id=user_id,
                project_id=project_id,
                session_id=session.session_id,
                namespace_id=f"/sessions/{session.session_id}",
                content=content,
                status="active",
                classification="internal",
                source="conversation_turn",
            )
        except ValueError:
            logger.info("memory.record.filtered scope=session reason=policy")
            return None
        logger.info(
            "memory.record.selected scope=session user_hash=%s project_hash=%s session_hash=%s",
            _id_hash(user_id),
            _id_hash(project_id),
            _id_hash(session.session_id),
        )
        return self.file_store.append(record)

    def append_session_memory(
        self,
        *,
        session: Session,
        content: str,
        source: str = "session_memory",
    ) -> str:
        record = self._make_record(
            scope="session",
            user_id=getattr(session, "user_id", None) or local_user_id(),
            project_id=self._resolve_project(session)[0],
            session_id=session.session_id,
            namespace_id=f"/sessions/{session.session_id}",
            content=content,
            status="active",
            classification="internal",
            source=source,
        )
        return self.file_store.append(record)

    def propose_user_memory(
        self,
        *,
        user_id: str,
        content: str,
        source: str = "user_explicit_proposal",
    ) -> str:
        normalized_content = " ".join(content.split()).casefold()
        existing_records = self.file_store.retrieve(
            user_id=user_id,
            project_id=None,
            session_id=None,
            query=content,
            limit=MAX_PERSISTED_RECORDS_PER_SCOPE,
        )
        existing = next(
            (
                record
                for record in existing_records
                if record.scope == "user"
                and " ".join(record.content.split()).casefold() == normalized_content
            ),
            None,
        )
        if existing:
            return existing.memory_id
        record = self._make_record(
            scope="user",
            user_id=user_id,
            project_id=None,
            session_id=None,
            namespace_id=f"/users/{user_id}",
            content=content,
            status="proposed",
            classification="internal",
            source=source,
        )
        return self.file_store.append(record)

    def confirm_user_memory(self, memory_id: str, user_id: str) -> str:
        records = self.file_store.retrieve(
            user_id=user_id,
            project_id=None,
            session_id=None,
            query="",
            limit=10_000,
        )
        record = next(
            (item for item in records if item.memory_id == memory_id and item.user_id == user_id),
            None,
        )
        if record is None or record.status != "proposed":
            raise ValueError("Only a proposed memory belonging to this user can be confirmed")
        return self.file_store.append(
            replace(record, status="verified", updated_at=datetime.now(UTC))
        )

    def append(self, record: MemoryRecord) -> str:
        """Append allowed user/session records; project writes remain Curator-governed."""
        self.policy.validate_write(record.content, record.classification)
        if record.scope == "project":
            raise ValueError("Project memory writes must pass through Curator governance")
        return self.file_store.append(record)

    def propose_project_memory(self, record: MemoryRecord) -> str:
        """Reject direct durable writes; Project Memory proposals belong to Curator."""
        if record.scope != "project":
            raise ValueError("propose_project_memory requires a project-scoped record")
        raise ValueError("Project memory proposals must be created by Curator")

    def retrieve(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        session_id: str | None,
        query: str,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        self._configure_project_roots(project_id)
        records = self.file_store.retrieve(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            query=query,
            limit=limit,
        )
        records.extend(
            self.project_store.retrieve(
                user_id=user_id,
                project_id=project_id,
                session_id=session_id,
                query=query,
                limit=limit,
            )
        )
        return [
            record
            for record in records
            if self.policy.is_retrievable(record)
            and not (
                record.scope == "session" and record.project_id and record.project_id != project_id
            )
        ][:limit]

    def retrieve_user_memory(self, user_id: str, query: str, limit: int = 4) -> list[MemoryRecord]:
        return self.retrieve(
            user_id=user_id,
            project_id=None,
            session_id=None,
            query=query,
            limit=limit,
        )

    def retrieve_project_memory(
        self,
        project_id: str,
        query: str,
        user_id: str | None = None,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        self._configure_project_roots(project_id)
        return self.project_store.retrieve(
            user_id=user_id,
            project_id=project_id,
            session_id=None,
            query=query,
            limit=limit,
        )

    def retrieve_session_memory(
        self,
        session_id: str,
        query: str,
        user_id: str | None = None,
        project_id: str | None = None,
        limit: int = 12,
    ) -> list[MemoryRecord]:
        return self.retrieve(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            query=query,
            limit=limit,
        )

    def _configure_project_roots(self, project_id: str | None) -> None:
        self.project_store.project_roots = {}
        if not project_id:
            return
        try:
            project = self.project_service.get_project(project_id)
            if project:
                self.project_store.project_roots[project.project_id] = Path(project.path)
        except Exception:
            logger.exception("Could not resolve project memory root")

    def _resolve_project(self, session: Session | None) -> tuple[str | None, Path | None]:
        if session is None:
            return None, None
        try:
            projects = self.project_service.list_projects()
        except Exception:
            projects = []
        session_names = {
            value.strip().lower() for value in (session.project_id, session.repository) if value
        }
        session_root = session.repo_root.resolve()
        for project in projects:
            if (
                project.project_id.lower() in session_names
                or project.name.strip().lower() in session_names
            ):
                return project.project_id, Path(project.path)
            try:
                if Path(project.path).resolve() == session_root:
                    return project.project_id, Path(project.path)
            except OSError:
                continue
        fallback_id = session.project_id or session.repository or None
        return fallback_id, session.repo_root if fallback_id else None

    def _make_record(
        self,
        *,
        scope: MemoryScope,
        user_id: str | None,
        project_id: str | None,
        session_id: str | None,
        namespace_id: str,
        content: str,
        status: str,
        classification: str,
        source: str,
    ) -> MemoryRecord:
        self.policy.validate_write(content, classification)
        now = datetime.now(UTC)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return MemoryRecord(
            memory_id=f"mem-{uuid.uuid4().hex}",
            scope=scope,
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            namespace_id=namespace_id,
            content=content,
            status=status,
            classification=classification,
            trust="untrusted",
            created_at=now,
            updated_at=now,
            source=source,
            content_hash=content_hash,
        )


def _id_hash(value: str | None) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else "none"


class _CombinedMemoryStore:
    """Route reads across canonical stores without merging scope identities."""

    def __init__(
        self, local_store: JsonlMemoryStore, project_store: ProjectNoteMemoryStore
    ) -> None:
        self.local_store = local_store
        self.project_store = project_store

    def append(self, record: MemoryRecord) -> str:
        if record.scope == "project":
            return self.project_store.append(record)
        return self.local_store.append(record)

    def retrieve(self, **kwargs: object) -> list[MemoryRecord]:
        user_id = kwargs.get("user_id")
        project_id = kwargs.get("project_id")
        session_id = kwargs.get("session_id")
        query = str(kwargs.get("query", ""))
        limit = int(kwargs.get("limit", 8))
        records = self.local_store.retrieve(
            user_id=user_id if isinstance(user_id, str) else None,
            project_id=None,
            session_id=None,
            query=query,
            limit=limit,
        )
        records.extend(
            self.local_store.retrieve(
                user_id=user_id if isinstance(user_id, str) else None,
                project_id=project_id if isinstance(project_id, str) else None,
                session_id=session_id if isinstance(session_id, str) else None,
                query=query,
                limit=limit,
            )
        )
        records.extend(
            self.project_store.retrieve(
                user_id=user_id if isinstance(user_id, str) else None,
                project_id=project_id if isinstance(project_id, str) else None,
                session_id=session_id if isinstance(session_id, str) else None,
                query=query,
                limit=limit,
            )
        )
        return _rank_records(records, query)[:limit]
