from __future__ import annotations

from tools.eval.wiki_wave15_end_to_end_dry_run import run_wave15_end_to_end_dry_run


def test_wave15_end_to_end_dry_run_stays_in_temp_workspace() -> None:
    payload = run_wave15_end_to_end_dry_run()

    assert payload["mode"] == "temp_workspace_no_runtime_artifacts"
    assert payload["migration"]["would_write"] is False
    assert payload["migration"]["candidate_count"] == 1
    assert payload["compile_preview"]["created"] == 1
    assert payload["compile_write"]["created"] == 1
    assert payload["query_hit_count"] >= 1
    assert payload["exploration"]["success"] is True
    assert payload["exploration"]["relative_path"] == "exploration/how-does-laser-welding-affect-stability.md"
    assert payload["doctor"]["counts"]["error"] == 0
    assert payload["backup_plan"]["would_write"] is False
    assert payload["backup_plan"]["file_count"] >= 3
