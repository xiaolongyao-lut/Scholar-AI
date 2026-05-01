from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


OPEN_STATUSES = {"待执行", "进行中", "open", "in-progress"}
DEFAULT_MIN_SELF_DECISIONS = int(os.environ.get("SQUAD_MIN_SELF_DECISIONS", "2"))
ALLOWED_STOP_REASONS = {
    "user-stop",
    "approval-boundary",
    "external-blocker",
    "session-limit",
    "cli-handoff",
    "plan-clear-no-safe-next",
}
SELF_DECISION_EXEMPT_REASONS = {
    "user-stop",
    "approval-boundary",
    "external-blocker",
    "cli-handoff",
}
USER_STOP_PATTERN = re.compile(r"\b(stop|idle|pause)\b|停止|暂停|收工", re.IGNORECASE)
STOP_REASON_PATTERN = re.compile(r"\[STOP_REASON:([^\]]+)\]", re.IGNORECASE)
SELF_DECISION_PATTERN = re.compile(r"\[SELF_DECISIONS:(\d+)\]", re.IGNORECASE)
DECISION_FILE_PATTERN = re.compile(
    r"\.squad[\\/]+decisions[\\/]+inbox[\\/]+copilot-[^\\/]+\.md$", re.IGNORECASE
)
APPLY_PATCH_FILE_PATTERN = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def allow(system_message: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"continue": True}
    if system_message:
        result["systemMessage"] = system_message
    return result


def deny_tool(reason: str, additional_context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    if additional_context:
        output["hookSpecificOutput"]["additionalContext"] = additional_context
    return output


def block_stop(reason: str) -> dict[str, Any]:
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "decision": "block",
            "reason": reason,
        },
    }


def repo_root_from_cwd(cwd: str | None) -> Path:
    if not cwd:
        return Path.cwd()
    path = Path(cwd).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".kilo").exists() or (candidate / ".github").exists() or (candidate / ".git").exists():
            return candidate
    return path


def normalize_path(value: str | Path, repo_root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve(strict=False)


def state_dir(repo_root: Path) -> Path:
    return repo_root / ".squad" / "state" / "stop-gate"


def state_path(repo_root: Path, session_id: str | None) -> Path:
    safe_session_id = session_id or "unknown-session"
    return state_dir(repo_root) / f"{safe_session_id}.json"


def default_state(session_id: str | None) -> dict[str, Any]:
    return {
        "sessionId": session_id or "unknown-session",
        "minSelfDecisions": DEFAULT_MIN_SELF_DECISIONS,
        "selfDecisionCount": 0,
        "decisionFiles": [],
    }


def load_state(repo_root: Path, session_id: str | None) -> dict[str, Any]:
    path = state_path(repo_root, session_id)
    if not path.exists():
        return default_state(session_id)

    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("sessionId", session_id or "unknown-session")
    state.setdefault("minSelfDecisions", DEFAULT_MIN_SELF_DECISIONS)
    state.setdefault("decisionFiles", [])
    state["selfDecisionCount"] = len(state["decisionFiles"])
    return state


def save_state(repo_root: Path, session_id: str | None, state: dict[str, Any]) -> None:
    directory = state_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = state_path(repo_root, session_id)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def decision_path_if_countable(path: Path, repo_root: Path) -> str | None:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return None

    relative_str = relative.as_posix()
    if DECISION_FILE_PATTERN.search(relative_str):
        return relative_str
    return None


def extract_decision_files(tool_name: str | None, tool_input: dict[str, Any], repo_root: Path) -> set[str]:
    touched: set[str] = set()

    if tool_name == "create_file":
        file_path = tool_input.get("filePath")
        if isinstance(file_path, str):
            normalized = normalize_path(file_path, repo_root)
            relative = decision_path_if_countable(normalized, repo_root)
            if relative:
                touched.add(relative)

    elif tool_name == "apply_patch":
        patch_text = tool_input.get("input")
        if isinstance(patch_text, str):
            for match in APPLY_PATCH_FILE_PATTERN.findall(patch_text):
                normalized = normalize_path(match.strip(), repo_root)
                relative = decision_path_if_countable(normalized, repo_root)
                if relative:
                    touched.add(relative)

    return touched


def initialize_session_state(payload: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    state = default_state(payload.get("sessionId"))
    save_state(repo_root, payload.get("sessionId"), state)
    return state


def update_self_decision_count(payload: dict[str, Any]) -> dict[str, Any]:
    repo_root = repo_root_from_cwd(payload.get("cwd"))
    session_id = payload.get("sessionId")
    state = load_state(repo_root, session_id)
    touched = extract_decision_files(payload.get("tool_name"), payload.get("tool_input") or {}, repo_root)
    if touched:
        state["decisionFiles"] = sorted({*state.get("decisionFiles", []), *touched})
        state["selfDecisionCount"] = len(state["decisionFiles"])
        save_state(repo_root, session_id, state)
        return allow(
            f"Strict stop gate tracked self-decisions: {state['selfDecisionCount']} / {state['minSelfDecisions']}"
        )
    save_state(repo_root, session_id, state)
    return allow()


def detect_active_plan(repo_root: Path) -> Path | None:
    env_path = os.environ.get("SQUAD_ACTIVE_PLAN")
    if env_path:
        candidate = Path(env_path)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.exists():
            return candidate.resolve()

    plan_dir = repo_root / ".kilo" / "plans"
    if not plan_dir.exists():
        return None

    plans = list(plan_dir.glob("*.md"))
    if not plans:
        return None

    def score(path: Path) -> tuple[int, float]:
        name = path.name.lower()
        priority = 2 if "master-plan" in name else 1 if "master" in name else 0
        return (priority, path.stat().st_mtime)

    return max(plans, key=score)


def find_open_tasks(plan_path: Path | None) -> list[str]:
    if plan_path is None or not plan_path.exists():
        return []

    open_tasks: list[str] = []
    for raw_line in plan_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|TASK-"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        task_id = cells[0]
        if any(cell in OPEN_STATUSES for cell in cells[1:]):
            open_tasks.append(task_id)
    return open_tasks


def transcript_has_explicit_user_stop(transcript_path: str | None) -> bool:
    if not transcript_path:
        return False
    path = Path(transcript_path)
    if not path.exists():
        return False

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    for line in reversed(lines[-80:]):
        if USER_STOP_PATTERN.search(line):
            return True
    return False


def session_start_response() -> dict[str, Any]:
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Strict stop gate active: do not call task_complete unless the summary includes "
                "[STOP_REASON:<reason>] and [SELF_DECISIONS:<n>]. Allowed reasons are user-stop, approval-boundary, "
                "external-blocker, session-limit, cli-handoff, and plan-clear-no-safe-next. "
                "Autonomous completion requires the session self-decision floor (default 2 unique copilot decision inbox files). "
                "Provisional go, PASS WITH NOTES, build/test success, and slice completion are not valid stop reasons."
            ),
        },
    }


