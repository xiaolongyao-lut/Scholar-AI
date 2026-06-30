from __future__ import annotations

import ast
from collections import Counter
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITIGNORE = REPO_ROOT / ".gitignore"
WORKFLOW_SPINE_GOAL_STATE = (
    "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
)
PRIVATE_LOCAL_PLAN_PROBE = "docs/plans/private-local-audit-placeholder.md"
WORKSPACE_TESTS_LOCAL_ONLY_PROBES = (
    "workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl",
    "workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl",
    "workspace_tests/fixtures/wiki_eval_smoke/manifest.json",
    "workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/baseline-contrast.md",
    "workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/paper-a.md",
    "workspace_tests/fixtures/wiki_graph_doctor_smoke/pages/concepts/alpha-model.md"
)
KNOWLEDGE_RUNTIME_PACKAGE_KINDS = (
    "wiki",
    "source_vault",
    "academic_english",
    "bridge_lexicon",
    "skill_package",
    "config",
    "product_docs",
)

PYTHON_TEST_RE = re.compile(r"(?P<path>(?:tests|agent_mcp_server/tests)/[A-Za-z0-9_./-]+\.py)")
FRONTEND_TEST_RE = re.compile(r"(?P<path>src/[A-Za-z0-9_./-]+\.test\.(?:tsx|ts))")
TESTS_PROMOTION_RE = re.compile(r"^!/tests/(?P<path>[A-Za-z0-9_./-]+\.py)$")
FRONTEND_PROMOTION_RE = re.compile(
    r"^!/frontend/src/(?P<path>[A-Za-z0-9_./-]+\.test\.(?:tsx|ts))$"
)
GIT_VISIBLE_TEST_RE = re.compile(
    r"^(?:tests/[A-Za-z0-9_./-]+\.py|"
    r"agent_mcp_server/tests/[A-Za-z0-9_./-]+\.py|"
    r"frontend/src/[A-Za-z0-9_./-]+\.test\.(?:tsx|ts)|"
    r"frontend/e2e/[A-Za-z0-9_./-]+\.spec\.ts)$"
)
GIT_VISIBLE_TEST_ROOTS = ("tests", "agent_mcp_server/tests", "frontend/src", "frontend/e2e")

