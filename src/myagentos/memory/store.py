"""Provider-independent, scope-filtered memory stores."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

import yaml  # type: ignore[import-untyped]

from myagentos.memory.models import MemoryRecord

logger = logging.getLogger(__name__)
MAX_PERSISTED_RECORDS_PER_SCOPE = 200


class MemoryStore(Protocol):
    def retrieve(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        session_id: str | None,
        query: str,
        limit: int = 8,
    ) -> list[MemoryRecord]: ...

    def append(self, record: MemoryRecord) -> str: ...


def _safe_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_from_json(raw: dict[str, object]) -> MemoryRecord:
    scope = raw.get("scope")
    if scope not in {"user", "project", "session"}:
        raise ValueError("Unknown memory scope")
    user_id_raw = raw.get("user_id")
    project_id_raw = raw.get("project_id")
    session_id_raw = raw.get("session_id")
    prov_raw = raw.get("provenance")
    prov_dict = prov_raw if isinstance(prov_raw, dict) else {}

    return MemoryRecord(
        memory_id=str(raw["memory_id"]),
        scope=scope,
        user_id=str(user_id_raw) if isinstance(user_id_raw, str) else None,
        project_id=str(project_id_raw) if isinstance(project_id_raw, str) else None,
        session_id=str(session_id_raw) if isinstance(session_id_raw, str) else None,
        namespace_id=str(raw["namespace_id"]),
        content=str(raw["content"]),
        status=str(raw["status"]),
        classification=str(raw["classification"]),
        trust=str(raw["trust"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        updated_at=datetime.fromisoformat(str(raw["updated_at"])),
        source=str(raw["source"]),
        content_hash=str(raw["content_hash"]),
        provenance={str(k): str(v) for k, v in prov_dict.items()},
    )


class JsonlMemoryStore:
    """Append-only persistence for user and session memory, never project memory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()

    def _path_for(self, scope: str, scope_id: str) -> Path:
        if scope not in {"user", "session"}:
            raise ValueError("JSONL memory storage is limited to user and session scopes")
        folder = "users" if scope == "user" else "sessions"
        return self.root / folder / f"{_safe_key(scope_id)}.jsonl"

    def append(self, record: MemoryRecord) -> str:
        if record.scope == "user":
            scope_id = record.user_id
        elif record.scope == "session":
            scope_id = record.session_id
        else:
            raise ValueError("Project memory writes are governed by Curator")
        if not scope_id:
            raise ValueError(f"{record.scope} memory requires its scope identifier")
        expected_namespace = f"/{'users' if record.scope == 'user' else 'sessions'}/{scope_id}"
        if record.namespace_id != expected_namespace:
            raise ValueError("Memory record namespace does not match its scope identifier")
        path = self._path_for(record.scope, scope_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        payload = json.dumps(
            {
                **record.__dict__,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        records = [*existing, payload][-MAX_PERSISTED_RECORDS_PER_SCOPE:]
        temporary_path = path.with_suffix(".jsonl.tmp")
        temporary_path.write_text("\n".join(records) + "\n", encoding="utf-8")
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        temporary_path.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return record.memory_id

    def retrieve(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        session_id: str | None,
        query: str,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for scope, scope_id in (("user", user_id), ("session", session_id)):
            if not scope_id:
                continue
            path = self._path_for(scope, scope_id)
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line:
                        continue
                    try:
                        record = _record_from_json(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        logger.warning("Skipping malformed memory record in %s", path)
                        continue
                    valid_hash = hashlib.sha256(record.content.encode("utf-8")).hexdigest()
                    if record.content_hash != valid_hash:
                        logger.warning("Skipping memory record with invalid content hash")
                        continue
                    if (
                        scope == "user"
                        and record.scope == "user"
                        and record.user_id == user_id
                        and record.namespace_id == f"/users/{user_id}"
                    ):
                        records.append(record)
                    elif (
                        scope == "session"
                        and record.scope == "session"
                        and record.session_id == session_id
                        and record.user_id == user_id
                        and record.namespace_id == f"/sessions/{session_id}"
                    ):
                        records.append(record)
            except OSError:
                logger.exception("Could not read memory store %s", path)
        latest_by_id = {record.memory_id: record for record in records}
        return _rank_records(list(latest_by_id.values()), query)[:limit]


class ProjectNoteMemoryStore:
    """Read verified Curator notes from canonical project-local memory."""

    _project_id_pattern = re.compile(r"[^a-zA-Z0-9_-]")
    _note_id_pattern = re.compile(r"[^a-zA-Z0-9_.-]")

    def __init__(self, project_roots: dict[str, Path] | None = None) -> None:
        self.project_roots = project_roots or {}

    def append(self, record: MemoryRecord) -> str:
        raise ValueError("Project memory writes must pass through Curator governance")

    def retrieve(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        session_id: str | None,
        query: str,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        if not project_id:
            return []
        root = self.project_roots.get(project_id)
        if root is None:
            return []
        canonical_dir = self.canonical_note_dir(root, project_id)
        self.migrate_legacy_notes(root, project_id)
        if not canonical_dir.is_dir():
            return []
        try:
            canonical_dir.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            logger.warning("Canonical project memory path escapes its project root")
            return []
        canonical_root = canonical_dir.resolve()
        records: list[MemoryRecord] = []
        for note_path in sorted(canonical_dir.glob("*.md"))[:500]:
            try:
                if note_path.stat().st_size > 16_384:
                    logger.warning("Skipping oversized project memory note")
                    continue
                note_path.resolve().relative_to(canonical_root)
                text = note_path.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            metadata, body = _parse_note(text)
            if metadata.get("project_id") != project_id or metadata.get("status") != "verified":
                continue
            classification = metadata.get("classification", "internal").lower()
            if classification not in {"public", "internal"}:
                continue
            note_id = metadata.get("note_id") or note_path.stem
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            generated = metadata.get("generated_at")
            try:
                timestamp = (
                    datetime.fromisoformat(generated)
                    if generated
                    else datetime.fromtimestamp(note_path.stat().st_mtime).astimezone()
                )
            except (ValueError, OSError):
                timestamp = datetime.fromtimestamp(0).astimezone()
            records.append(
                MemoryRecord(
                    memory_id=note_id,
                    scope="project",
                    user_id=user_id,
                    project_id=project_id,
                    session_id=None,
                    namespace_id=f".myagentos/memory/projects/{project_id}",
                    content=body,
                    status="verified",
                    classification=classification,
                    trust="untrusted",
                    created_at=timestamp,
                    updated_at=timestamp,
                    source="curator_project_note",
                    content_hash=content_hash,
                    provenance={
                        key: metadata[key]
                        for key in ("job_id", "base_commit", "model", "prompt_version")
                        if key in metadata
                    },
                )
            )
        return _rank_records(records, query)[:limit]

    @classmethod
    def canonical_note_dir(cls, project_root: Path, project_id: str) -> Path:
        safe_project_id = cls._project_id_pattern.sub("_", project_id)
        return project_root / ".myagentos" / "memory" / "projects" / safe_project_id / "notes"

    @classmethod
    def migrate_legacy_notes(cls, project_root: Path, project_id: str) -> int:
        """Copy verified legacy vault notes to canonical memory without deleting originals."""
        safe_project_id = cls._project_id_pattern.sub("_", project_id)
        legacy_root = project_root / ".myagentos" / "vault" / "projects" / safe_project_id
        if not legacy_root.is_dir():
            return 0
        project_root_resolved = project_root.resolve()
        try:
            legacy_root_resolved = legacy_root.resolve()
            legacy_root_resolved.relative_to(project_root_resolved)
        except (OSError, ValueError):
            logger.warning("Legacy project memory path escapes its project root")
            return 0
        canonical_dir = cls.canonical_note_dir(project_root, project_id)
        try:
            canonical_dir.parent.resolve().relative_to(project_root_resolved)
        except (OSError, ValueError):
            logger.warning("Canonical project memory path escapes its project root")
            return 0
        canonical_dir.mkdir(parents=True, exist_ok=True)
        try:
            canonical_dir.resolve().relative_to(project_root_resolved)
        except (OSError, ValueError):
            logger.warning("Canonical project memory path escapes its project root")
            return 0
        try:
            canonical_dir.chmod(0o700)
        except OSError:
            pass

        migrated = 0
        for source in sorted(legacy_root.rglob("*.md"))[:500]:
            try:
                if source.stat().st_size > 16_384:
                    continue
                source.resolve().relative_to(legacy_root_resolved)
                text = source.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            metadata, _ = _parse_note(text)
            if metadata.get("project_id") != project_id:
                continue
            if metadata.get("status") != "verified":
                continue
            if metadata.get("classification", "internal").lower() not in {"public", "internal"}:
                continue

            raw_note_id = metadata.get("note_id", source.stem)
            safe_note_id = cls._note_id_pattern.sub("_", raw_note_id)
            if not safe_note_id:
                continue
            target = canonical_dir / f"{safe_note_id}.md"
            try:
                with target.open("x", encoding="utf-8") as stream:
                    stream.write(text)
                target.chmod(0o600)
                migrated += 1
            except FileExistsError:
                continue
            except OSError:
                logger.exception("Could not migrate a verified legacy project note")
        if migrated:
            logger.info(
                "memory.project.migration.completed project_hash=%s migrated_count=%d",
                hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:12],
                migrated,
            )
        return migrated


def _parse_note(text: str) -> tuple[dict[str, str], str]:
    """Parse ProjectNote frontmatter with YAML and return its Markdown body."""
    if not text.startswith("---\n"):
        return {}, text
    _, rest = text.split("---\n", 1)
    if "\n---\n" not in rest:
        return {}, text
    frontmatter, body = rest.split("\n---\n", 1)
    try:
        document = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(document, dict):
        return {}, text
    metadata: dict[str, str] = {
        str(key): str(value)
        for key, value in document.items()
        if isinstance(value, (str, int, float))
    }
    provenance = document.get("provenance")
    if isinstance(provenance, dict):
        metadata.update(
            {str(key): str(value) for key, value in provenance.items() if value is not None}
        )
    return metadata, body.strip()


def _rank_records(records: list[MemoryRecord], query: str) -> list[MemoryRecord]:
    terms = {term for term in re.findall(r"[\w-]+", query.lower()) if len(term) > 2}
    return sorted(
        records,
        key=lambda record: (
            sum(term in record.content.lower() for term in terms),
            record.updated_at.timestamp(),
        ),
        reverse=True,
    )
