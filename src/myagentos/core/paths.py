"""Robust and secure path containment and filesystem operations (AGF-003, §10, §13)."""

import os
from collections.abc import Generator
from fnmatch import fnmatch
from pathlib import Path, PurePath

from myagentos.core.errors import (
    PathEscapeError,
    PolicyViolationError,
    SymlinkDisallowedError,
)


def validate_safe_path(
    base_dir: Path | str,
    relative_path: str,
    allow_symlinks: bool = False,
    must_exist: bool = False,
) -> Path:
    """Validates that a path is strictly within base_dir and free of traversal and symlinks.

    Raises:
        PathEscapeError: If path contains traversal sequences or resolves outside base_dir.
        SymlinkDisallowedError: If path or any intermediate component is a symlink.
        FileNotFoundError: If must_exist is True and target does not exist.
    """
    if not relative_path:
        raise PathEscapeError("Path cannot be empty")

    if "\x00" in relative_path:
        raise PathEscapeError("Path cannot contain null bytes")

    pure = PurePath(relative_path)
    if pure.is_absolute():
        raise PathEscapeError(f"Absolute path '{relative_path}' is not permitted")

    if ".." in pure.parts:
        raise PathEscapeError(f"Path traversal sequence '..' in '{relative_path}' is not permitted")

    resolved_base = Path(base_dir).resolve()
    target_unresolved = resolved_base / relative_path

    # Check every existing component from resolved_base down to target for symlinks
    current = resolved_base
    for part in pure.parts:
        current = current / part
        if not allow_symlinks and os.path.islink(current):
            raise SymlinkDisallowedError(
                f"Path '{relative_path}' traverses symlink component at '{part}'"
            )

    resolved_target = target_unresolved.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise PathEscapeError(
            f"Path '{relative_path}' escapes base directory '{resolved_base}'"
        ) from None

    if not allow_symlinks and os.path.islink(target_unresolved):
        raise SymlinkDisallowedError(
            f"Path '{relative_path}' points to a symlink, which is strictly disallowed (AGF-003)"
        )

    if must_exist and not target_unresolved.exists():
        raise FileNotFoundError(f"File not found: '{relative_path}'")

    return target_unresolved


def safe_read_text(
    base_dir: Path | str,
    relative_path: str,
    max_bytes: int = 10_000_000,
) -> str:
    """Safely reads a text file preventing symlink following and path traversal."""
    target = validate_safe_path(base_dir, relative_path, allow_symlinks=False, must_exist=True)
    if not target.is_file():
        raise FileNotFoundError(f"Not a regular file: '{relative_path}'")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(target), flags)
    except OSError as err:
        if err.errno in (getattr(os, "ELOOP", 62), getattr(os, "EEXIST", 17)):
            raise SymlinkDisallowedError(
                f"Symlink detected while opening '{relative_path}'"
            ) from err
        raise

    try:
        with open(fd, encoding="utf-8", errors="ignore") as f:
            return f.read(max_bytes)
    finally:
        # Note: open(fd, ...) will close fd when exiting with-block, but if exception before:
        pass


def safe_write_text(
    base_dir: Path | str,
    relative_path: str,
    content: str,
    overwrite: bool = True,
) -> int:
    """Safely writes content to a file, verifying containment and preventing symlink escapes."""
    target = validate_safe_path(base_dir, relative_path, allow_symlinks=False, must_exist=False)

    if not overwrite and target.exists():
        raise PolicyViolationError(
            f"Cannot create file '{relative_path}': file already exists and overwrite is False"
        )

    # Ensure parent directory is safe and exists
    resolved_base = Path(base_dir).resolve()
    parent = target.parent
    try:
        parent.resolve().relative_to(resolved_base)
    except ValueError:
        raise PathEscapeError(
            f"Parent directory of '{relative_path}' escapes base directory '{resolved_base}'"
        ) from None

    # Step through parents to create them safely without following symlinks
    current = resolved_base
    rel_parent = parent.relative_to(resolved_base)
    for part in rel_parent.parts:
        current = current / part
        if os.path.islink(current):
            raise SymlinkDisallowedError(f"Parent directory '{current}' is a symlink")
        if not current.exists():
            current.mkdir(mode=0o755, exist_ok=True)
        elif not current.is_dir():
            raise PolicyViolationError(f"Path component '{current}' exists and is not a directory")

    if not overwrite and target.exists():
        raise PolicyViolationError(f"File '{relative_path}' already exists")

    # Atomic write to avoid partial writes and race conditions
    tmp_target = parent / f".tmp_safe_{os.getpid()}_{os.urandom(4).hex()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(tmp_target), flags, 0o644)
    except OSError as err:
        if err.errno in (getattr(os, "ELOOP", 62),):
            raise SymlinkDisallowedError(
                f"Symlink detected while creating temp file for '{relative_path}'"
            ) from err
        raise

    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(str(tmp_target), str(target))
    except Exception:
        if tmp_target.exists():
            try:
                tmp_target.unlink()
            except OSError:
                pass
        raise

    return len(content)


