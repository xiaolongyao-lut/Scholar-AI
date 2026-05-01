"""Predicate-level pin for tools/squad/_score-quality.py (round 22 brief 150304).

Discharges goal-drift §4 self-explore lane (saturation regime — every other
.squad/tools/ test slot has been claimed by parallel-Morpheus instances within
1-4 minutes of identification this round-window). The sibling
`test_check-eval-rubric.py` is the only existing scaffold in tools/squad/, so
the `_score-quality.py` predicate harness is virgin.

What this pins (the 7 documented branches of `_score-quality.main`):
  T1  stdin is non-JSON garbage          → _fail_closed exit 1
  T2  stdin is empty / whitespace        → exit 0, {quality_score:null, quality_pass:false}
  T3  response_text missing / non-string → exit 0, null/false envelope
  T4  citations field is not a list      → _fail_closed exit 1
  T5  src.quality_heuristic absent       → _fail_closed exit 1 (ImportError branch)
  T6  score() raises mid-call            → _fail_closed exit 1, error carries exc class+msg
  T7  happy path                         → exit 0, asdict(result) + bool(overall_pass)

Pure read-only on the source; this test file is the one new artifact this
round. The `_score-quality.py` script itself is untouched (per CLAUDE.md
"surgical changes" and the round-protocol malware-analysis rule of NOT
augmenting code merely because it was read).

Loader strategy: the source filename uses a hyphen (`_score-quality.py`),
which is not a legal Python identifier, so we load it via
`importlib.util.spec_from_file_location` and exercise `main()` directly with
monkeypatched stdin/stdout/sys.modules.

Run: py -3 -m pytest tools/squad/test__score_quality.py -q
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent / "_score-quality.py"


def _load_module():
    """Fresh import of `_score-quality.py` with a stable module name.

    Each test gets its own module instance so the `from src.quality_heuristic
    import score` inside main() re-resolves against the current sys.modules
    state (we mutate sys.modules per-test).
    """
    spec = importlib.util.spec_from_file_location("score_quality_under_test", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class _FakeResult:
    overall_pass: bool
    citation_score: float = 0.0
    coherence_score: float = 0.0


def _install_fake_quality(monkeypatch, *, score_fn=None, raise_on_call: Exception | None = None):
    """Inject a synthetic `src.quality_heuristic` so main() finds a deterministic score()."""
    pkg = types.ModuleType("src")
    pkg.__path__ = []  # mark as package
    sub = types.ModuleType("src.quality_heuristic")

    def default_score(response_text, citations, gold_text=None):
        return _FakeResult(overall_pass=True, citation_score=1.0, coherence_score=0.9)

    if raise_on_call is not None:
        def _raiser(*_a, **_kw):
            raise raise_on_call
        sub.score = _raiser
    else:
        sub.score = score_fn or default_score

    monkeypatch.setitem(sys.modules, "src", pkg)
    monkeypatch.setitem(sys.modules, "src.quality_heuristic", sub)


def _run_with_stdin(monkeypatch, stdin_text: str) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    mod = _load_module()
    rc = mod.main()
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# T1: stdin is non-JSON garbage → fail-closed exit 1
# ---------------------------------------------------------------------------
def test_T1_stdin_non_json_fails_closed(monkeypatch):
    _install_fake_quality(monkeypatch)  # not reached, but harmless
    rc, out = _run_with_stdin(monkeypatch, "this is not json {{{")
    assert rc == 1
    payload = json.loads(out)
    assert payload["quality_score"] is None
    assert payload["quality_pass"] is False
    assert "stdin not valid JSON" in payload["error"]


# ---------------------------------------------------------------------------
# T2: empty / whitespace stdin → empty payload path → exit 0, null envelope
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("blob", ["", "   ", "\n\n", "\t \r\n"])
def test_T2_empty_stdin_returns_null_envelope(monkeypatch, blob):
    _install_fake_quality(monkeypatch)
    rc, out = _run_with_stdin(monkeypatch, blob)
    assert rc == 0
    payload = json.loads(out)
    assert payload == {"quality_score": None, "quality_pass": False}


# ---------------------------------------------------------------------------
# T3: response_text missing / non-string / blank → null envelope, exit 0
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    {},                                    # field missing
    {"response_text": None},               # explicit null
    {"response_text": 42},                  # int instead of str
    {"response_text": ["chunked"]},         # list instead of str
    {"response_text": ""},                  # empty string
    {"response_text": "    \n\t"},          # whitespace-only string
])
def test_T3_missing_or_blank_response_text(monkeypatch, payload):
    _install_fake_quality(monkeypatch)
    rc, out = _run_with_stdin(monkeypatch, json.dumps(payload))
    assert rc == 0
    body = json.loads(out)
    assert body == {"quality_score": None, "quality_pass": False}


# ---------------------------------------------------------------------------
# T4: citations field present but not a list → fail-closed exit 1
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_citations", [
    "not-a-list",
    {"first": "Smith2023"},
    42,
    True,
])
def test_T4_non_list_citations_fails_closed(monkeypatch, bad_citations):
    _install_fake_quality(monkeypatch)
    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({"response_text": "valid answer text", "citations": bad_citations}),
    )
    assert rc == 1
    body = json.loads(out)
    assert body["quality_score"] is None
    assert body["quality_pass"] is False
    assert "citations field is not a list" in body["error"]


# ---------------------------------------------------------------------------
# T5: src.quality_heuristic missing → ImportError branch fires fail-closed
# ---------------------------------------------------------------------------
def test_T5_missing_quality_heuristic_module(monkeypatch):
    # Block import: stub `src` package with NO `quality_heuristic` submodule.
    pkg = types.ModuleType("src")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "src", pkg)
    # Ensure any cached real module is gone.
    monkeypatch.delitem(sys.modules, "src.quality_heuristic", raising=False)

    # Also block sys.path lookup of a real `src/quality_heuristic.py` by
    # registering a finder that vetoes that exact dotted name.
    import importlib.abc
    import importlib.machinery

    class _Veto(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname == "src.quality_heuristic":
                # Return a spec with no loader → ImportError on exec.
                raise ImportError(f"vetoed by test: {fullname}")
            return None

    monkeypatch.setattr(sys, "meta_path", [_Veto()] + sys.meta_path)

    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({"response_text": "hello", "citations": []}),
    )
    assert rc == 1
    body = json.loads(out)
    assert body["quality_score"] is None
    assert body["quality_pass"] is False
    assert "cannot import quality_heuristic" in body["error"]


# ---------------------------------------------------------------------------
# T6: score() raises mid-call → fail-closed surfaces type+message
# ---------------------------------------------------------------------------
def test_T6_score_raises_is_caught(monkeypatch):
    _install_fake_quality(monkeypatch, raise_on_call=ValueError("boom-detail-42"))
    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({"response_text": "hello world", "citations": ["Smith2023"]}),
    )
    assert rc == 1
    body = json.loads(out)
    assert body["quality_score"] is None
    assert body["quality_pass"] is False
    assert "score() raised" in body["error"]
    assert "ValueError" in body["error"]
    assert "boom-detail-42" in body["error"]


# ---------------------------------------------------------------------------
# T7: happy path → asdict(result) + bool(overall_pass), exit 0
# ---------------------------------------------------------------------------
def test_T7_happy_path_emits_asdict_envelope(monkeypatch):
    captured = {}

    def custom_score(response_text, citations, gold_text=None):
        captured["response_text"] = response_text
        captured["citations"] = citations
        captured["gold_text"] = gold_text
        return _FakeResult(overall_pass=True, citation_score=0.83, coherence_score=0.91)

    _install_fake_quality(monkeypatch, score_fn=custom_score)
    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({
            "response_text": "Welds form columnar grains [Smith, 2023].",
            "citations": ["Smith2023", "Jones2021"],
        }),
    )
    assert rc == 0
    body = json.loads(out)
    assert body["quality_pass"] is True
    qs = body["quality_score"]
    assert qs == {
        "overall_pass": True,
        "citation_score": 0.83,
        "coherence_score": 0.91,
    }
    # score() received the unmodified payload + gold_text=None contract
    assert captured == {
        "response_text": "Welds form columnar grains [Smith, 2023].",
        "citations": ["Smith2023", "Jones2021"],
        "gold_text": None,
    }


def test_T7b_overall_pass_false_propagates(monkeypatch):
    _install_fake_quality(
        monkeypatch,
        score_fn=lambda r, c, gold_text=None: _FakeResult(overall_pass=False),
    )
    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({"response_text": "weak answer", "citations": []}),
    )
    assert rc == 0
    body = json.loads(out)
    assert body["quality_pass"] is False
    # bool() coercion contract: even though overall_pass is False, the score
    # envelope is still populated (not the empty-stdin null path).
    assert body["quality_score"] is not None
    assert body["quality_score"]["overall_pass"] is False


# ---------------------------------------------------------------------------
# Citations default-to-empty-list contract: omitted citations key with valid
# response_text must NOT trip the non-list fail-closed branch.
# ---------------------------------------------------------------------------
def test_citations_omitted_treated_as_empty_list(monkeypatch):
    seen = {}

    def custom_score(response_text, citations, gold_text=None):
        seen["citations"] = citations
        return _FakeResult(overall_pass=True)

    _install_fake_quality(monkeypatch, score_fn=custom_score)
    rc, out = _run_with_stdin(
        monkeypatch,
        json.dumps({"response_text": "answer body"}),
    )
    assert rc == 0
    assert seen["citations"] == []
    body = json.loads(out)
    assert body["quality_pass"] is True
