#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib import error, request

KEY_PATTERN = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$")
NOTE_PREFIX = "## 联通性备注("
TEAM_USABLE_VERDICTS = {
    "ok",
    "reachable_but_error",
    "reachable_endpoint_or_payload_issue",
}
STRICT_FAIL_VERDICTS = {"auth_failed", "unreachable"}


@dataclass
class Group:
    index: int
    key_var: str
    key_value: str
    base_var: str
    base_url: str
    base_line_index: int


@dataclass
class ProbeResult:
    index: int
    keyVar: str
    baseVar: str
    baseUrl: str
    method: str
    status: Optional[int]
    errorClass: Optional[str]
    verdict: str
    maskedKey: str


def mask_key(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def classify(status: Optional[int], _error_class: Optional[str]) -> str:
    if status is None:
        return "unreachable"
    if 200 <= status <= 299:
        return "ok"
    if status in (401, 403):
        return "auth_failed"
    if status in (404, 405, 422):
        return "reachable_endpoint_or_payload_issue"
    if 400 <= status <= 599:
        return "reachable_but_error"
    return "reachable_unknown"


def build_team_summary(results: List[ProbeResult]) -> dict:
    counts: dict[str, int] = {}
    usable_entries: list[dict] = []
    strict_failures: list[dict] = []

    for result in results:
        counts[result.verdict] = counts.get(result.verdict, 0) + 1
        entry = {
            "index": result.index,
            "keyVar": result.keyVar,
            "baseVar": result.baseVar,
            "baseUrl": result.baseUrl,
            "verdict": result.verdict,
            "method": result.method,
            "status": result.status,
            "errorClass": result.errorClass,
            "maskedKey": result.maskedKey,
        }
        if result.verdict in TEAM_USABLE_VERDICTS:
            usable_entries.append(entry)
        if result.verdict in STRICT_FAIL_VERDICTS:
            strict_failures.append(entry)

    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "teamReady": bool(usable_entries),
        "counts": counts,
        "usableEntries": usable_entries,
        "strictFailures": strict_failures,
    }


def determine_exit_code(results: List[ProbeResult], strict: bool) -> int:
    if strict and any(result.verdict in STRICT_FAIL_VERDICTS for result in results):
        return 2
    return 0


def parse_groups(lines: List[str]) -> List[Group]:
    groups: List[Group] = []
    current_key_var: Optional[str] = None
    current_key_value: Optional[str] = None

    for i, raw in enumerate(lines):
        m = KEY_PATTERN.match(raw)
        if not m:
            continue

        var = m.group(1).strip()
        val = m.group(2).strip()

        if var.endswith("_API_KEY") or var == "API_KEY":
            current_key_var = var
            current_key_value = val
            continue

        if (var.endswith("_BASE_URL") or var == "BASE_URL") and current_key_var and current_key_value:
            groups.append(
                Group(
                    index=len(groups),
                    key_var=current_key_var,
                    key_value=current_key_value,
                    base_var=var,
                    base_url=val,
                    base_line_index=i,
                )
            )

    return groups


def _http_call(url: str, method: str, token: str, timeout: int, body: bytes | None = None) -> tuple[Optional[int], Optional[str]]:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "safe-env-connectivity-check/1.0"}
    if method == "POST":
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, method=method, headers=headers, data=body)

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return int(resp.getcode()), None
    except error.HTTPError as e:
        return int(e.code), None
    except error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return None, "timeout"
        return None, "network_error"
    except TimeoutError:
        return None, "timeout"
    except OSError:
        return None, "os_error"


def probe(group: Group, timeout: int) -> ProbeResult:
    base = group.base_url.strip().rstrip("/")

    # 兼容性优先：常见 OpenAI/ARK 风格先试 /models；失败再试对 base 的 POST {}
    try_chain = [
        ("GET", f"{base}/models", None),
        ("POST", base, b"{}"),
    ]

    picked_method = "GET"
    picked_status: Optional[int] = None
    picked_error: Optional[str] = None

    for method, url, body in try_chain:
        status, err = _http_call(url, method, group.key_value, timeout, body)
        picked_method = method
        picked_status = status
        picked_error = err

        # 只要有 HTTP 状态码说明链路可达，立即使用该结果
        if status is not None:
            break

    verdict = classify(picked_status, picked_error)
    return ProbeResult(
        index=group.index,
        keyVar=group.key_var,
        baseVar=group.base_var,
        baseUrl=group.base_url,
        method=picked_method,
        status=picked_status,
        errorClass=picked_error,
        verdict=verdict,
        maskedKey=mask_key(group.key_value),
    )