def safe_delete_file(base_dir: Path | str, relative_path: str) -> None:
    """Safely deletes a file within base_dir without following symlinks."""
    target = validate_safe_path(base_dir, relative_path, allow_symlinks=False, must_exist=True)
    if os.path.islink(target):
        raise SymlinkDisallowedError(f"Refusing to delete symlink '{relative_path}'")
    target.unlink()


def safe_rename_file(
    base_dir: Path | str,
    old_relative_path: str,
    new_relative_path: str,
) -> None:
    """Safely renames a file ensuring both source and destination stay strictly within base_dir."""
    old_target = validate_safe_path(
        base_dir, old_relative_path, allow_symlinks=False, must_exist=True
    )
    new_target = validate_safe_path(
        base_dir, new_relative_path, allow_symlinks=False, must_exist=False
    )

    if os.path.islink(old_target) or os.path.islink(new_target):
        raise SymlinkDisallowedError("Renaming involving symlinks is strictly disallowed")

    # Ensure parent directory of destination exists safely
    resolved_base = Path(base_dir).resolve()
    current = resolved_base
    rel_parent = new_target.parent.relative_to(resolved_base)
    for part in rel_parent.parts:
        current = current / part
        if os.path.islink(current):
            raise SymlinkDisallowedError(f"Destination parent directory '{current}' is a symlink")
        if not current.exists():
            current.mkdir(mode=0o755, exist_ok=True)

    os.rename(str(old_target), str(new_target))


def safe_walk(
    base_dir: Path | str,
    sub_path: str = ".",
) -> Generator[tuple[Path, str], None, None]:
    """Safely traverses files in sub_path relative to base_dir, never following symlinks."""
    start_dir = validate_safe_path(base_dir, sub_path, allow_symlinks=False, must_exist=True)
    resolved_base = Path(base_dir).resolve()

    for root, dirs, files in os.walk(str(start_dir), followlinks=False):
        root_path = Path(root)
        # Prune any directory symlinks from traversal
        dirs[:] = [d for d in dirs if not os.path.islink(root_path / d)]

        for fname in files:
            fpath = root_path / fname
            if os.path.islink(fpath):
                continue
            try:
                rel_path = fpath.relative_to(resolved_base).as_posix()
                yield fpath, rel_path
            except ValueError:
                continue


def matches_path_pattern(path: str, pattern: str) -> bool:
    """Matches a relative path against a glob pattern, supporting standard recursive globs.

    Supports:
    - Direct matches and fnmatch wildcards (*, ?, [a-z])
    - Recursive globs ('**/*', '**') matching both direct and nested descendants
    - Directory wildcards (e.g. 'src/**/*' matching 'src/app.py' and 'src/a/b.py')
    """
    normalized = path.strip("/")
    stripped_pat = pattern.strip("/")

    if (
        fnmatch(normalized, pattern)
        or fnmatch(path, pattern)
        or fnmatch(normalized, stripped_pat)
    ):
        return True

    # Recursive directory glob: e.g. "src/**/*" or "/src/**/*"
    if stripped_pat.endswith("/**/*"):
        prefix = stripped_pat[:-5].strip("/")
        return (
            fnmatch(normalized, f"{prefix}/*")
            or fnmatch(normalized, f"{prefix}/**")
            or normalized.startswith(f"{prefix}/")
        )

    # Bare recursive glob: "**/*" or "**"
    if stripped_pat in ("**/*", "**", "*"):
        return True

    return False
