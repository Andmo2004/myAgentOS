"""Unit tests for path canonicalization and secret classification (§9.5, §9.6, §18)."""

from pathlib import Path

import pytest

from myagentos.context.security import (
    PathSecurityViolation,
    canonicalize_and_verify_path,
    classify_path_and_content,
)
from myagentos.core.models.data_policy import DataClassification


def test_canonicalize_and_verify_path_valid(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_file = src_dir / "app.py"
    target_file.write_text("print('hello')")

    canon = canonicalize_and_verify_path("src/app.py", tmp_path)
    assert canon == target_file.resolve()

    canon2 = canonicalize_and_verify_path("./src/app.py", tmp_path)
    assert canon2 == target_file.resolve()


def test_canonicalize_and_verify_path_traversal_rejection(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityViolation, match="traversal"):
        canonicalize_and_verify_path("../../../etc/passwd", tmp_path)

    with pytest.raises(PathSecurityViolation, match="traversal"):
        canonicalize_and_verify_path("src/../../outside.py", tmp_path)


def test_classify_path_and_content_secrets() -> None:
    # Secret filenames
    assert classify_path_and_content(".env") == DataClassification.SECRET
    assert classify_path_and_content(".env.local") == DataClassification.SECRET
    assert classify_path_and_content("id_rsa") == DataClassification.SECRET
    assert classify_path_and_content("server.key") == DataClassification.SECRET

    # Secret contents
    aws_secret = "AWS key = AKIAIOSFODNN7EXAMPLE"
    assert classify_path_and_content("src/config.py", aws_secret) == DataClassification.SECRET

    priv_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
    assert classify_path_and_content("certs/cert.txt", priv_key) == DataClassification.SECRET

    # Confidential
    assert classify_path_and_content("src/auth/login.py") == DataClassification.CONFIDENTIAL

    # Public
    assert classify_path_and_content("README.md") == DataClassification.PUBLIC
    assert classify_path_and_content("LICENSE") == DataClassification.PUBLIC

    # Normal code
    assert classify_path_and_content("src/math/utils.py") == DataClassification.INTERNAL
