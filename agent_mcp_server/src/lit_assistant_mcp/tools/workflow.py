"""Workflow and artifact tools for controlled local agent workflows."""

import time
from pathlib import Path
from typing import Any

from ..audit import AuditLog
from ..result import safe_result
from ..workflow_runtime.interpreter import ToolCallable, WorkflowInterpreter
from ..workflow_runtime.workspace import ArtifactWorkspace


class WorkflowTools:
    """Controlled workflow and artifact tool implementations."""

    def __init__(
        self,
        workspace: ArtifactWorkspace,
        tool_registry: dict[str, ToolCallable],
        audit: AuditLog | None = None,
    ) -> None:
        """Create workflow tools.

        Args:
            workspace: Artifact workspace constrained to workflow artifacts.
            tool_registry: Tool callables that JSON workflows may invoke.
            audit: Optional audit log.
        """
        if not tool_registry:
            raise ValueError("tool_registry must not be empty")
        self.workspace = workspace
        self.tool_registry = dict(tool_registry)
        self.interpreter = WorkflowInterpreter(tool_registry=self.tool_registry)
        self.audit = audit

    def create_plan(self, goal: str, suggested_steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create a workflow plan skeleton without executing it."""
        started = time.perf_counter()
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        if suggested_steps is not None and not isinstance(suggested_steps, list):
            raise ValueError("suggested_steps must be an array when provided")
        steps = suggested_steps or [
            {
                "id": "check_status",
                "tool": "literature.config_status",
                "args": {},
            }
        ]
        plan = {
            "goal": goal.strip(),
            "workflow": {
                "id": self._slug(goal),
                "input": {},
                "steps": steps,
            },
            "allowed_tools": sorted(self.tool_registry),
        }
        result = safe_result(plan)
        return self._finish("workflow.create_plan", {"goal": goal[:200]}, result, started, "planned")

    def write_json_workflow(
        self,
        path: str,
        workflow: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a JSON workflow artifact."""
        started = time.perf_counter()
        if not isinstance(workflow, dict):
            raise ValueError("workflow must be an object")
        result = safe_result(self.workspace.write_json(path, workflow, overwrite=overwrite))
        return self._finish("workflow.write_json_workflow", {"path": path}, result, started, "artifact_write")

    def run_json_workflow(
        self,
        workflow: dict[str, Any] | None = None,
        path: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an inline or artifact-backed JSON workflow."""
        started = time.perf_counter()
        if workflow is None and path is None:
            raise ValueError("workflow or path is required")
        if workflow is not None and path is not None:
            raise ValueError("provide workflow or path, not both")
        if input_data is not None and not isinstance(input_data, dict):
            raise ValueError("input_data must be an object when provided")
        loaded_workflow = workflow if workflow is not None else self.workspace.read_json(path or "")
        if not isinstance(loaded_workflow, dict):
            raise ValueError("workflow must be an object")
        result = self.interpreter.run(loaded_workflow, input_data=input_data)
        return self._finish(
            "workflow.run_json_workflow",
            {"path": path or "<inline>", "workflow_id": loaded_workflow.get("id")},
            result,
            started,
            "workflow_run",
        )

    def write_markdown(self, path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        """Write a Markdown artifact under the workflow workspace."""
        started = time.perf_counter()
        if not path.lower().endswith((".md", ".markdown")):
            raise ValueError("markdown artifact path must end with .md or .markdown")
        result = safe_result(self.workspace.write_text(path, content, overwrite=overwrite))
        return self._finish("artifact.write_markdown", {"path": path}, result, started, "artifact_write")

    def read_artifact(self, path: str, max_chars: int = 120_000) -> dict[str, Any]:
        """Read a text artifact from the workflow workspace."""
        started = time.perf_counter()
        result = safe_result(self.workspace.read_text(path, max_chars=max_chars))
        return self._finish("artifact.read_artifact", {"path": path}, result, started, "artifact_read")

    def list_artifacts(self, max_entries: int = 200) -> dict[str, Any]:
        """List artifacts from the workflow workspace."""
        started = time.perf_counter()
        result = safe_result({"artifacts": self.workspace.list_artifacts(max_entries=max_entries)})
        return self._finish("artifact.list_artifacts", {"max_entries": max_entries}, result, started, "artifact_list")

    def _finish(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        started: float,
        reason: str,
    ) -> dict[str, Any]:
        if self.audit is not None:
            self.audit.log(
                tool_name=tool_name,
                args_summary=args,
                touched_paths=[],
                allow_block_reason=reason,
                result_preview=str(result.get("data")),
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=result.get("error_code"),
            )
        return result

    def _slug(self, value: str) -> str:
        cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-")[:64] or "workflow"


def create_default_workflow_tools(
    repo_root: Path,
    tool_registry: dict[str, ToolCallable],
    audit_root: Path | None = None,
) -> WorkflowTools:
    """Create WorkflowTools with the default artifact workspace."""
    audit = AuditLog(audit_root) if audit_root is not None else None
    return WorkflowTools(
        workspace=ArtifactWorkspace(repo_root=repo_root),
        tool_registry=tool_registry,
        audit=audit,
    )
