#!/usr/bin/env python3
"""test_queued_age_report — contract tests for tools/squad/queued-age-report.py.

Read-only predicate-level coverage of the bucket logic, regex scrape, and
atomic-write contract. Source filename has a hyphen; loaded via importlib.

Anchors:
  - Spec §4.7 atomic-write hardening (.tmp + os.replace).
  - Goal-drift §4 line 88 (no silent failures): assert squad-CLI failure path
    returns (None, error_str) so callers can surface the error.
  - Round 22 brief 150134 self-explore virgin-axis (eval byte-stable 120m).
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SRC = HERE / "queued-age-report.py"


def _load():
    spec = importlib.util.spec_from_file_location("queued_age_report", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qar = _load()


class BucketForTests(unittest.TestCase):
    def test_none_age_returns_question_mark(self):
        self.assertEqual(qar.bucket_for(None), "?")

    def test_zero_minutes_in_first_bucket(self):
        self.assertEqual(qar.bucket_for(0), "<30m")

    def test_29_minutes_in_first_bucket(self):
        self.assertEqual(qar.bucket_for(29), "<30m")

    def test_30_minutes_crosses_into_second(self):
        self.assertEqual(qar.bucket_for(30), "30-120m")

    def test_119_minutes_in_second(self):
        self.assertEqual(qar.bucket_for(119), "30-120m")

    def test_120_minutes_in_third(self):
        self.assertEqual(qar.bucket_for(120), "2-12h")

    def test_just_under_12h_in_third(self):
        self.assertEqual(qar.bucket_for(12 * 60 - 1), "2-12h")

    def test_12h_boundary_overflows_to_open_bucket(self):
        # 12*60=720 → hi for "2-12h" is 720, lo<=age<hi means 720 NOT in it
        self.assertEqual(qar.bucket_for(720), ">12h")

    def test_very_large_age_in_open_bucket(self):
        self.assertEqual(qar.bucket_for(9999), ">12h")


class BucketsTableTests(unittest.TestCase):
    def test_buckets_have_expected_names_and_order(self):
        names = [b[0] for b in qar.BUCKETS]
        self.assertEqual(names, ["<30m", "30-120m", "2-12h", ">12h"])

    def test_last_bucket_has_open_upper_bound(self):
        self.assertIsNone(qar.BUCKETS[-1][2])

    def test_first_bucket_starts_at_zero(self):
        self.assertEqual(qar.BUCKETS[0][1], 0)


class ListQueuedIdsTests(unittest.TestCase):
    def test_squad_cli_missing_returns_error(self):
        with mock.patch.object(qar.subprocess, "run", side_effect=FileNotFoundError("squad")):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("squad CLI failure", err)

    def test_squad_cli_timeout_returns_error(self):
        timeout_exc = qar.subprocess.TimeoutExpired(cmd="squad", timeout=30)
        with mock.patch.object(qar.subprocess, "run", side_effect=timeout_exc):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("squad CLI failure", err)

    def test_nonzero_exit_returns_error(self):
        fake = mock.MagicMock()
        fake.returncode = 7
        fake.stdout = b""
        fake.stderr = b"db locked"
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(ids)
        self.assertIn("exited 7", err)
        self.assertIn("db locked", err)

    def test_parses_uuids_from_stdout(self):
        fake = mock.MagicMock()
        fake.returncode = 0
        fake.stdout = (
            b"[task 6908f3cc-7251-46f4-ae7f-8b30478721d1] queued (tank-r3)\n"
            b"[task dec0e7a2-dd14-4f0a-a133-2870b6e1a182] queued (tank-r5)\n"
            b"some other line\n"
        )
        fake.stderr = b""
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(err)
        self.assertEqual(
            ids,
            [
                "6908f3cc-7251-46f4-ae7f-8b30478721d1",
                "dec0e7a2-dd14-4f0a-a133-2870b6e1a182",
            ],
        )

    def test_no_matches_returns_empty_list_not_none(self):
        fake = mock.MagicMock()
        fake.returncode = 0
        fake.stdout = b"no queued tasks\n"
        fake.stderr = b""
        with mock.patch.object(qar.subprocess, "run", return_value=fake):
            ids, err = qar.list_queued_ids()
        self.assertIsNone(err)
        self.assertEqual(ids, [])


class EnrichFromDbTests(unittest.TestCase):
    def test_empty_ids_returns_empty(self):
        self.assertEqual(qar.enrich_from_db([]), [])

    def test_missing_db_returns_empty(self):
        # Swap the module-level DB_PATH to a guaranteed-nonexistent location.
        bogus = Path(__file__).parent / "_does_not_exist_db.sqlite3"
        self.assertFalse(bogus.exists())
        with mock.patch.object(qar, "DB_PATH", bogus):
            self.assertEqual(qar.enrich_from_db(["abc"]), [])


class AtomicWriteContractTests(unittest.TestCase):
    """The producer must use .tmp + os.replace per Spec §4.7."""

    def test_source_uses_tmp_staging(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(".json.tmp", text)

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp_path, out_path)", text)

    def test_source_uses_readonly_sqlite_uri(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("mode=ro", text)
        self.assertIn("uri=True", text)


if __name__ == "__main__":
    unittest.main()