def handle_pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("tool_name") != "task_complete":
        return allow()

    tool_input = payload.get("tool_input") or {}
    summary = str(tool_input.get("summary") or "")
    match = STOP_REASON_PATTERN.search(summary)
    if not match:
        return deny_tool(
            "Strict stop gate: task_complete requires [STOP_REASON:<reason>] in the summary.",
            "Continue the current run, classify the stop reason explicitly, and only retry task_complete when the reason is valid.",
        )

    reason = match.group(1).strip().lower()
    if reason not in ALLOWED_STOP_REASONS:
        return deny_tool(
            f"Strict stop gate: stop reason '{reason}' is not allowed.",
            "Allowed reasons: user-stop, approval-boundary, external-blocker, session-limit, cli-handoff, plan-clear-no-safe-next.",
        )

    self_decision_match = SELF_DECISION_PATTERN.search(summary)
    if not self_decision_match:
        return deny_tool(
            "Strict stop gate: task_complete requires [SELF_DECISIONS:<n>] in the summary.",
            "Report the session self-decision count explicitly before retrying task_complete.",
        )

    claimed_self_decisions = int(self_decision_match.group(1))

    repo_root = repo_root_from_cwd(payload.get("cwd"))
    active_plan = detect_active_plan(repo_root)
    open_tasks = find_open_tasks(active_plan)
    state = load_state(repo_root, payload.get("sessionId"))
    actual_self_decisions = int(state.get("selfDecisionCount", 0))
    min_self_decisions = int(state.get("minSelfDecisions", DEFAULT_MIN_SELF_DECISIONS))

    if claimed_self_decisions != actual_self_decisions:
        return deny_tool(
            f"Strict stop gate: claimed SELF_DECISIONS={claimed_self_decisions} does not match tracked count {actual_self_decisions}.",
            "Self-decision count is measured by the current session's unique `.squad/decisions/inbox/copilot-*.md` files.",
        )

    if reason not in SELF_DECISION_EXEMPT_REASONS and actual_self_decisions < min_self_decisions:
        return deny_tool(
            f"Strict stop gate: self-decision floor not met ({actual_self_decisions} / {min_self_decisions}).",
            "Autonomous completion requires enough recorded self-decisions before the run may stop.",
        )

    if reason == "plan-clear-no-safe-next" and open_tasks:
        plan_name = active_plan.name if active_plan else "<unknown plan>"
        task_preview = ", ".join(open_tasks[:5])
        return deny_tool(
            f"Strict stop gate: {plan_name} still has open tasks ({task_preview}).",
            "You may not finish the run while the active master plan still contains open TASK-* rows.",
        )

    if reason == "user-stop" and not transcript_has_explicit_user_stop(payload.get("transcript_path")):
        return deny_tool(
            "Strict stop gate: user-stop requires an explicit user stop/idle signal in the transcript.",
            "Use user-stop only when the user actually asked to stop, pause, or idle the run.",
        )

    return allow(
        (
            f"Strict stop gate accepted: STOP_REASON={reason} | SELF_DECISIONS={actual_self_decisions}/{min_self_decisions}"
            + (f" | active plan={active_plan.name}" if active_plan else "")
        )
    )


def handle_post_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    return update_self_decision_count(payload)


def handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("stop_hook_active"):
        return allow()

    repo_root = repo_root_from_cwd(payload.get("cwd"))
    active_plan = detect_active_plan(repo_root)
    open_tasks = find_open_tasks(active_plan)
    if open_tasks:
        plan_name = active_plan.name if active_plan else "<unknown plan>"
        task_preview = ", ".join(open_tasks[:5])
        return block_stop(
            f"Strict stop gate: do not stop yet — {plan_name} still has open tasks ({task_preview})."
        )
    return allow()


def main() -> None:
    try:
        payload = read_payload()
        event_name = payload.get("hookEventName")
        repo_root = repo_root_from_cwd(payload.get("cwd"))
        if event_name == "SessionStart":
            initialize_session_state(payload, repo_root)
            emit(session_start_response())
            return
        if event_name == "PreToolUse":
            emit(handle_pre_tool_use(payload))
            return
        if event_name == "PostToolUse":
            emit(handle_post_tool_use(payload))
            return
        if event_name == "Stop":
            emit(handle_stop(payload))
            return
        emit(allow())
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:  # fail-open to avoid bricking the session
        emit(allow(f"squad governance hook degraded: {exc}"))


if __name__ == "__main__":
    main()