PYTEST_FOCUSED_CI_EXEMPTIONS: dict[str, str] = {
    "tests/conftest.py": "pytest support module, not a standalone CI target",
    "tests/live_api_chat_full_writing_chain_smoke.py": "live API smoke remains opt-in outside deterministic CI",
    "tests/live_api_chat_knowledge_context_receipt_smoke.py": "live Knowledge Runtime context-receipt smoke remains opt-in outside deterministic CI",
    "tests/live_provider_direct_workflow_smoke.py": "live direct provider workflow smoke remains opt-in outside deterministic CI",
    "tests/test_api_probe_semantics.py": "legacy API probe contract outside the current KRT/N33 focused gate",
    "tests/test_chat_hybrid_retrieval.py": "broader retrieval regression outside the current KRT/N33 focused gate",
    "tests/test_chunk_vector_store_dim_allowlist.py": "vector-store compatibility check outside the current KRT/N33 focused gate",
    "tests/test_credentials_sampling.py": "credential sampling regression outside the current KRT/N33 focused gate",
    "tests/test_credentials_strategy_hint_mapping.py": "credential strategy mapping outside the current KRT/N33 focused gate",
    "tests/test_diagnostics_router.py": "diagnostics router regression outside the current KRT/N33 focused gate",
    "tests/test_discussion_mcp_per_agent_scope.py": "discussion MCP scope regression outside the current KRT/N33 focused gate",
    "tests/test_discussion_runtime_credentials.py": "discussion credential regression outside the current KRT/N33 focused gate",
    "tests/test_embedding_key_probe.py": "embedding key probe regression outside the current KRT/N33 focused gate",
    "tests/test_env_example_contract.py": "env example contract outside the current KRT/N33 focused gate",
    "tests/test_evolution_release_hardening.py": "release hardening regression outside the current KRT/N33 focused gate",
    "tests/test_export_docx_contract.py": "DOCX export contract outside the current KRT/N33 focused gate",
    "tests/test_journal_metric_evidence.py": "journal metric evidence regression outside the current KRT/N33 focused gate",
    "tests/test_key_pool_priority.py": "key-pool priority regression outside the current KRT/N33 focused gate",
    "tests/test_live_api_chat_full_writing_chain_smoke_harness.py": "live smoke harness remains opt-in outside deterministic CI",
    "tests/test_local_rerank_adapter.py": "local rerank adapter regression outside the current KRT/N33 focused gate",
    "tests/test_local_rerank_status_endpoint.py": "local rerank status regression outside the current KRT/N33 focused gate",
    "tests/test_mcp_phase2_tool_loop.py": "phase-2 MCP loop regression outside the current KRT/N33 focused gate",
    "tests/test_metadata_linter_api.py": "metadata linter regression outside the current KRT/N33 focused gate",
    "tests/test_pdf_backend_router.py": "PDF backend router regression outside the current KRT/N33 focused gate",
    "tests/test_pdf_backends.py": "PDF backend matrix regression outside the current KRT/N33 focused gate",
    "tests/test_provider_endpoint_policy.py": "provider endpoint policy regression outside the current KRT/N33 focused gate",
    "tests/test_provider_endpoint_policy_fake_ip.py": "provider endpoint fake-IP regression outside the current KRT/N33 focused gate",
    "tests/test_provider_endpoint_policy_loopback.py": "provider endpoint loopback regression outside the current KRT/N33 focused gate",
    "tests/test_pyproject_runtime_metadata.py": "runtime metadata regression outside the current KRT/N33 focused gate",
    "tests/test_rag_ablation_evaluator.py": "RAG ablation evaluator regression outside the current KRT/N33 focused gate",
    "tests/test_rag_structured_sibling_inclusion.py": "RAG sibling inclusion regression outside the current KRT/N33 focused gate",
    "tests/test_release_secret_scan.py": "release secret-scan regression outside the current KRT/N33 focused gate",
    "tests/test_search_refs_contract.py": "search refs contract outside the current KRT/N33 focused gate",
    "tests/test_skill_export.py": "skill export regression outside the current KRT/N33 focused gate",
    "tests/test_start_launchers_security.py": "launcher security regression outside the current KRT/N33 focused gate",
    "tests/test_token_utils_offline.py": "token utility regression outside the current KRT/N33 focused gate",
    "tests/test_tolf_rag_fusion.py": "TOLF RAG fusion regression outside the current KRT/N33 focused gate",
    "tests/test_wiki_export.py": "wiki export regression outside the current KRT/N33 focused gate",
    "tests/test_wiki_permissions.py": "wiki permissions regression outside the current KRT/N33 focused gate",
    "tests/test_writing_runtime_persistence.py": "writing runtime persistence outside the current KRT/N33 focused gate",
    "tests/test_writing_submission_export.py": "writing submission export outside the current KRT/N33 focused gate",
}

MCP_FOCUSED_CI_EXEMPTIONS: dict[str, str] = {
    "agent_mcp_server/tests/test_backend_client.py": "backend client unit coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_backend_launcher.py": "backend launcher coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_distribution.py": "distribution packaging coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_experimental_tools.py": "experimental tools outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_policy.py": "policy unit coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_redaction.py": "redaction unit coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_result.py": "result helper unit coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_runtime_attach.py": "runtime attach coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_source_tools.py": "source tools coverage outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_stdio_academic_writing_acceptance.py": "academic-writing stdio acceptance outside runtime-wrapper focused CI",
    "agent_mcp_server/tests/test_workflow_tools.py": "workflow tools coverage outside runtime-wrapper focused CI",
}

FRONTEND_FOCUSED_CI_EXEMPTIONS: dict[str, str] = {
    "frontend/src/components/chat/MessageRenderer.test.tsx": "SmartRead renderer regression outside wiki/N33 focused CI",
    "frontend/src/components/graph/DimensionGraphViewer.test.tsx": "graph viewer regression outside wiki/N33 focused CI",
    "frontend/src/components/graph/semanticReviewSpec.test.ts": "semantic graph review spec outside wiki/N33 focused CI",
    "frontend/src/pages/Jobs.test.tsx": "jobs page regression outside wiki/N33 focused CI",
    "frontend/src/pages/Settings.test.tsx": "settings page regression outside wiki/N33 focused CI",
}

E2E_FOCUSED_CI_EXEMPTIONS: dict[str, str] = {
    "frontend/e2e/agent-workspace-requirement-drilldown.spec.ts": "Playwright desktop-acceptance route smoke remains outside focused unit CI",
}


