"""Registered-tool-only JSON workflow interpreter."""

import json
import re
import time
from collections.abc import Callable
from typing import Any

from ..redaction import SecretRedactor
from ..result import safe_result
from .expressions import ExpressionEvaluator

ToolCallable = Callable[..., dict[str, Any]]

MAX_STEPS: int = 20
MAX_CONTEXT_BYTES: int = 1024 * 1024
MAX_WORKFLOW_SECONDS: int = 45
STEP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class WorkflowInterpreter:
    """Execute bounded JSON workflows through a fixed tool registry."""

    def __init__(
        self,
        tool_registry: dict[str, ToolCallable],
        evaluator: ExpressionEvaluator | None = None,
    ) -> None:
        """Create a workflow interpreter.

        Args:
            tool_registry: Callable registry keyed by exposed tool name.
            evaluator: Optional expression evaluator.
        """
        if not tool_registry:
            raise ValueError("tool_registry must not be empty")
        self.tool_registry = dict(tool_registry)
        self.evaluator = evaluator or ExpressionEvaluator()

    def run(self, workflow: dict[str, Any], input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a workflow and return redacted step results."""
        started = time.perf_counter()
        self._validate_workflow(workflow)
        context: dict[str, Any] = {
            "input": input_data or workflow.get("input", {}),
            "steps": {},
            "vars": {},
        }
        continue_on_error = bool(workflow.get("continue_on_error", False))

        for raw_step in workflow["steps"]:
            self._check_deadline(started)
            step = self._validate_step(raw_step)
            step_started = time.perf_counter()
            tool = self.tool_registry.get(step["tool"])
            if tool is None:
                return safe_result(
                    {
                        "completed_steps": context["steps"],
                        "failed_step": step["id"],
                    },
                    error=True,
                    error_code="workflow_tool_not_allowed",
                    message=f"workflow tool is not registered: {step['tool']}",
                )
            args: dict[str, Any] = {}
            try:
                args = self.evaluator.evaluate(step.get("args", {}), context)
                if not isinstance(args, dict):
                    raise ValueError("step args must evaluate to an object")
                result = tool(**args)
                result = self._redact_result(result)
            except Exception as exc:
                result = safe_result(
                    None,
                    error=True,
                    error_code="workflow_step_exception",
                    message=str(exc),
                )

            context["steps"][step["id"]] = {
                "tool": step["tool"],
                "args": self._redact_value(args),
                "result": result,
                "duration_ms": int((time.perf_counter() - step_started) * 1000),
            }
            self._check_context_size(context)
            if result.get("is_error") is True and not continue_on_error:
                return safe_result(
                    {
                        "completed_steps": context["steps"],
                        "failed_step": step["id"],
                    },
                    error=True,
                    error_code="workflow_step_failed",
                    message=f"step failed: {step['id']}",
                )

        return safe_result(
            {
                "workflow_id": workflow.get("id"),
                "steps": context["steps"],
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )

    def _validate_workflow(self, workflow: dict[str, Any]) -> None:
        if not isinstance(workflow, dict):
            raise ValueError("workflow must be an object")
        steps = workflow.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("workflow.steps must be a non-empty array")
        if len(steps) > MAX_STEPS:
            raise ValueError(f"workflow may contain at most {MAX_STEPS} steps")
        input_data = workflow.get("input", {})
        if not isinstance(input_data, dict):
            raise ValueError("workflow.input must be an object when provided")

    def _validate_step(self, step: Any) -> dict[str, Any]:
        if not isinstance(step, dict):
            raise ValueError("workflow step must be an object")
        step_id = step.get("id")
        tool = step.get("tool")
        if not isinstance(step_id, str) or STEP_ID_RE.fullmatch(step_id) is None:
            raise ValueError("step.id must be a stable identifier")
        if not isinstance(tool, str) or not tool:
            raise ValueError("step.tool must be a non-empty string")
        args = step.get("args", {})
        if not isinstance(args, dict):
            raise ValueError("step.args must be an object when provided")
        return {"id": step_id, "tool": tool, "args": args}

    def _redact_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return safe_result(result)
        serialized = json.dumps(result, ensure_ascii=False)
        redacted = SecretRedactor.scan(serialized)
        loaded = json.loads(redacted)
        if not isinstance(loaded, dict):
            return safe_result(loaded)
        return loaded

    def _redact_value(self, value: Any) -> Any:
        serialized = json.dumps(value, ensure_ascii=False)
        return json.loads(SecretRedactor.scan(serialized))

    def _check_context_size(self, context: dict[str, Any]) -> None:
        if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_BYTES:
            raise ValueError(f"workflow context exceeds {MAX_CONTEXT_BYTES} bytes")

    def _check_deadline(self, started: float) -> None:
        if time.perf_counter() - started > MAX_WORKFLOW_SECONDS:
            raise TimeoutError(f"workflow exceeded {MAX_WORKFLOW_SECONDS} seconds")
