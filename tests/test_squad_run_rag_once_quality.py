from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_RAG_ONCE = REPO_ROOT / "tools" / "squad" / "run-rag-once.ps1"


def test_run_rag_once_records_quality_score_for_each_question() -> None:
    script = RUN_RAG_ONCE.read_text(encoding="utf-8")

    assert "quality_score" in script and "$null" in script
    assert "quality_pass" in script and "$false" in script
    assert "_score-quality.py" in script


def test_run_rag_once_quality_score_runs_after_response_and_before_pass() -> None:
    script = RUN_RAG_ONCE.read_text(encoding="utf-8")

    response_index = script.index("$qResult.response_text")
    scorer_index = script.index("$qualityInput = @{")
    pass_index = script.index("$qResult.passed =")

    assert response_index < scorer_index < pass_index
    assert "$qResult.passed" in script and "$qResult.quality_pass" in script
