"""Unit tests for Mya Home path validator (§16)."""

from pathlib import Path
from myagentos.setup.validator import is_protected_path, validate_mya_home


def test_validate_empty_path() -> None:
    res = validate_mya_home(None)
    assert not res.valid
    assert "empty" in res.error.lower()

    res2 = validate_mya_home("   ")
    assert not res2.valid
    assert "empty" in res2.error.lower()


def test_validate_protected_path() -> None:
    res = validate_mya_home("/")
    assert not res.valid
    assert "protected" in res.error.lower()

    assert is_protected_path(Path("/usr"))
    assert is_protected_path(Path("/System"))


def test_validate_git_dir(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    res = validate_mya_home(git_dir)
    assert not res.valid
    assert ".git" in res.error


def test_validate_valid_existing_dir(tmp_path: Path) -> None:
    home_dir = tmp_path / ".agenticos"
    home_dir.mkdir()
    res = validate_mya_home(home_dir)
    assert res.valid
    assert res.error == ""
    assert res.resolved_path == home_dir.resolve()


def test_validate_valid_creatable_dir(tmp_path: Path) -> None:
    candidate = tmp_path / "sub" / ".agenticos"
    res = validate_mya_home(candidate)
    assert res.valid
    assert res.error == ""
