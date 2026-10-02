"""Protected credential store with POSIX 0700/0600 permissions and cross-process locking (§4, §5).

Follows specifications from
docs/new_features/agentic-os-feature-model-plan-connect-v2.md
(AO-MODEL-PLAN-CONNECT-01).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.credentials import derive_fingerprint
from myagentos.gateway.plan_connection import PlanConnectionProfile


class CredentialStoreError(MyAgentOSError):
    """Raised when credential storage or locking fails."""


class PlanCredentialSecret(BaseModel):
    """Private, secret credential record for a plan connection (§4, §5).

    MUST NEVER be serialized into logs, public profiles, jobs, or continuity exports.
    """

    model_config = ConfigDict(frozen=True)

    connection_id: str
    provider: str
    platform: str
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scope: list[str] = Field(default_factory=list)
    client_id_issued: str | None = None
    host_id: str | None = None
    account_id: str | None = None
    account_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Checks if the access token has expired (or will expire within buffer_seconds)."""
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        return (self.expires_at.timestamp() - now.timestamp()) < buffer_seconds

    def __repr__(self) -> str:
        acc_fp = derive_fingerprint(self.access_token)
        ref_fp = derive_fingerprint(self.refresh_token)
        return (
            f"PlanCredentialSecret(connection_id='{self.connection_id}', "
            f"provider='{self.provider}', platform='{self.platform}', "
            f"access_token='{acc_fp}', refresh_token='{ref_fp}', "
            f"expires_at={self.expires_at})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class CredentialStore:
    """Secure, isolated credential store outside the repository (§5).

    Guarantees:
    - POSIX directory mode 0700 and file mode 0600.
    - Atomic writes via temporary files and rename.
    - Cross-process serialization via file locking.
    """

    DEFAULT_STORE_DIR = Path.home() / ".myagentos"
    DEFAULT_STORE_FILE = DEFAULT_STORE_DIR / "credentials.json"
    DEFAULT_PROFILES_FILE = DEFAULT_STORE_DIR / "plan_connections.json"
    DEFAULT_LOCK_FILE = DEFAULT_STORE_DIR / "credentials.lock"

    def __init__(
        self,
        store_path: Path | None = None,
        lock_path: Path | None = None,
        profiles_path: Path | None = None,
    ) -> None:
        self.store_path = store_path or self.DEFAULT_STORE_FILE
        self.lock_path = lock_path or (
            self.store_path.parent / f"{self.store_path.stem}.lock"
        )
        self.profiles_path = profiles_path or (
            self.store_path.parent / "plan_connections.json"
        )
        self.store_dir = self.store_path.parent
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        self._lock_fd: int | None = None
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Creates the directory with mode 0700 and checks symlinks."""
        if self.store_dir.is_symlink():
            raise CredentialStoreError(
                f"Credential store directory '{self.store_dir}' cannot be a symlink"
            )
        if not self.store_dir.exists():
            self.store_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        else:
            try:
                os.chmod(self.store_dir, 0o700)
            except OSError:
                pass

    @contextmanager
    def lock(self, timeout_seconds: float = 10.0) -> Generator[None, None, None]:
        """Cross-process and re-entrant mutual exclusion lock for atomic store operations."""
        with self._thread_lock:
            self._ensure_storage_dir()
            if self._lock_depth > 0:
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                return

            try:
                import fcntl

                has_fcntl = True
            except ImportError:
                has_fcntl = False

            start_time = time.monotonic()
            lock_fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                locked = False
                while not locked:
                    if has_fcntl:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            locked = True
                        except (BlockingIOError, OSError):
                            pass
                    else:
                        locked = True

                    if not locked:
                        if (time.monotonic() - start_time) > timeout_seconds:
                            raise CredentialStoreError(
                                f"Timed out after {timeout_seconds}s waiting for "
                                "credential store lock"
                            )
                        time.sleep(0.05)

                self._lock_fd = lock_fd
                self._lock_depth = 1
                try:
                    yield
                finally:
                    self._lock_depth = 0
                    self._lock_fd = None
                    if has_fcntl:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        except OSError:
                            pass
                    try:
                        os.close(lock_fd)
                    except OSError:
                        pass
            except Exception:
                if self._lock_depth == 0 and lock_fd is not None:
                    try:
                        os.close(lock_fd)
                    except OSError:
                        pass
                raise

    def _read_raw_under_lock(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        if self.store_path.is_symlink():
            raise CredentialStoreError(
                f"Credential store file '{self.store_path}' cannot be a symlink"
            )
        try:
            content = self.store_path.read_text(encoding="utf-8")
            if not content.strip():
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            raise CredentialStoreError(f"Failed to read credentials store: {e}") from e

    def _write_raw_under_lock(self, data: dict[str, Any]) -> None:
        self._ensure_storage_dir()
        temp_file = self.store_dir / f".tmp_{os.getpid()}_{time.time_ns()}.json"
        try:
            # Write with 0600 mode
            fd = os.open(str(temp_file), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(str(temp_file), str(self.store_path))
            try:
                os.chmod(self.store_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise CredentialStoreError(f"Failed to save credential store atomically: {e}") from e

    def save_credential(self, secret: PlanCredentialSecret) -> None:
        """Saves or updates a credential secret atomically under cross-process lock."""
        with self.lock():
            data = self._read_raw_under_lock()
            data[secret.connection_id] = secret.model_dump(mode="json")
            self._write_raw_under_lock(data)

    def get_credential(self, connection_id: str) -> PlanCredentialSecret | None:
        """Retrieves a credential secret for connection_id under cross-process lock."""
        with self.lock():
            data = self._read_raw_under_lock()
            raw = data.get(connection_id)
            if not raw or not isinstance(raw, dict):
                return None
            try:
                return PlanCredentialSecret.model_validate(raw)
            except Exception as e:
                raise CredentialStoreError(
                    f"Corrupt credential record for connection '{connection_id}': {e}"
                ) from e

    def delete_credential(self, connection_id: str) -> bool:
        """Deletes a credential secret under cross-process lock."""
        with self.lock():
            data = self._read_raw_under_lock()
            if connection_id in data:
                del data[connection_id]
                self._write_raw_under_lock(data)
                return True
            return False

    def list_connection_ids(self) -> list[str]:
        """Lists all stored connection IDs."""
        with self.lock():
            data = self._read_raw_under_lock()
            return list(data.keys())

    def clear(self) -> None:
        """Purges all credentials from the store."""
        with self.lock():
            self._write_raw_under_lock({})

    def _read_profiles_under_lock(self) -> dict[str, Any]:
        if not self.profiles_path.exists():
            return {}
        if self.profiles_path.is_symlink():
            raise CredentialStoreError(
                f"Profiles file '{self.profiles_path}' cannot be a symlink"
            )
        try:
            content = self.profiles_path.read_text(encoding="utf-8")
            if not content.strip():
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            raise CredentialStoreError(f"Failed to read profiles store: {e}") from e

    def _write_profiles_under_lock(self, data: dict[str, Any]) -> None:
        self._ensure_storage_dir()
        temp_file = self.store_dir / f".tmp_profiles_{os.getpid()}_{time.time_ns()}.json"
        try:
            fd = os.open(str(temp_file), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(str(temp_file), str(self.profiles_path))
            try:
                os.chmod(self.profiles_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise CredentialStoreError(f"Failed to save profiles store atomically: {e}") from e

    def save_profile(self, profile: PlanConnectionProfile) -> None:
        """Saves or updates a public connection profile under cross-process lock."""
        with self.lock():
            data = self._read_profiles_under_lock()
            data[profile.connection_id] = profile.model_dump(mode="json")
            self._write_profiles_under_lock(data)

    def get_profile(self, connection_id: str) -> PlanConnectionProfile | None:
        """Retrieves a public connection profile under cross-process lock."""
        with self.lock():
            data = self._read_profiles_under_lock()
            raw = data.get(connection_id)
            if not raw or not isinstance(raw, dict):
                return None
            try:
                return PlanConnectionProfile.model_validate(raw)
            except Exception as e:
                raise CredentialStoreError(
                    f"Corrupt profile record for connection '{connection_id}': {e}"
                ) from e

    def list_profiles(self) -> list[PlanConnectionProfile]:
        """Lists all stored connection profiles."""
        with self.lock():
            data = self._read_profiles_under_lock()
            profiles: list[PlanConnectionProfile] = []
            for item in data.values():
                if isinstance(item, dict):
                    try:
                        profiles.append(PlanConnectionProfile.model_validate(item))
                    except Exception:
                        pass
            return profiles

    def delete_profile(self, connection_id: str) -> bool:
        """Deletes a connection profile under cross-process lock."""
        with self.lock():
            data = self._read_profiles_under_lock()
            if connection_id in data:
                del data[connection_id]
                self._write_profiles_under_lock(data)
                return True
            return False
