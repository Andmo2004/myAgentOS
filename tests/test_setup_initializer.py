"""Unit tests for Mya Home initializer (§10, §17)."""

import json
from pathlib import Path
from myagentos.setup.initializer import SUBDIRECTORIES, initialize_mya_home


def test_initialize_mya_home_creates_all_subdirs(tmp_path: Path) -> None:
    target_home = tmp_path / "custom_mya_home"
    assert not target_home.exists()

    initialized = initialize_mya_home(target_home)
    assert initialized == target_home.resolve()
    assert target_home.is_dir()

    for subdir in SUBDIRECTORIES:
        assert (target_home / subdir).is_dir(), f"Missing subdirectory {subdir}"

    version_file = target_home / "version.json"
    assert version_file.is_file()

    version_data = json.loads(version_file.read_text(encoding="utf-8"))
    assert version_data.get("schema_version") == 1
    assert version_data.get("format") == "mya_home_v1"
