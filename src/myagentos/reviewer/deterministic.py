"""Deterministic code review checks according to §15.1 and §16."""

import re

from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS, detect_risk_signals


class DeterministicReviewer:
    """Executes rule-based, non-probabilistic checks on patch sets (§15.1)."""

    def __init__(
        self,
        protected_paths: list[str] | None = None,
    ) -> None:
        self.protected_paths = protected_paths or DEFAULT_PROTECTED_PATHS

    def review(
        self,
        patch_set: PatchSet,
        plan: PlanSpec,
        risk_level: RiskLevel,
    ) -> list[str]:
        """Runs all deterministic checks and returns a list of blocker findings."""
        findings: list[str] = []

        findings.extend(self.check_git_diff_syntax(patch_set))
        findings.extend(self.check_protected_paths(patch_set))
        findings.extend(self.check_scope_conformance(patch_set, plan))
        findings.extend(self.check_sensitive_path_risk(patch_set, risk_level))

        return findings

    def check_git_diff_syntax(self, patch_set: PatchSet) -> list[str]:
        """Detects merge conflict markers, corrupted hunks, or binary injections."""
        findings: list[str] = []
        conflict_marker_pattern = re.compile(r"^(<{7}|={7}|>{7})(\s|$)", re.MULTILINE)

        for fp in patch_set.files:
            if "\x00" in fp.patch:
                findings.append(f"Null bytes detected in text patch for '{fp.path}'")

            if conflict_marker_pattern.search(fp.patch):
                findings.append(
                    f"Unresolved git merge conflict markers found in patch for '{fp.path}'"
                )

        return findings

    def check_protected_paths(self, patch_set: PatchSet) -> list[str]:
        """Verifies that no integrity-protected test or harness paths were modified (§13.3)."""
        findings: list[str] = []
        for path in patch_set.affected_paths:
            for prot in self.protected_paths:
                if prot.endswith("/"):
                    if path.startswith(prot):
                        findings.append(f"Modification of protected directory path: '{path}'")
                elif path == prot:
                    findings.append(f"Modification of protected path: '{path}'")
        return findings

    def check_scope_conformance(self, patch_set: PatchSet, plan: PlanSpec) -> list[str]:
        """Verifies that all modified files were explicitly declared in the plan (§15.1)."""
        findings: list[str] = []
        targeted = plan.all_targeted_paths()

        for path in patch_set.affected_paths:
            if path not in targeted:
                findings.append(
                    f"Out-of-scope modification: '{path}' was not declared in Plan {plan.plan_id}"
                )

        return findings

    def check_sensitive_path_risk(
        self,
        patch_set: PatchSet,
        risk_level: RiskLevel,
    ) -> list[str]:
        """Ensures that sensitive files (auth, db, infra) are not modified under LOW risk (§5.2)."""
        findings: list[str] = []
        if risk_level != RiskLevel.LOW:
            return findings

        for path in patch_set.affected_paths:
            signals = detect_risk_signals([path], protected_paths=self.protected_paths)
            sensitive = [s for s in signals if s.category == "sensitive_path"]
            if sensitive:
                sig_names = ", ".join(s.description for s in sensitive)
                findings.append(
                    f"Sensitive path '{path}' ({sig_names}) modified under LOW risk level. "
                    "Risk escalation required (§5.2)."
                )

        return findings
