"""claim-collision-scan: per-run evidence collector for .squad/claims/ race-risk audit.

Read-only diagnostic. Walks .squad/claims/*.claim, classifies each file
(ok / size_anomaly / parse_error), and detects session-id collisions
(>=2 files sharing the same session= line). Emits one JSON artifact under
.squad/diagnostics/ via .tmp + os.replace atomic write.

Pool entry (filed round 4): "claim-collision-scan diagnostic" at
.squad/identity/requirement-pool.md (41/50, SELF-APPLIED-NEXT-ROUND).

Pre-conditions and contract:
  - Does NOT modify any .claim file.
  - Does NOT modify claim-self-explore.ps1 (HIGH-RISK per audit; Owner-only).
  - Pure stdlib: pathlib, re, json, collections, datetime, os, sys.
  - Exit 0 always (read-only diagnostic; missing claims dir => total=0).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "v0"
EXPECTED_SIZE = 52  # current census: all 9 claims are exactly 52 bytes
SESSION_RE = re.compile(r"^session=(.+)$", re.MULTILINE)
TS_RE = re.compile(r"^ts=(.+)$", re.MULTILINE)


def repo_root() -> Path:
    # tools/squad/diag/<this>.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def classify(path: Path) -> tuple[str, str | None, str | None]:
    """Return (status, session_id, ts) for a single .claim file.

    status in {"ok", "size_anomaly", "parse_error"}.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:  # pragma: no cover - permission edge
        return ("parse_error", None, None)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ("parse_error", None, None)

    sm = SESSION_RE.search(text)
    tm = TS_RE.search(text)
    session = sm.group(1).strip() if sm else None
    ts = tm.group(1).strip() if tm else None

    if session is None or ts is None:
        return ("parse_error", session, ts)
    if size != EXPECTED_SIZE:
        return ("size_anomaly", session, ts)
    return ("ok", session, ts)


def atomic_write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)


def main() -> int:
    root = repo_root()
    claims_dir = root / ".squad" / "claims"
    out_dir = root / ".squad" / "diagnostics"

    by_status = {"ok": 0, "size_anomaly": 0, "parse_error": 0}
    session_files: dict[str, list[str]] = defaultdict(list)
    total = 0

    if claims_dir.is_dir():
        for entry in sorted(claims_dir.iterdir()):
            if not entry.is_file() or entry.suffix != ".claim":
                continue
            total += 1
            status, session, _ts = classify(entry)
            by_status[status] += 1
            if session is not None:
                session_files[session].append(entry.name)

    collisions = [
        {"session_id": sid, "files": sorted(files)}
        for sid, files in sorted(session_files.items())
        if len(files) >= 2
    ]

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    payload = {
        "captured_at": captured_at,
        "claims_dir": str(claims_dir),
        "total_claims": total,
        "by_status": by_status,
        "collisions": collisions,
        "schema_version": SCHEMA_VERSION,
    }

    out_path = out_dir / f"claim-collision-{captured_at}.json"
    atomic_write_json(out_path, payload)

    print(
        f"claim-collision-scan: total={total}, "
        f"anomalies={by_status['size_anomaly'] + by_status['parse_error']}, "
        f"collisions={len(collisions)}, wrote={out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
