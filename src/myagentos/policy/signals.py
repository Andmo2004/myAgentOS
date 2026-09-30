"""Risk signal detection based on paths and categories according to §5.2 and §13.2."""

from fnmatch import fnmatch

from myagentos.core.models.risk import RiskLevel, RiskSignal

# Default protected paths defined normatively in §13.2
DEFAULT_PROTECTED_PATHS = [
    "tests/protected/**",
    "tests/acceptance/**",
    "tests/security/**",
    "conftest.py",
    "**/conftest.py",
    "pytest.ini",
    "tox.ini",
    "**/fixtures/protected/**",
    ".github/workflows/**",
]

# Sensitive signal patterns defined in §5.2
SENSITIVE_PATTERNS: list[tuple[str, str, RiskLevel]] = [
    # Auth and credentials
    ("**/auth/**", "Authentication and session logic", RiskLevel.HIGH),
    ("*auth*", "Authentication logic", RiskLevel.HIGH),
    ("**/login*", "Login credentials logic", RiskLevel.HIGH),
    ("**/token*", "Token issuance and validation", RiskLevel.HIGH),
    # Databases and migrations
    ("**/migrations/**", "Database schema migration", RiskLevel.HIGH),
    ("**/alembic/**", "Database migration tool", RiskLevel.HIGH),
    ("*.sql", "Raw SQL or database schema", RiskLevel.HIGH),
    # Infrastructure and build
    ("Dockerfile*", "Container infrastructure", RiskLevel.HIGH),
    ("docker-compose*", "Container composition", RiskLevel.HIGH),
    ("Makefile", "Build and automation script", RiskLevel.HIGH),
    ("k8s/**", "Kubernetes manifests", RiskLevel.HIGH),
    # CI/CD
    (".github/workflows/**", "CI/CD automation pipelines", RiskLevel.CRITICAL),
    # Secrets and environment
    ("*.env*", "Environment configuration and secrets", RiskLevel.CRITICAL),
    ("**/secrets/**", "Secret storage", RiskLevel.CRITICAL),
    # Dependency manifests and lockfiles
    ("pyproject.toml", "Build and dependency configuration", RiskLevel.HIGH),
    ("uv.lock", "Dependency lockfile", RiskLevel.HIGH),
    ("package.json", "Dependency manifest", RiskLevel.HIGH),
    ("package-lock.json", "Dependency lockfile", RiskLevel.HIGH),
    ("poetry.lock", "Dependency lockfile", RiskLevel.HIGH),
    ("requirements*.txt", "Python dependency requirements", RiskLevel.HIGH),
]


def detect_risk_signals(
    paths: list[str],
    protected_paths: list[str] | None = None,
) -> list[RiskSignal]:
    """Inspects a list of file paths and returns all triggered risk signals (§5.2)."""
    signals: list[RiskSignal] = []
    active_protected = protected_paths or DEFAULT_PROTECTED_PATHS

    for path in paths:
        normalized = path.strip("/")

        # Check protected paths (§13.2) -> CRITICAL
        for pattern in active_protected:
            if fnmatch(normalized, pattern) or fnmatch(path, pattern):
                signals.append(
                    RiskSignal(
                        category="protected_path",
                        description=f"Path {path} matches protected pattern {pattern}",
                        path=path,
                        minimum_risk=RiskLevel.CRITICAL,
                    )
                )
                break

        # Check sensitive patterns (§5.2)
        for pattern, desc, min_risk in SENSITIVE_PATTERNS:
            if fnmatch(normalized, pattern) or fnmatch(path, pattern):
                signals.append(
                    RiskSignal(
                        category="sensitive_path",
                        description=f"{desc} ({path})",
                        path=path,
                        minimum_risk=min_risk,
                    )
                )
                break

    return signals
