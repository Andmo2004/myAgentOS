"""Unit tests for WorktreeManager, patch application, and MergeController."""

import hashlib
import subprocess
from pathlib import Path

from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.worktree import (
    MergeController,
    WorktreeManager,
    apply_patch_set,
    calculate_file_sha256,
)


def _init_git_repo(path: Path) -> str:
    """Helper to initialize a real git repository with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@agentic.os"],
        cwd=str(path),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Agentic Tester"],
        cwd=str(path),
        check=True,
    )

    init_file = path / "main.py"
    init_file.write_text("print('initial')\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True)

    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    return rev.stdout.strip()


def test_worktree_lifecycle_and_patch_application(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    base_commit = _init_git_repo(repo_dir)

    manager = WorktreeManager(repo_root=repo_dir)
    job_id = "job-wt-1"

    # 1. Create worktree
    wt_path = manager.create_worktree(job_id=job_id, base_commit=base_commit)
    assert wt_path.exists()
    assert (wt_path / "main.py").exists()

    # 2. Prepare PatchSet with modify and create
    original_main_sha = calculate_file_sha256(wt_path / "main.py")
    new_main_content = "print('updated')\n"
    new_main_sha = hashlib.sha256(new_main_content.encode("utf-8")).hexdigest()

    new_helper_content = "def helper(): pass\n"
    new_helper_sha = hashlib.sha256(new_helper_content.encode("utf-8")).hexdigest()

    patch_set = PatchSet(
        job_id=job_id,
        base_commit=base_commit,
        files=[
            FilePatch(
                path="main.py",
                operation=PatchOperation.MODIFY,
                patch=new_main_content,
                sha256_before=original_main_sha,
                sha256_after=new_main_sha,
            ),
            FilePatch(
                path="helper.py",
                operation=PatchOperation.CREATE,
                patch=new_helper_content,
                sha256_before="",
                sha256_after=new_helper_sha,
            ),
        ],
    )

    # 3. Apply patch
    success, err = apply_patch_set(wt_path, patch_set)
    assert success is True
    assert err is None
    assert (wt_path / "main.py").read_text(encoding="utf-8") == new_main_content
    assert (wt_path / "helper.py").read_text(encoding="utf-8") == new_helper_content

    # 4. MergeController commit
    merge_ctrl = MergeController(repo_root=repo_dir)
    with merge_ctrl.repository_lock():
        head_commit = merge_ctrl.commit_in_job_branch(wt_path, job_id=job_id)
        assert head_commit != base_commit

        # Simulate merge
        can_merge, merge_err = merge_ctrl.simulate_merge(base_commit, head_commit)
        assert can_merge is True
        assert merge_err is None

    # 5. Remove worktree
    manager.remove_worktree(job_id=job_id)
    assert not wt_path.exists()


def test_patch_applier_hash_mismatch_detection(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_err"
    repo_dir.mkdir()
    base_commit = _init_git_repo(repo_dir)

    manager = WorktreeManager(repo_root=repo_dir)
    job_id = "job-wt-err"
    wt_path = manager.create_worktree(job_id=job_id, base_commit=base_commit)

    # Modify with wrong sha256_before
    patch_set = PatchSet(
        job_id=job_id,
        base_commit=base_commit,
        files=[
            FilePatch(
                path="main.py",
                operation=PatchOperation.MODIFY,
                patch="print('bad')\n",
                sha256_before="bad_hash" * 8,
                sha256_after="whatever" * 8,
            )
        ],
    )
    success, err = apply_patch_set(wt_path, patch_set)
    assert success is False
    assert err is not None
    assert "Hash mismatch before" in err

    manager.remove_worktree(job_id=job_id)
