"""Path canonicalization, namespace verification, and secret detection.

Follows §9.5, §9.6, and §18.
"""

import os
import re
from pathlib import Path

from myagentos.core.errors import AgenticOSError
from myagentos.core.models.data_policy import DataClassification


class PathSecurityError(AgenticOSError):
    """Raised when a path escapes authorized namespace or violates traversal rules (§9.6)."""


PathSecurityViolation = PathSecurityError


SECRET_FILE_PATTERNS = [
    re.compile(r"^\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"^id_rsa.*$", re.IGNORECASE),
    re.compile(r"^.*\.pem$", re.IGNORECASE),
    re.compile(r"^.*\.key$", re.IGNORECASE),
    re.compile(r"^.*credentials.*$", re.IGNORECASE),
    re.compile(r"^.*secret.*$", re.IGNORECASE),
]

SECRET_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(r"ghp_[0-9a-zA-Z]{36}"),  # GitHub PAT
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API key
    re.compile(r"sk-(?:live-|proj-)?[a-zA-Z0-9_-]{20,}"),  # OpenAI-like API key
]


def canonicalize_and_verify_path(path_str: str, root_dir: Path) -> Path:
    """Implements §9.6: resolve -> canonicalize -> verify namespace -> allow.

    Rejects escapes through '..', absolute paths outside root, and symlinks pointing out.
    """
    if not path_str or not path_str.strip():
        raise PathSecurityError("Path string cannot be empty")

    root_canonical = root_dir.resolve()

    # Pre-check for raw traversal tricks
    normalized_input = os.path.normpath(path_str)
    if normalized_input.startswith("..") or "/../" in path_str or "\\..\\" in path_str:
        raise PathSecurityViolation(f"Path traversal detected in '{path_str}' (§9.6)")

    # Treat path as relative to root_canonical
    candidate = (root_canonical / path_str).resolve()

    # Verify namespace: candidate must be strictly within root_canonical
    try:
        candidate.relative_to(root_canonical)
    except ValueError as e:
        raise PathSecurityViolation(
            f"Path '{path_str}' escapes authorized workspace root '{root_canonical}' (§9.6)"
        ) from e

    # Also verify that if candidate is a symlink, its target stays inside root
    if candidate.is_symlink():
        target = candidate.resolve()
        try:
            target.relative_to(root_canonical)
        except ValueError as e:
            raise PathSecurityViolation(
                f"Symlink '{path_str}' points to external location '{target}' (§9.6)"
            ) from e

    return candidate


def classify_path_and_content(
    relative_path: str,
    content: str | None = None,
) -> DataClassification:
    """Classifies path and content deterministically according to §9.5 and §18.1."""
    filename = Path(relative_path).name

    # 1. Secret file names
    for pat in SECRET_FILE_PATTERNS:
        if pat.match(filename):
            return DataClassification.SECRET

    # 2. Secret content inspection if content is provided
    if content:
        for cpat in SECRET_CONTENT_PATTERNS:
            if cpat.search(content):
                return DataClassification.SECRET

    # 3. Confidential paths (e.g. internal specs, auth, config)
    path_lower = relative_path.lower()
    if any(k in path_lower for k in ("auth", "security", "token", "password", "audit")):
        return DataClassification.CONFIDENTIAL

    # 4. Public files (README, LICENSE, pyproject.toml docs)
    if filename.lower() in ("readme.md", "license", "contributing.md", "notice"):
        return DataClassification.PUBLIC

    # Default repo code is INTERNAL
    return DataClassification.INTERNAL
