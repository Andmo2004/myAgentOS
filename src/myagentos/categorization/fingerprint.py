"""Repository scan fingerprint generator for caching and staleness detection.

Follows §13 of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ScanFingerprint(BaseModel):
    """Cryptographic fingerprint of repository structure and dependency manifests (§13)."""

    model_config = ConfigDict(frozen=True)

    manifests_hash: str
    dependency_hash: str
    tree_hash: str
    ci_hash: str
    combined_hash: str


MANIFEST_FILENAMES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)

LOCK_FILENAMES = (
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "composer.lock",
)


def _hash_file_if_exists(file_path: Path) -> str:
    """Returns SHA-256 hex digest of file contents if it exists and is under 2MB."""
    if not file_path.is_file():
        return ""
    try:
        if file_path.stat().st_size > 2 * 1024 * 1024:
            # File too large, hash size and mtime
            st = file_path.stat()
            return hashlib.sha256(f"{st.st_size}_{st.st_mtime}".encode()).hexdigest()
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        return ""


def calculate_fingerprint(repo_root: Path) -> ScanFingerprint:
    """Calculates deterministic fingerprint over repository manifests, lockfiles, and CI (§13)."""
    manifest_digests: list[str] = []
    for name in MANIFEST_FILENAMES:
        p = repo_root / name
        if p.exists():
            h = _hash_file_if_exists(p)
            if h:
                manifest_digests.append(f"{name}:{h}")

    manifests_hash = hashlib.sha256(";".join(manifest_digests).encode()).hexdigest()

    lock_digests: list[str] = []
    for name in LOCK_FILENAMES:
        p = repo_root / name
        if p.exists():
            h = _hash_file_if_exists(p)
            if h:
                lock_digests.append(f"{name}:{h}")

    dependency_hash = hashlib.sha256(";".join(lock_digests).encode()).hexdigest()

    ci_digests: list[str] = []
    github_ci = repo_root / ".github" / "workflows"
    if github_ci.is_dir():
        for yml in sorted(github_ci.glob("*.y*ml")):
            ci_digests.append(f"{yml.name}:{_hash_file_if_exists(yml)}")
    gitlab_ci = repo_root / ".gitlab-ci.yml"
    if gitlab_ci.exists():
        ci_digests.append(f"gitlab:{_hash_file_if_exists(gitlab_ci)}")

    ci_hash = hashlib.sha256(";".join(ci_digests).encode()).hexdigest()

    # Structural top-level directory names
    top_entries: list[str] = []
    try:
        for item in sorted(repo_root.iterdir()):
            if item.name.startswith(".") and item.name not in (".github",):
                continue
            item_type = "d" if item.is_dir() else "f"
            top_entries.append(f"{item_type}:{item.name}")
    except Exception:
        pass

    tree_hash = hashlib.sha256(";".join(top_entries).encode()).hexdigest()

    combined_raw = f"{manifests_hash}|{dependency_hash}|{ci_hash}|{tree_hash}"
    combined_hash = hashlib.sha256(combined_raw.encode()).hexdigest()

    return ScanFingerprint(
        manifests_hash=manifests_hash,
        dependency_hash=dependency_hash,
        tree_hash=tree_hash,
        ci_hash=ci_hash,
        combined_hash=combined_hash,
    )