def build_note(result: ProbeResult) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    if result.status is not None:
        detail = f"HTTP {result.status}"
    else:
        detail = result.errorClass or "unknown"
    return (
        f"## 联通性备注({date_str}): 结论={result.verdict}，探测={result.method}，"
        f"结果={detail}，key={result.maskedKey}"
    )


def extract_key_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        m = KEY_PATTERN.match(line)
        if not m:
            continue
        var = m.group(1).strip()
        if var.endswith("_API_KEY") or var == "API_KEY":
            out.append(line.rstrip("\n"))
    return out


def write_notes(env_path: Path, original_lines: List[str], groups: List[Group], results: List[ProbeResult]) -> Path:
    notes_by_base_line = {g.base_line_index: build_note(r) for g, r in zip(groups, results)}

    new_lines: List[str] = []
    i = 0
    while i < len(original_lines):
        line = original_lines[i]
        new_lines.append(line)

        if i in notes_by_base_line:
            # 删除紧随 BASE_URL 之后已有的旧联通备注
            j = i + 1
            while j < len(original_lines) and original_lines[j].strip().startswith(NOTE_PREFIX):
                j += 1
            new_lines.append(notes_by_base_line[i] + "\n")
            i = j
            continue

        i += 1

    # 安全保护：写回前校验 key 行完全一致
    before_keys = extract_key_lines(original_lines)
    after_keys = extract_key_lines(new_lines)
    if before_keys != after_keys:
        raise RuntimeError("检测到 API key 行发生变化，已中止写回以保护密钥参数。")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = env_path.with_name(f"{env_path.name}.backup_connectivity_{stamp}")
    backup.write_text("".join(original_lines), encoding="utf-8")
    env_path.write_text("".join(new_lines), encoding="utf-8")
    return backup


def print_summary(results: List[ProbeResult]) -> None:
    print("idx | keyVar | baseVar | method | status/error | verdict")
    print("-" * 92)
    for r in results:
        status_part = str(r.status) if r.status is not None else (r.errorClass or "unknown")
        print(
            f"{r.index:>3} | {r.keyVar:<24} | {r.baseVar:<24} | {r.method:<5} | {status_part:<12} | {r.verdict}"
        )


def print_team_summary(summary: dict) -> None:
    counts = summary.get("counts", {})
    counts_display = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
    print(f"Team ready:   {summary.get('teamReady', False)}")
    print(f"Verdict stats: {counts_display}")
    print(f"Usable for team: {len(summary.get('usableEntries', []))}")
    print(f"Strict failures: {len(summary.get('strictFailures', []))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe .env connectivity checker (never edits key params).")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--timeout", type=int, default=12, help="HTTP timeout seconds")
    parser.add_argument("--json", default=".connectivity_results.json", help="Output json result file")
    parser.add_argument("--summary-json", default=".team_api_health.json", help="Output team summary json file")
    parser.add_argument("--no-write", action="store_true", help="Do not write notes back to .env")
    parser.add_argument("--strict", action="store_true", help="Return exit code 2 when auth_failed/unreachable results exist")
    args = parser.parse_args()

    env_path = Path(args.env).resolve()
    if not env_path.exists():
        raise FileNotFoundError(f".env not found: {env_path}")

    original_lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    groups = parse_groups(original_lines)
    if not groups:
        print("No API_KEY + BASE_URL groups found.")
        return 0

    results = [probe(g, timeout=args.timeout) for g in groups]

    json_path = Path(args.json).resolve()
    json_path.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = build_team_summary(results)
    summary_json_path = Path(args.summary_json).resolve()
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    backup_path = None
    if not args.no_write:
        backup_path = write_notes(env_path, original_lines, groups, results)

    print_summary(results)
    print()
    print_team_summary(summary)
    print(f"\nResults JSON: {json_path}")
    print(f"Team JSON:    {summary_json_path}")
    if backup_path:
        print(f"Env backup:   {backup_path}")
    print("Safety guard: API key lines were verified unchanged before write.")
    return determine_exit_code(results, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