def _read_text(path: Path) -> str:
    """Return UTF-8 text for required repository configuration files."""
    if not path.is_file():
        raise AssertionError(f"Required configuration file is missing: {path}")
    return path.read_text(encoding="utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    """Return a JSON object from a required repository record."""
    payload = json.loads(_read_text(path))
    if not isinstance(payload, dict):
        raise AssertionError(f"Required JSON record must be an object: {path}")
    return payload


def _normalize_path(raw_path: str) -> str:
    """Return repository-style paths for CI and git comparisons."""
    normalized = raw_path.strip().replace("\\", "/").rstrip("\\")
    if not normalized:
        raise ValueError("Test path must not be empty.")
    return normalized


def _focused_ci_tests() -> set[str]:
    """Return test file paths explicitly listed in the focused CI workflow."""
    workflow = _read_text(CI_WORKFLOW)
    python_paths = {_normalize_path(match.group("path")) for match in PYTHON_TEST_RE.finditer(workflow)}
    frontend_paths = {
        _normalize_path(f"frontend/{match.group('path')}")
        for match in FRONTEND_TEST_RE.finditer(workflow)
    }
    return python_paths | frontend_paths


def _promoted_tests() -> set[str]:
    """Return tests explicitly promoted through the public-source allowlist."""
    gitignore = _read_text(GITIGNORE)
    promoted: set[str] = set()
    for line in gitignore.splitlines():
        stripped = line.strip()
        tests_match = TESTS_PROMOTION_RE.match(stripped)
        if tests_match is not None:
            promoted.add(_normalize_path(f"tests/{tests_match.group('path')}"))
            continue
        frontend_match = FRONTEND_PROMOTION_RE.match(stripped)
        if frontend_match is not None:
            promoted.add(_normalize_path(f"frontend/src/{frontend_match.group('path')}"))
    return promoted


def _focused_ci_exemptions() -> set[str]:
    """Return git-visible tests intentionally deferred from focused CI."""
    return (
        set(PYTEST_FOCUSED_CI_EXEMPTIONS)
        | set(MCP_FOCUSED_CI_EXEMPTIONS)
        | set(FRONTEND_FOCUSED_CI_EXEMPTIONS)
        | set(E2E_FOCUSED_CI_EXEMPTIONS)
    )


def _git_visible_tests() -> set[str]:
    """Return git-visible test files without pulling in ignored local scratch files."""
    return _git_visible_paths(GIT_VISIBLE_TEST_ROOTS, GIT_VISIBLE_TEST_RE)


def _require_git_worktree() -> None:
    """Skip Git-index visibility contracts when running from a source archive."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip().lower() != "true":
        pytest.skip("Git visibility contracts require a .git worktree, not a source ZIP archive")


def _git_visible_paths(roots: tuple[str, ...], path_pattern: re.Pattern[str]) -> set[str]:
    """Return git-visible paths under bounded roots using git's ignore engine."""
    _require_git_worktree()
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *roots,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git ls-files failed: {result.stderr.strip()}")
    return {
        _normalize_path(line)
        for line in result.stdout.splitlines()
        if path_pattern.match(_normalize_path(line))
        and not _normalize_path(line).endswith("/__init__.py")
    }


def _is_git_ignored(path: str) -> bool:
    """Return whether git-ignore rules hide a repository-relative path."""
    _require_git_worktree()
    normalized = _normalize_path(path)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", normalized],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise AssertionError(f"git check-ignore failed for {normalized}: {result.stderr.strip()}")


def _existing(paths: set[str]) -> set[str]:
    """Return paths that exist now so stale allowlist entries do not mask CI drift."""
    return {path for path in paths if (REPO_ROOT / path).is_file()}


def _format_paths(paths: set[str]) -> str:
    """Return a stable newline list for assertion messages."""
    return "\n".join(f"- {path}" for path in sorted(paths))


def _python_test_selectors(path: Path) -> set[str]:
    """Return function and class-scoped pytest selectors declared in a file."""
    tree = ast.parse(_read_text(path), filename=str(path))
    selectors: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            selectors.add(node.name)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    selectors.add(f"{node.name}::{child.name}")
    return selectors


def _knowledge_runtime_test_nodes() -> set[str]:
    """Return static Knowledge Runtime focused-test evidence node ids."""
    from literature_assistant.core.routers import knowledge_router

    nodes: set[str] = set()
    for kind in KNOWLEDGE_RUNTIME_PACKAGE_KINDS:
        evidence = knowledge_router._test_evidence_for_package(  # noqa: SLF001 - contract test for public evidence.
            knowledge_router.KnowledgePackageProjectionResponse(
                package_id=f"{kind}:ci-proof" if kind in {"skill_package", "config"} else kind,
                kind=kind,
                title=kind,
                source_label="ci-proof",
                status="loaded",
                available=True,
                loaded=True,
                manifest_loaded=True,
                source_path="ci-proof",
                source_hash="a" * 64,
                content_hash="b" * 64,
                updated_at="2026-06-27T00:00:00Z",
                read_endpoint="/api/agent-bridge/resource/ci-proof",
                manifest={},
            )
        )
        nodes.update(evidence.test_nodes)
    return nodes


def test_focused_ci_paths_exist() -> None:
    """Focused CI entries must point at real test files."""
    missing = {path for path in _focused_ci_tests() if not (REPO_ROOT / path).is_file()}
    assert not missing, "Focused CI references missing test files:\n" + _format_paths(missing)


def test_backend_ci_condition_covers_all_python_test_roots() -> None:
    """The backend focused job must not skip MCP tests when root tests are absent."""
    workflow = _read_text(CI_WORKFLOW)
    assert "hashFiles('tests/**/*.py', 'agent_mcp_server/tests/**/*.py')" in workflow


def test_promoted_tests_are_classified_for_focused_ci() -> None:
    """Every promoted test is either run by focused CI or explicitly deferred."""
    focused = _focused_ci_tests()
    promoted = _existing(_promoted_tests())
    visible = _git_visible_tests()
    exemptions = _focused_ci_exemptions()
    invisible = promoted - visible
    unclassified = promoted - focused - exemptions
    assert not invisible, "Promoted tests must remain git-visible:\n" + _format_paths(invisible)
    assert not unclassified, (
        "Promoted tests must be added to focused CI or to a reasoned exemption list:\n"
        + _format_paths(unclassified)
    )


def test_git_visible_tests_are_classified_for_focused_ci() -> None:
    """Git-visible tests are either run by focused CI or explicitly deferred."""
    focused = _focused_ci_tests()
    visible_tests = _git_visible_tests()
    exemptions = _focused_ci_exemptions()
    unclassified = visible_tests - focused - exemptions
    stale_exemptions = exemptions - visible_tests
    assert not unclassified, (
        "Git-visible tests must be added to focused CI or to a reasoned exemption list:\n"
        + _format_paths(unclassified)
    )
    assert not stale_exemptions, "Focused CI exemptions no longer match git-visible tests:\n" + _format_paths(
        stale_exemptions
    )


def test_docs_plans_stay_local_only() -> None:
    """Internal plan and goal-state records must stay out of the public Git tree."""
    visible_records = _git_visible_paths(
        ("docs",),
        re.compile(r"^docs/plans/[A-Za-z0-9_./-]+\.(?:json|md)$"),
    )
    assert not visible_records
    assert _is_git_ignored(WORKFLOW_SPINE_GOAL_STATE)
    assert _is_git_ignored(PRIVATE_LOCAL_PLAN_PROBE)


def test_workspace_tests_stay_local_only() -> None:
    """Workspace evaluation manifests and fixtures must stay out of public Git."""
    visible_records = _git_visible_paths(
        ("workspace_tests",),
        re.compile(r"^workspace_tests/[A-Za-z0-9_./-]+$"),
    )
    assert not visible_records
    for path in WORKSPACE_TESTS_LOCAL_ONLY_PROBES:
        assert _is_git_ignored(path)


def test_knowledge_runtime_test_evidence_nodes_resolve() -> None:
    """KRT focused-test evidence must point at real pytest node ids."""
    missing_files: set[str] = set()
    missing_selectors: set[str] = set()
    for node_id in _knowledge_runtime_test_nodes():
        path_text, separator, selector = node_id.partition("::")
        if not separator or not selector:
            missing_selectors.add(node_id)
            continue
        path = REPO_ROOT / _normalize_path(path_text)
        if not path.is_file():
            missing_files.add(path_text)
            continue
        selectors = _python_test_selectors(path)
        if selector not in selectors:
            missing_selectors.add(node_id)

    assert not missing_files, "Knowledge Runtime test evidence references missing files:\n" + _format_paths(missing_files)
    assert not missing_selectors, (
        "Knowledge Runtime test evidence references missing pytest selectors:\n"
        + _format_paths(missing_selectors)
    )


def test_current_workflow_spine_goal_lifecycle_rollup_matches_requirements() -> None:
    """Goal lifecycle rollup must stay machine-consistent with requirement rows."""
    if not (REPO_ROOT / WORKFLOW_SPINE_GOAL_STATE).is_file():
        pytest.skip("local-only workflow-spine goal-state record is not present in this checkout")
    payload = _read_json_object(REPO_ROOT / WORKFLOW_SPINE_GOAL_STATE)
    requirements = payload.get("requirements")
    assert isinstance(requirements, list) and requirements

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            raise AssertionError(f"Requirement row {index} must be an object")
        requirement_id = item.get("id")
        status = item.get("status")
        assert isinstance(requirement_id, str) and requirement_id.strip()
        assert isinstance(status, str) and status.strip()
        rows.append(item)

    top_updated_at = payload.get("updated_at")
    assert isinstance(top_updated_at, str) and top_updated_at.strip()
    rollup = payload.get("goal_lifecycle_rollup")
    assert isinstance(rollup, dict)
    status_counts = Counter(str(row["status"]) for row in rows)

    assert rollup.get("updated_at") == top_updated_at
    assert rollup.get("requirements_total") == len(rows)
    assert rollup.get("requirement_status_counts") == dict(sorted(status_counts.items()))
    assert rollup.get("latest_requirement_id") == rows[-1]["id"]
    assert rollup.get("latest_slice_id") == rows[-1]["id"]
    top_latest_slice = payload.get("latest_slice")
    if top_latest_slice is not None:
        assert top_latest_slice == rows[-1]["id"]
        latest_slice_key = (
            re.sub(r"[^a-z0-9]+", "_", top_latest_slice.lower()).strip("_") + "_slice"
        )
        latest_slice_record = payload.get(latest_slice_key)
        assert isinstance(latest_slice_record, dict)
        assert latest_slice_record.get("id") == top_latest_slice
        assert latest_slice_record.get("updated_at") == top_updated_at
        rollback = payload.get("rollback")
        assert isinstance(rollback, dict)
        latest_checkpoint_id = latest_slice_record.get("rollback_checkpoint_id")
        latest_checkpoint_path = latest_slice_record.get("rollback_checkpoint_path")
        assert isinstance(latest_checkpoint_id, str) and latest_checkpoint_id.strip()
        assert isinstance(latest_checkpoint_path, str) and latest_checkpoint_path.strip()
        assert rollback.get("latest_checkpoint_id") == latest_checkpoint_id
        assert rollback.get("latest_goal_state_checkpoint_id") == latest_checkpoint_id
        assert rollback.get("latest_checkpoint_path") == latest_checkpoint_path
        assert rollback.get("latest_goal_state_checkpoint_path") == latest_checkpoint_path
        top_mature_references = payload.get("mature_references_checked")
        latest_mature_references = latest_slice_record.get("mature_references_checked")
        assert isinstance(top_mature_references, list)
        assert isinstance(latest_mature_references, list) and latest_mature_references
        top_reference_records = [
            reference for reference in top_mature_references if isinstance(reference, dict)
        ][: len(latest_mature_references)]
        latest_reference_records = [
            reference for reference in latest_mature_references if isinstance(reference, dict)
        ]
        assert top_reference_records == latest_reference_records
        top_reference_topics = [
            reference.get("topic")
            for reference in top_reference_records
        ]
        latest_reference_topics = [reference.get("topic") for reference in latest_reference_records]
        assert top_reference_topics == latest_reference_topics
        top_changed_files = payload.get("changed_files_for_this_slice")
        latest_changed_files = latest_slice_record.get("changed_files")
        assert isinstance(top_changed_files, list) and top_changed_files
        assert isinstance(latest_changed_files, list) and latest_changed_files
        assert top_changed_files == latest_changed_files
        top_verification_commands = payload.get("verification_commands")
        latest_verification_commands = latest_slice_record.get("verification")
        assert isinstance(top_verification_commands, list) and top_verification_commands
        assert isinstance(latest_verification_commands, list) and latest_verification_commands
        assert top_verification_commands == latest_verification_commands
        top_next_actions = payload.get("next_authorized_local_actions")
        latest_next_actions = latest_slice_record.get("next_actions")
        assert isinstance(top_next_actions, list) and top_next_actions
        assert isinstance(latest_next_actions, list) and latest_next_actions
        top_next_action_records = [
            action for action in top_next_actions if isinstance(action, str) and action.strip()
        ]
        latest_next_action_records = [
            action for action in latest_next_actions if isinstance(action, str) and action.strip()
        ][: len(top_next_action_records)]
        assert top_next_action_records == latest_next_action_records
        pending_latest_verifications = [
            command
            for command in top_verification_commands
            if isinstance(command, str)
            and re.search(r"->\s*pending after\s+N\d+", command, flags=re.IGNORECASE)
        ]
        assert not pending_latest_verifications, (
            "Latest slice verification commands must record observed results, not pending placeholders:\n"
            + _format_paths(set(pending_latest_verifications))
        )
        completion_claim = payload.get("completion_claim")
        assert isinstance(completion_claim, dict)
        assert completion_claim.get("latest_slice_id") == top_latest_slice
        assert completion_claim.get("updated_at") == top_updated_at
        assert completion_claim.get("requirements_total") == rollup.get("requirements_total")
        assert completion_claim.get("requirements_status_counts") == rollup.get("requirement_status_counts")
        assert completion_claim.get("latest_requirement_id") == rollup.get("latest_requirement_id")
        assert completion_claim.get("is_goal_complete") is rollup.get("is_goal_complete")
        completion_this_slice = completion_claim.get("this_slice")
        assert isinstance(completion_this_slice, str) and completion_this_slice.strip()
        assert top_latest_slice in completion_this_slice
        completion_why_not_complete = completion_claim.get("why_not_complete")
        rollup_why_not_complete = rollup.get("why_not_complete")
        if rollup.get("can_mark_goal_complete") is False:
            assert isinstance(completion_why_not_complete, str) and completion_why_not_complete.strip()
            assert rollup_why_not_complete == completion_why_not_complete
            assert top_latest_slice in rollup_why_not_complete
        else:
            assert completion_why_not_complete in {"", None}
            assert (
                rollup_why_not_complete in {"", None}
                or rollup_why_not_complete == []
            )
        if any("0 tools remain without annotations" in command for command in top_verification_commands):
            next_actions = payload.get("next_authorized_local_actions")
            assert isinstance(next_actions, list) and next_actions
            stale_annotation_actions = [
                action
                for action in next_actions
                if isinstance(action, str) and "unannotated" in action.lower()
            ]
            assert not stale_annotation_actions
    assert rollup.get("requirements_all_proved") is all(
        row["status"] == "proved" for row in rows
    )
    assert rollup.get("requirements_all_proved_or_out_of_scope") is all(
        row["status"] in {"proved", "out_of_scope"} for row in rows
    )

    completion_blockers = rollup.get("completion_blockers")
    assert isinstance(completion_blockers, list)
    if completion_blockers:
        assert rollup.get("is_goal_complete") is False
        assert rollup.get("can_mark_goal_complete") is False
        first_blocker = completion_blockers[0]
        assert isinstance(first_blocker, dict)
        blocker_current_boundary = first_blocker.get("current_boundary")
        assert isinstance(blocker_current_boundary, str) and blocker_current_boundary.strip()
        blocker_evidence = first_blocker.get("evidence")
        assert isinstance(blocker_evidence, str) and blocker_evidence.strip()
        if isinstance(top_latest_slice, str) and top_latest_slice.strip():
            latest_slice_marker = top_latest_slice.split("-", 1)[0]
            assert latest_slice_marker in blocker_current_boundary
            assert latest_slice_marker in blocker_evidence
        blocker_missing_evidence = first_blocker.get("missing_evidence")
        assert isinstance(blocker_missing_evidence, str) and blocker_missing_evidence.strip()
        if "provider_preflight.status=proved" in blocker_missing_evidence:
            stop_boundaries = payload.get("stop_boundary")
            assert isinstance(stop_boundaries, list) and stop_boundaries
            stop_boundary_text = "\n".join(
                boundary for boundary in stop_boundaries if isinstance(boundary, str)
            ).lower()
            assert "provider preflight" in stop_boundary_text
            assert "fresh ok smoke" in stop_boundary_text
            next_actions = payload.get("next_authorized_local_actions")
            assert isinstance(next_actions, list) and next_actions
            next_action_text = "\n".join(
                action for action in next_actions if isinstance(action, str)
            ).lower()
            assert "no live provider/model" in next_action_text
            assert "provider preflight" in next_action_text
            assert "fresh ok smoke" in next_action_text

    completion_claim = payload.get("completion_claim")
    assert isinstance(completion_claim, dict)
    claim_can_mark_complete = completion_claim.get("can_mark_goal_complete")
    if claim_can_mark_complete is not None:
        assert isinstance(claim_can_mark_complete, bool)
        assert claim_can_mark_complete is rollup.get("can_mark_goal_complete")
    if rollup.get("can_mark_goal_complete") is False:
        full_goal = completion_claim.get("full_goal")
        why_not_complete = completion_claim.get("why_not_complete")
        assert isinstance(full_goal, str) and full_goal.strip()
        assert "complete" not in full_goal.lower() or full_goal.startswith("not_complete")
        assert isinstance(why_not_complete, str) and why_not_complete.strip()
        assert isinstance(rollup.get("why_not_complete"), str) and rollup.get("why_not_complete").strip()
    else:
        assert rollup.get("is_goal_complete") is True
        assert not rollup.get("completion_blockers")
        full_goal = completion_claim.get("full_goal")
        assert isinstance(full_goal, str) and full_goal.strip()
        assert full_goal.startswith("complete")


def test_current_workflow_spine_agent_workspace_projection_exposes_completion_claim() -> None:
    """Agent Workspace recovery projection must expose the real goal completion gate."""

    from literature_assistant.core.routers import agent_workspace_router

    if not (REPO_ROOT / WORKFLOW_SPINE_GOAL_STATE).is_file():
        summary = agent_workspace_router._load_goal_state_summary()
        assert summary.available is False
        assert summary.path is None
        assert summary.error == "no longrun goal-state record found"
        return

    payload = _read_json_object(REPO_ROOT / WORKFLOW_SPINE_GOAL_STATE)
    completion_claim = payload.get("completion_claim")
    assert isinstance(completion_claim, dict)
    rollup = payload.get("goal_lifecycle_rollup")
    assert isinstance(rollup, dict)

    summary = agent_workspace_router._load_goal_state_summary()

    assert summary.available is True
    assert summary.path == WORKFLOW_SPINE_GOAL_STATE
    assert summary.requirement_count == len(payload.get("requirements", []))
    assert summary.latest_requirement_id == rollup.get("latest_requirement_id")
    assert summary.completion_claim.can_mark_goal_complete is completion_claim.get("can_mark_goal_complete")
    assert summary.lifecycle_rollup.can_mark_goal_complete is rollup.get("can_mark_goal_complete")
    assert summary.completion_claim.can_mark_goal_complete is summary.lifecycle_rollup.can_mark_goal_complete
    assert summary.lifecycle_rollup.requirements_total == rollup.get("requirements_total")
    assert summary.lifecycle_rollup.requirement_status_counts == rollup.get("requirement_status_counts")
    assert summary.completion_claim.full_goal == completion_claim.get("full_goal")
    next_actions = payload.get("next_authorized_local_actions")
    assert isinstance(next_actions, list) and next_actions
    expected_next_actions = [
        action for action in next_actions if isinstance(action, str) and action.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_ACTIONS]
    assert summary.next_authorized_local_actions == expected_next_actions
    if completion_claim.get("can_mark_goal_complete") is False:
        assert any("deterministic local recovery/proof hardening" in action for action in expected_next_actions)
    else:
        assert any("requirement-to-evidence audit" in action for action in expected_next_actions)

    stop_boundaries = payload.get("stop_boundary")
    assert isinstance(stop_boundaries, list) and stop_boundaries
    expected_stop_boundaries = [
        boundary for boundary in stop_boundaries if isinstance(boundary, str) and boundary.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_BOUNDARIES]
    assert summary.stop_boundaries == expected_stop_boundaries
    if completion_claim.get("can_mark_goal_complete") is False:
        assert any("Do not call the long-run goal complete" in boundary for boundary in expected_stop_boundaries)
        assert any("live provider/model" in boundary for boundary in expected_stop_boundaries)
    else:
        assert any("Do not run additional live provider/model calls" in boundary for boundary in expected_stop_boundaries)
    assert any("Zotero DB" in boundary and "github/" in boundary for boundary in expected_stop_boundaries)
    authoritative_records = payload.get("authoritative_records")
    assert isinstance(authoritative_records, list) and authoritative_records
    expected_authoritative_records = [
        record for record in authoritative_records if isinstance(record, str) and record.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_AUTH_RECORDS]
    assert summary.authoritative_records == expected_authoritative_records
    assert "AI_WORKSPACE_GUIDE.md" in expected_authoritative_records
    assert "AGENTS.md" in expected_authoritative_records
    assert "docs/plans/autonomous-execution-framework.md" in expected_authoritative_records
    assert "docs/plans/autonomous-execution-planning-playbook.md" in expected_authoritative_records
    rollback = payload.get("rollback")
    assert isinstance(rollback, dict)
    latest_checkpoint_caveat = rollback.get("latest_checkpoint_caveat")
    assert isinstance(latest_checkpoint_caveat, str) and latest_checkpoint_caveat.strip()
    assert summary.rollback_caveat is not None
    assert latest_checkpoint_caveat.startswith(summary.rollback_caveat[:120])
    assert "rollback-checkpoints" not in summary.rollback_caveat
    assert "Restore-Item" not in summary.rollback_caveat
    mature_references = payload.get("mature_references_checked")
    assert isinstance(mature_references, list) and mature_references
    expected_mature_references = [
        reference for reference in mature_references if isinstance(reference, dict)
    ][: agent_workspace_router.MAX_GOAL_STATE_MATURE_REFERENCES]
    assert len(summary.mature_references_checked) == len(expected_mature_references)
    assert summary.mature_references_checked[0].source == expected_mature_references[0].get("source")
    assert summary.mature_references_checked[0].topic == expected_mature_references[0].get("topic")
    expected_reference_status = expected_mature_references[0].get("status")
    assert isinstance(expected_reference_status, str)
    assert expected_reference_status.startswith(summary.mature_references_checked[0].status[:120])
    changed_files = payload.get("changed_files_for_this_slice")
    assert isinstance(changed_files, list) and changed_files
    expected_changed_files = [
        agent_workspace_router._redact_text(item).strip()[:240]
        for item in changed_files
        if isinstance(item, str) and item.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_CHANGED_FILES]
    assert summary.changed_files_for_this_slice == expected_changed_files
    verification_commands = payload.get("verification_commands")
    assert isinstance(verification_commands, list) and verification_commands
    expected_verification_commands = [
        agent_workspace_router._redact_text(item).strip()[:240]
        for item in verification_commands
        if isinstance(item, str) and item.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_VERIFICATION_COMMANDS]
    assert summary.verification_commands == expected_verification_commands
    serialized_goal_state = summary.model_dump_json()
    assert "rollback-checkpoints" not in serialized_goal_state
    assert "Restore-Item" not in serialized_goal_state
    why_not_complete = completion_claim.get("why_not_complete")
    if summary.completion_claim.can_mark_goal_complete is False:
        assert isinstance(why_not_complete, str) and why_not_complete.strip()
        assert summary.completion_claim.why_not_complete is not None
        assert why_not_complete.startswith(summary.completion_claim.why_not_complete[:120])
    else:
        assert why_not_complete in {"", None}
        assert summary.completion_claim.why_not_complete is None
    if summary.completion_claim.can_mark_goal_complete is False:
        assert summary.completion_claim.why_not_complete
        assert summary.lifecycle_rollup.completion_blockers
        expected_blockers = [
            blocker for blocker in rollup.get("completion_blockers", []) if isinstance(blocker, dict)
        ][: agent_workspace_router.MAX_GOAL_LIFECYCLE_BLOCKERS]
        assert expected_blockers
        first_expected_blocker = expected_blockers[0]
        first_summary_blocker = summary.lifecycle_rollup.completion_blockers[0]
        first_expected_id = first_expected_blocker.get("id")
        assert isinstance(first_expected_id, str) and first_expected_id.strip()
        assert first_summary_blocker.id == (
            agent_workspace_router._redact_text(first_expected_id).strip()[:160]
        )
        expected_limits = {
            "status": 120,
            "requirement_surface": 240,
            "missing_evidence": 240,
            "current_boundary": 240,
        }
        for field_name, max_chars in expected_limits.items():
            expected_value = first_expected_blocker.get(field_name)
            assert isinstance(expected_value, str) and expected_value.strip()
            assert getattr(first_summary_blocker, field_name) == (
                agent_workspace_router._redact_text(expected_value).strip()[:max_chars]
            )
        first_expected_evidence = first_expected_blocker.get("evidence")
        assert isinstance(first_expected_evidence, str) and first_expected_evidence.strip()
        assert first_summary_blocker.evidence == (
            agent_workspace_router._redact_text(first_expected_evidence).strip()[:240]
        )
        expected_completion_rule = rollup.get("machine_readable_completion_rule")
        assert isinstance(expected_completion_rule, str) and expected_completion_rule.strip()
        assert summary.lifecycle_rollup.machine_readable_completion_rule == (
            agent_workspace_router._redact_text(expected_completion_rule).strip()[:240]
        )
        expected_rollup_why_not_raw = rollup.get("why_not_complete")
        if isinstance(expected_rollup_why_not_raw, str):
            expected_rollup_why_not = [
                agent_workspace_router._redact_text(expected_rollup_why_not_raw).strip()[:240]
            ]
        else:
            assert isinstance(expected_rollup_why_not_raw, list)
            expected_rollup_why_not = [
                agent_workspace_router._redact_text(item).strip()[:240]
                for item in expected_rollup_why_not_raw
                if isinstance(item, str) and item.strip()
            ][: agent_workspace_router.MAX_GOAL_STATE_BOUNDARIES]
        assert expected_rollup_why_not
        assert summary.lifecycle_rollup.why_not_complete == expected_rollup_why_not
