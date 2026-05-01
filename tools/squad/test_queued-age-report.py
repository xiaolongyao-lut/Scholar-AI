#!/usr/bin/env python3
"""test_queued-age-report.py — predicate-level contract tests for queued-age-report.

Companion artifact for `tools/squad/queued-age-report.py` (round-25 brief 150135
self-explore discharge). Source filename has a hyphen so we load it via
importlib.util.spec_from_file_location (cf. precedent at
tools/squad/test_check-eval-rubric.py).

Tests are pure-stdlib, read-only, and offline (no `squad` CLI or sqlite required).
External I/O is injected by monkey-patching the loaded module's globals
(subprocess.run, DB_PATH, DIAG_DIR) — same shape as round-22 lane tests.

Spec anchors:
  - requirement-pool 39/50 (queued-age diagnostic)
  - CLAUDE.md §4.7 atomic-write hardening (assert .tmp + os.replace observed)
  - goal-drift §4 line 88 ban-on-silent-failure (assert error path returns 1)

Exit 0 iff every contract holds; non-zero otherwise (loop-observable).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().with_name("queued-age-report.py")


def _load():
    spec = importlib.util.spec_from_file_location("queued_age_report", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SOURCE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qar = _load()


class BucketForTests(unittest.TestCase):
    """bucket_for() must classify ages into the four documented buckets."""

    def test_none_age_is_unknown(self):
        self.assertEqual(qar.bucket_for(None), "?")

    def test_zero_age_is_under_30(self):
        self.assertEqual(qar.bucket_for(0), "<30m")

    def test_just_under_30_is_under_30(self):
        self.assertEqual(qar.bucket_for(29), "<30m")

    def test_30_lands_in_30_to_120(self):
        self.assertEqual(qar.bucket_for(30), "30-120m")

    def test_just_under_120_is_30_to_120(self):
        self.assertEqual(qar.bucket_for(119), "30-120m")

    def test_120_is_2_to_12h(self):
        self.assertEqual(qar.bucket_for(120), "2-12h")

    def test_just_under_720_is_2_to_12h(self):
        self.assertEqual(qar.bucket_for(719), "2-12h")

    def test_720_is_over_12h(self):
        self.assertEqual(qar.bucket_for(720), ">12h")

    def test_huge_age_is_over_12h(self):
        self.assertEqual(qar.bucket_for(10_000), ">12h")


class BucketsConstantTests(unittest.TestCase):
    """The four-bucket schema is load-bearing — guard against silent reorder."""

    def test_four_buckets_present(self):
        self.assertEqual(len(qar.BUCKETS), 4)

    def test_bucket_order_is_documented(self):
        names = [b[0] for b in qar.BUCKETS]
        self.assertEqual(names, ["<30m", "30-120m", "2-12h", ">12h"])

    def test_open_ended_top_bucket(self):
        # Only the last bucket should have None upper bound.
        for name, lo, hi in qar.BUCKETS[:-1]:
            self.assertIsNotNone(hi, f"bucket {name} must be bounded")
        self.assertIsNone(qar.BUCKETS[-1][2])


class ListQueuedIdsTests(unittest.TestCase):
    """list_queued_ids() must scrape the CLI output and surface failures."""

    def test_parses_task_id_lines(self):
        sample = (
            b"[task 11111111-2222-3333-4444-555555555555] queued some title\n"
            b"[task aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee] queued other title\n"
            b"noise line\n"
        )
        fake = mock.Mock(returncode=0, stdout=sample, stderr=b"")
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(err)
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(len(i) == 36 for i in ids))

    def test_squad_cli_missing_returns_error(self):
        with mock.patch.object(
            qar.subprocess, "run", side_effect=FileNotFoundError("squad")
        ):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("squad CLI failure", err)

    def test_squad_cli_timeout_returns_error(self):
        with mock.patch.object(
            qar.subprocess,
            "run",
            side_effect=qar.subprocess.TimeoutExpired(cmd="squad", timeout=30),
        ):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("squad CLI failure", err)

    def test_nonzero_exit_returns_error(self):
        fake = mock.Mock(returncode=2, stdout=b"", stderr=b"db locked")
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("squad exited 2", err)

    def test_empty_output_returns_empty_list(self):
        fake = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(err)
        self.assertEqual(ids, [])


class EnrichFromDbTests(unittest.TestCase):
    """enrich_from_db() must early-return when the DB is missing or ids empty."""

    def test_empty_ids_returns_empty(self):
        # Should not even try to open the DB.
        with mock.patch.object(qar.sqlite3, "connect", side_effect=AssertionError):
            self.assertEqual(qar.enrich_from_db([]), [])

    def test_missing_db_returns_empty(self):
        bogus = Path(tempfile.gettempdir()) / "queued-age-report-no-such.db"
        if bogus.exists():
            bogus.unlink()
        with mock.patch.object(qar, "DB_PATH", bogus):
            self.assertEqual(qar.enrich_from_db(["abc"]), [])


class MainAtomicWriteTests(unittest.TestCase):
    """main() must round-trip JSON via .tmp + os.replace per CLAUDE.md §4.7."""

    def test_main_writes_atomic_json(self):
        with tempfile.TemporaryDirectory() as td:
            diag_dir = Path(td) / "diagnostics"
            sample_id = "11111111-2222-3333-4444-555555555555"
            cli_out = mock.Mock(
                returncode=0,
                stdout=f"[task {sample_id}] queued probe\n".encode(),
                stderr=b"",
            )
            with mock.patch.object(qar, "DIAG_DIR", diag_dir), \
                 mock.patch.object(qar.subprocess, "run", return_value=cli_out), \
                 mock.patch.object(qar, "enrich_from_db", return_value=[
                     (sample_id, "probe", "tank", None, qar.time.time().__int__() - 60 * 45),
                 ]), \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO) as buf:
                rc = qar.main()
            self.assertEqual(rc, 0)
            files = list(diag_dir.glob("queued-age-*.json"))
            self.assertEqual(len(files), 1, "expected exactly one report file")
            self.assertFalse(
                any(p.suffix == ".tmp" for p in diag_dir.iterdir()),
                "no .tmp file should remain after os.replace",
            )
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "v0")
            self.assertEqual(payload["total_queued"], 1)
            self.assertEqual(payload["total_enriched"], 1)
            # 45m bucket → 30-120m
            self.assertEqual(payload["by_bucket"]["30-120m"], 1)
            self.assertEqual(payload["by_assigned"]["tank"], 1)
            self.assertIn("oldest_n", payload)
            self.assertEqual(payload["oldest_n"][0]["id"], sample_id)
            self.assertIn("queued-age-report:", buf.getvalue())

    def test_main_returns_1_on_cli_failure(self):
        with mock.patch.object(
            qar.subprocess, "run", side_effect=FileNotFoundError("squad")
        ), mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
            rc = qar.main()
        self.assertEqual(rc, 1, "main must surface CLI failure as exit 1")
        self.assertIn("queued-age-report: ERROR", err.getvalue())


class ModuleSurfaceTests(unittest.TestCase):
    """Lock the public surface so silent renames break loudly."""

    def test_expected_callables_present(self):
        for name in ("bucket_for", "list_queued_ids", "enrich_from_db", "main"):
            self.assertTrue(callable(getattr(qar, name, None)),
                            f"missing public callable: {name}")

    def test_db_path_under_squad_messages(self):
        self.assertTrue(str(qar.DB_PATH).endswith(os.path.join(".squad", "messages.db")))

    def test_diag_dir_under_squad_diagnostics(self):
        self.assertTrue(str(qar.DIAG_DIR).endswith(os.path.join(".squad", "diagnostics")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
