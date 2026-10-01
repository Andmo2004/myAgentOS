"""Path validation for Mya Home (§16).

Validates candidate paths to ensure they are writable, safe, and not system-protected.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_PROTECTED_UNIX_DIRECTORIES: tuple[str, ...] = (
    "/bin",
    "/sbin",
    "/usr",
    "/System",
    "/Library",
    "/etc",
    "/private/etc",
    "/dev",
    "/proc",
    "/sys",
    "/var/log",
    "/var/root",
    "/private/var/log",
    "/private/var/root",
)

_PROTECTED_WINDOWS_PREFIXES: tuple[str, ...] = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\system32",
)


@dataclass
class ValidationResult:
    """Result of validating a candidate Mya Home directory."""

    valid: bool
    error: str = ""
    resolved_path: Path | None = None


def is_protected_path(path: Path) -> bool:
    """Checks whether a path falls into a protected operating system directory."""
    resolved = path.resolve()
    resolved_str = str(resolved)

    if sys.platform == "win32":
        lowered = resolved_str.lower()
        if len(lowered) <= 3 and lowered.endswith(":\\"):
            return True
        for prefix in _PROTECTED_WINDOWS_PREFIXES:
            if lowered == prefix or lowered.startswith(prefix + "\\"):
                return True
        return False

    # Unix / macOS
    if resolved_str == "/":
        return True

    user_home = str(Path.home().resolve())
    if resolved_str == user_home or resolved_str.startswith(user_home + "/"):
        return False

    # Temporary directories are safe for tests and testing instances
    sys_temp = str(Path(tempfile.gettempdir()).resolve())
    if resolved_str == sys_temp or resolved_str.startswith(sys_temp + "/"):
        return False

    for tmp_prefix in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders"):
        if resolved_str == tmp_prefix or resolved_str.startswith(tmp_prefix + "/"):
            return False

    # Check protected directories
    for protected in _PROTECTED_UNIX_DIRECTORIES:
        if resolved_str == protected or resolved_str.startswith(protected + "/"):
            return True

    return False


def validate_mya_home(candidate: Path | str | None) -> ValidationResult:
    """Validates if a path can safely and correctly be used as Mya Home.

    Checks:
    1. Path string is not empty.
    2. Path can be parsed and expanded.
    3. Path does not point to a protected system location.
    4. Path does not point to a .git directory.
    5. Path (or its nearest existing parent) has write permissions.
    """
    if candidate is None:
        return ValidationResult(valid=False, error="Path cannot be empty.")

    raw = str(candidate).strip()
    if not raw:
        return ValidationResult(valid=False, error="Path cannot be empty.")

    try:
        path = Path(raw).expanduser().resolve()
    except Exception as exc:
        return ValidationResult(valid=False, error=f"Invalid path syntax: {exc}")

    # Check protected locations
    if is_protected_path(path):
        return ValidationResult(
            valid=False,
            error=f"'{path}' is a protected system directory and cannot be used as Mya Home.",
            resolved_path=path,
        )

    # Check .git directory collision
    if path.name == ".git" or (path / "HEAD").is_file() and (path / "objects").is_dir():
        return ValidationResult(
            valid=False,
            error="Mya Home cannot be located inside a .git repository metadata directory.",
            resolved_path=path,
        )

    # Check permissions & existing path type
    if path.exists():
        if not path.is_dir():
            return ValidationResult(
                valid=False,
                error=f"'{path}' already exists and is not a directory.",
                resolved_path=path,
            )
        if not os.access(path, os.W_OK | os.X_OK):
            return ValidationResult(
                valid=False,
                error=f"Permission denied: no write access to '{path}'.",
                resolved_path=path,
            )
    else:
        # Check permissions on lowest existing parent
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent

        if not parent.exists() or not os.access(parent, os.W_OK | os.X_OK):
            return ValidationResult(
                valid=False,
                error=f"Permission denied: cannot create directory in '{parent}'.",
                resolved_path=path,
            )

    return ValidationResult(valid=True, error="", resolved_path=path)
