from __future__ import annotations

import ast
from collections import Counter
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITIGNORE = REPO_ROOT / ".gitignore"
WORKFLOW_SPINE_GOAL_STATE = (
    "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
)
PRIVATE_LOCAL_PLAN_PROBE = "docs/plans/private-local-audit-placeholder.md"
WIKI_EVAL_SMOKE_VISIBLE_FIXTURES = (
    "workspace_tests/fixtures/wiki_eval_smoke/manifest.json",
    "workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/baseline-contrast.md",
    "workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/paper-a.md",
)
WIKI_GRAPH_DOCTOR_LOCAL_ONLY_PROBE = (
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
GIT_VISIBLE_PUBLIC_RECORD_ROOTS = ("docs/plans",)

PYTEST_FOCUSED_CI_EXEMPTIONS: dict[str, str] = {
    "tests/conftest.py": "pytest support module, not a standalone CI target",
    "tests/live_api_chat_full_writing_chain_smoke.py": "live API smoke remains opt-in outside deterministic CI",
    "tests/live_api_chat_knowledge_context_receipt_smoke.py": "live Knowledge Runtime context-receipt smoke remains opt-in outside deterministic CI",
    "tests/test_api_probe_semantics.py": "legacy API probe contract outside the current KRT/N33 focused gate",
    "tests/test_build_windows_exe_script.py": "Windows packaging helper is outside Linux CI focused gate",
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
    "tests/test_pyinstaller_hiddenimports.py": "PyInstaller hidden-import regression outside Linux CI focused gate",
    "tests/test_pyproject_runtime_metadata.py": "packaging metadata regression outside the current KRT/N33 focused gate",
    "tests/test_rag_ablation_evaluator.py": "RAG ablation evaluator regression outside the current KRT/N33 focused gate",
    "tests/test_rag_structured_sibling_inclusion.py": "RAG sibling inclusion regression outside the current KRT/N33 focused gate",
    "tests/test_release_secret_scan.py": "release secret-scan regression outside the current KRT/N33 focused gate",
    "tests/test_search_refs_contract.py": "search refs contract outside the current KRT/N33 focused gate",
    "tests/test_skill_export.py": "skill export regression outside the current KRT/N33 focused gate",
    "tests/test_smoke_frozen_host_appdata.py": "frozen Windows smoke outside Linux CI focused gate",
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


def _git_visible_paths(roots: tuple[str, ...], path_pattern: re.Pattern[str]) -> set[str]:
    """Return git-visible paths under bounded roots using git's ignore engine."""
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


def test_current_workflow_spine_goal_state_is_git_visible() -> None:
    """Current workflow-spine goal-state is public-visible while private plans stay local-only."""
    visible_records = _git_visible_paths(
        GIT_VISIBLE_PUBLIC_RECORD_ROOTS,
        re.compile(r"^docs/plans/[A-Za-z0-9_./-]+\.(?:json|md)$"),
    )
    assert (REPO_ROOT / WORKFLOW_SPINE_GOAL_STATE).is_file()
    assert WORKFLOW_SPINE_GOAL_STATE in visible_records
    assert not _is_git_ignored(WORKFLOW_SPINE_GOAL_STATE)
    assert _is_git_ignored(PRIVATE_LOCAL_PLAN_PROBE)


def test_selected_workspace_fixtures_are_path_explicit() -> None:
    """Selected workspace fixtures must be complete without exposing adjacent local fixtures."""
    for path in WIKI_EVAL_SMOKE_VISIBLE_FIXTURES:
        assert (REPO_ROOT / path).is_file()
        assert not _is_git_ignored(path)
    assert _is_git_ignored(WIKI_GRAPH_DOCTOR_LOCAL_ONLY_PROBE)


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


def test_current_workflow_spine_agent_workspace_projection_exposes_completion_claim() -> None:
    """Agent Workspace recovery projection must expose the real goal completion gate."""

    from literature_assistant.core.routers import agent_workspace_router

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
    assert summary.completion_claim.full_goal == completion_claim.get("full_goal")
    next_actions = payload.get("next_authorized_local_actions")
    assert isinstance(next_actions, list) and next_actions
    expected_next_actions = [
        action for action in next_actions if isinstance(action, str) and action.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_ACTIONS]
    assert summary.next_authorized_local_actions == expected_next_actions
    assert any("deterministic local recovery/proof hardening" in action for action in expected_next_actions)

    stop_boundaries = payload.get("stop_boundary")
    assert isinstance(stop_boundaries, list) and stop_boundaries
    expected_stop_boundaries = [
        boundary for boundary in stop_boundaries if isinstance(boundary, str) and boundary.strip()
    ][: agent_workspace_router.MAX_GOAL_STATE_BOUNDARIES]
    assert summary.stop_boundaries == expected_stop_boundaries
    assert any("Do not call the long-run goal complete" in boundary for boundary in expected_stop_boundaries)
    assert any("live provider/model" in boundary for boundary in expected_stop_boundaries)
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
    assert summary.mature_references_checked[0].status == expected_mature_references[0].get("status")
    serialized_goal_state = summary.model_dump_json()
    assert "rollback-checkpoints" not in serialized_goal_state
    assert "Restore-Item" not in serialized_goal_state
    why_not_complete = completion_claim.get("why_not_complete")
    assert isinstance(why_not_complete, str) and why_not_complete.strip()
    assert summary.completion_claim.why_not_complete is not None
    assert why_not_complete.startswith(summary.completion_claim.why_not_complete[:120])
    if summary.completion_claim.can_mark_goal_complete is False:
        assert summary.completion_claim.why_not_complete
        assert summary.lifecycle_rollup.completion_blockers
