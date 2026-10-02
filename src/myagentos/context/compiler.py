"""Deterministic Context Compiler with dependency closure and prompt caching (§9, §18, AUD-005)."""

from fnmatch import fnmatch
from pathlib import Path

from myagentos.context.closure import DependencyClosureAnalyzer
from myagentos.context.extractor import StructuralExtractor
from myagentos.context.models import (
    CompiledContext,
    ContextExpansionRequest,
    ContextExpansionResult,
    ContextKind,
)
from myagentos.context.security import (
    PathSecurityViolation,
    canonicalize_and_verify_path,
    classify_path_and_content,
)
from myagentos.continuity.models import ProjectFinding, ProjectSnapshot
from myagentos.core.models.data_policy import DataClassification
from myagentos.core.models.patch import PatchOperation, PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.token import CapabilityToken
from myagentos.policy.engine import PolicyEngine


def estimate_tokens(text: str) -> int:
    """Fast, deterministic token estimator (~4 chars per token)."""
    return max(1, len(text) // 4)


PLAN_SYSTEM_PROMPT = """You are the Planner agent in Agentic OS.
Your role is to formulate a minimal, precise PlanSpec for the user's objective.
You are provided with a lightweight structural map (signatures, imports, tests).
Do not assume unstated permissions or broad scopes. Minimize target files."""

WORKER_SYSTEM_PROMPT = """You are the Worker agent in Agentic OS.
Operate strictly within your assigned capability token and bounded execution loop.
Propose file edits and tool calls adhering to the architecture and existing test suite."""


class ContextCompiler:
    """Builds minimal sufficient context for Planner, Worker, Knowledge, and PCA (§9)."""

    def __init__(
        self,
        repo_root: Path,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.policy_engine = policy_engine or PolicyEngine()

    def compile_plan_context(
        self,
        job_id: str,
        prompt: str,
        seed_paths: list[str] | None = None,
        base_commit: str = "HEAD",
        max_tokens: int = 8000,
    ) -> CompiledContext:
        """Constructs PLAN_CONTEXT before PLAN_SPEC generation (§9.2).

        Lightweight structural map: signatures, imports, route tree, test summaries.
        Without file bodies unless strictly necessary.
        """
        repo_map = DependencyClosureAnalyzer.build_repository_map(self.repo_root)

        # Build signatures for seed files if provided
        seed_paths = seed_paths or []
        signatures_blocks: list[str] = []

        for p in seed_paths:
            try:
                canon_path = canonicalize_and_verify_path(p, self.repo_root)
                if canon_path.is_file():
                    summary = StructuralExtractor.extract_file(canon_path, p)
                    signatures_blocks.append(StructuralExtractor.format_signatures(summary))
            except PathSecurityViolation:
                continue

        stable_parts: list[str] = [
            f"# Role: PLANNER | Job: {job_id} | Base Commit: {base_commit}",
            PLAN_SYSTEM_PROMPT,
            "## Repository Tree",
            repo_map.tree_repr,
            "## Key Entrypoints",
            "\n".join(f"- {e}" for e in repo_map.key_entrypoints) or "None",
            "## Test Suites",
            "\n".join(f"- {t}" for t in repo_map.test_files[:15]) or "None",
            "## Dependency Manifests",
            "\n".join(f"- {m}" for m in repo_map.manifest_files) or "None",
        ]

        if signatures_blocks:
            stable_parts.extend(["## Seed Signatures", "\n\n".join(signatures_blocks)])

        stable_prefix = "\n\n".join(stable_parts)

        variable_suffix = f"## Task Objective\n{prompt}\n\nPlease generate a structured PlanSpec."

        total_tokens = estimate_tokens(stable_prefix) + estimate_tokens(variable_suffix)

        return CompiledContext(
            context_kind=ContextKind.PLAN_CONTEXT,
            job_id=job_id,
            base_commit=base_commit,
            stable_prefix=stable_prefix,
            variable_suffix=variable_suffix,
            total_estimated_tokens=total_tokens,
            target_files=seed_paths,
            dependency_files=[],
            metadata={"total_repo_files": repo_map.total_files},
        )

    def compile_worker_context(
        self,
        job_id: str,
        prompt: str,
        plan: PlanSpec,
        token: CapabilityToken,
        max_tokens: int = 16000,
    ) -> CompiledContext:
        """Constructs WORKER_CONTEXT after approval (§9.2).

        Dependency closure of approved scope: target files (full content),
        direct imports & referenced signatures, relevant tests, and manifests.
        """
        targets = sorted(plan.all_targeted_paths())

        # 1. Compute dependency closure
        closure_files = DependencyClosureAnalyzer.compute_dependency_closure(
            seed_files=targets,
            root_dir=self.repo_root,
            max_depth=2,
        )

        repo_map = DependencyClosureAnalyzer.build_repository_map(self.repo_root, max_tree_lines=60)

        # 2. Extract signatures of closure files
        closure_signatures: list[str] = []
        for cfile in closure_files:
            try:
                cpath = canonicalize_and_verify_path(cfile, self.repo_root)
                if cpath.is_file():
                    summary = StructuralExtractor.extract_file(cpath, cfile)
                    closure_signatures.append(StructuralExtractor.format_signatures(summary))
            except PathSecurityViolation:
                continue

        # 3. Read target files content (respecting token read scope)
        target_contents: list[str] = []
        for tfile in targets:
            if not self._is_path_allowed(tfile, token.read_scope):
                target_contents.append(
                    f"### File: {tfile} [READ PERMISSION DENIED BY CAPABILITY TOKEN]"
                )
                continue

            try:
                tpath = canonicalize_and_verify_path(tfile, self.repo_root)
                if tpath.is_file():
                    content = tpath.read_text(encoding="utf-8", errors="ignore")
                    classification = classify_path_and_content(tfile, content)
                    if classification == DataClassification.SECRET:
                        target_contents.append(
                            f"### File: {tfile} [REDACTED: SECRET DETECTED BY POLICY §18]"
                        )
                    else:
                        target_contents.append(
                            f"### File: {tfile} ({len(content.splitlines())} lines)\n"
                            f"```\n{content}\n```"
                        )
                else:
                    target_contents.append(f"### File: {tfile} (New file to create)")
            except PathSecurityViolation as e:
                target_contents.append(f"### File: {tfile} [SECURITY VIOLATION: {e}]")

        # Stable prefix (system instructions, structural map, closure signatures)
        stable_parts = [
            f"# Role: WORKER | Job: {job_id} | Base Commit: {plan.base_commit}",
            WORKER_SYSTEM_PROMPT,
            "## Repository Tree",
            repo_map.tree_repr,
            "## Dependency Signatures",
            "\n\n".join(closure_signatures) if closure_signatures else "None",
        ]
        stable_prefix = "\n\n".join(stable_parts)

        # Variable suffix (task, plan summary, target file contents)
        variable_parts = [
            f"## Task Objective\n{prompt}",
            (
                f"## Approved Plan Summary\n"
                f"- Plan ID: {plan.plan_id}\n"
                f"- Targets: {', '.join(targets)}"
            ),
            (
                f"## Capability Bounds\n"
                f"- Read Scope: {token.read_scope}\n"
                f"- Write Scope: {token.write_scope}\n"
                f"- Max Steps: {token.limits.max_steps}"
            ),
            "## Target Files Content",
            "\n\n".join(target_contents),
        ]
        variable_suffix = "\n\n".join(variable_parts)

        total_tokens = estimate_tokens(stable_prefix) + estimate_tokens(variable_suffix)

        # Budget-aware truncation if exceeded
        if total_tokens > max_tokens and closure_signatures:
            # Truncate closure signatures to fit budget
            trimmed_signatures = closure_signatures[: len(closure_signatures) // 2]
            stable_parts[-1] = "\n\n".join(trimmed_signatures)
            stable_prefix = "\n\n".join(stable_parts)
            total_tokens = estimate_tokens(stable_prefix) + estimate_tokens(variable_suffix)

        return CompiledContext(
            context_kind=ContextKind.WORKER_CONTEXT,
            job_id=job_id,
            base_commit=plan.base_commit,
            stable_prefix=stable_prefix,
            variable_suffix=variable_suffix,
            total_estimated_tokens=total_tokens,
            target_files=targets,
            dependency_files=closure_files,
            metadata={"risk_level": token.risk_level.value, "plan_id": plan.plan_id},
        )

    def compile_knowledge_context(
        self,
        job_id: str,
        patch_set: PatchSet,
        base_commit: str = "HEAD",
    ) -> CompiledContext:
        """Constructs KNOWLEDGE_CONTEXT post-merge (§9.2, §22.2).

        Deterministic facts extracted without LLM: signatures, new/modified exported symbols,
        added tests, and modified dependencies.
        """
        facts: list[str] = [
            f"# Post-Merge Knowledge Update | Job: {job_id} | Base Commit: {base_commit}",
            f"## Affected Files Count: {patch_set.total_files}",
        ]

        modified_symbols: list[str] = []
        tests_added: list[str] = []
        deps_changed: list[str] = []

        for fp in patch_set.files:
            op_label = fp.operation.value.upper()
            facts.append(f"- [{op_label}] {fp.path} (diff lines: {fp.diff_line_count})")
            if "test" in fp.path.lower():
                tests_added.append(fp.path)
            if fp.path in ("pyproject.toml", "requirements.txt", "package.json"):
                deps_changed.append(fp.path)

            # Extract symbols if file exists in worktree
            fpath = self.repo_root / fp.path
            if fpath.is_file() and fp.operation != PatchOperation.DELETE:
                summary = StructuralExtractor.extract_file(fpath, fp.path)
                for sym in summary.symbols:
                    if sym.is_exported:
                        modified_symbols.append(f"{fp.path}:{sym.name} ({sym.kind.value})")

        facts.append("## Exported Symbols in Modified Files")
        facts.append("\n".join(f"- {s}" for s in modified_symbols) or "None")

        facts.append("## Tests Affected")
        facts.append("\n".join(f"- {t}" for t in tests_added) or "None")

        facts.append("## Dependency Manifests Affected")
        facts.append("\n".join(f"- {d}" for d in deps_changed) or "None")

        body = "\n\n".join(facts)
        tokens = estimate_tokens(body)

        return CompiledContext(
            context_kind=ContextKind.KNOWLEDGE_CONTEXT,
            job_id=job_id,
            base_commit=base_commit,
            stable_prefix="Deterministic Knowledge Facts (§22.2)",
            variable_suffix=body,
            total_estimated_tokens=tokens,
            target_files=list(patch_set.affected_paths),
            dependency_files=[],
            metadata={"files_count": patch_set.total_files},
        )

    def compile_continuation_context(
        self,
        job_id: str,
        snapshot: ProjectSnapshot,
        findings: list[ProjectFinding],
        synthesis_doc: str | None = None,
    ) -> CompiledContext:
        """Constructs CONTINUATION_CONTEXT for the Continuity Analyst (§6.2, PCA extension)."""
        stable_prefix = (
            f"# Role: CONTINUITY_ANALYST | Job: {job_id} | Commit: {snapshot.base_commit}\n\n"
            "Analyze project continuity baseline, structural health, "
            "and active findings without bias."
        )

        variable_parts = [
            (
                f"## Repository Baseline\n"
                f"- Branch: {snapshot.branch}\n"
                f"- Tracked files: {len(snapshot.tracked_files)}\n"
                f"- Size bytes: {snapshot.project_size_bytes}\n"
                f"- Working tree clean: {snapshot.working_tree.clean}"
            ),
            f"## Findings Summary ({len(findings)} total)",
        ]

        # Group findings by severity
        findings_by_sev: dict[str, list[ProjectFinding]] = {}
        for f in findings:
            findings_by_sev.setdefault(f.severity.value, []).append(f)

        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            f_list = findings_by_sev.get(sev, [])
            if f_list:
                variable_parts.append(f"### Severity: {sev} ({len(f_list)})")
                for item in f_list[:5]:
                    variable_parts.append(f"- **[{item.code.value}]** {item.title}: {item.summary}")

        if synthesis_doc:
            variable_parts.append(f"## Continuation Synthesis\n{synthesis_doc}")

        variable_suffix = "\n\n".join(variable_parts)
        total_tokens = estimate_tokens(stable_prefix) + estimate_tokens(variable_suffix)

        return CompiledContext(
            context_kind=ContextKind.CONTINUATION_CONTEXT,
            job_id=job_id,
            base_commit=snapshot.base_commit,
            stable_prefix=stable_prefix,
            variable_suffix=variable_suffix,
            total_estimated_tokens=total_tokens,
            target_files=[],
            dependency_files=[],
            metadata={"findings_count": len(findings)},
        )

    def expand_context(
        self,
        request: ContextExpansionRequest,
        token: CapabilityToken,
        current_context: CompiledContext,
    ) -> ContextExpansionResult:
        """Evaluates Context Expansion request against token permissions and safety (§9.3)."""
        expanded: list[str] = []
        denied: list[str] = []
        content_by_path: dict[str, str] = {}
        rejection_reasons: list[str] = []
        requires_token_renegotiation = False

        for path_str in request.paths_suggested:
            # 1. Path safety and canonicalization (§9.6)
            try:
                canon_path = canonicalize_and_verify_path(path_str, self.repo_root)
            except PathSecurityViolation as e:
                denied.append(path_str)
                rejection_reasons.append(f"Security violation for '{path_str}': {e}")
                continue

            rel_str = canon_path.relative_to(self.repo_root).as_posix()

            # 2. Check capability token read scope (§9.3, §23)
            if not self._is_path_allowed(rel_str, token.read_scope):
                denied.append(rel_str)
                requires_token_renegotiation = True
                rejection_reasons.append(
                    f"Path '{rel_str}' outside capability token read scope ({token.read_scope})"
                )
                continue

            # 3. Data classification & secret detection (§9.5, §18)
            content = canon_path.read_text(encoding="utf-8", errors="ignore")
            classification = classify_path_and_content(rel_str, content)
            if classification == DataClassification.SECRET:
                denied.append(rel_str)
                rejection_reasons.append(f"Path '{rel_str}' contains classified secrets (§18)")
                continue

            expanded.append(rel_str)
            content_by_path[rel_str] = content

        approved = len(expanded) > 0 and not requires_token_renegotiation

        return ContextExpansionResult(
            approved=approved,
            expanded_paths=expanded,
            denied_paths=denied,
            content_by_path=content_by_path,
            requires_token_renegotiation=requires_token_renegotiation,
            rejection_reasons=rejection_reasons,
        )

    def _is_path_allowed(self, path: str, allowed_patterns: list[str]) -> bool:
        """Glob pattern matcher for path permission scopes."""
        return any(fnmatch(path, pat) or fnmatch(Path(path).name, pat) for pat in allowed_patterns)
