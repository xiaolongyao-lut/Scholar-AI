"""Behavior contracts for repairing invalid claim-cache rows."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from layers.claim_cache import ClaimCache


def _seed_claim_cache_row(
    db_path: Path,
    chunk_signature: str,
    claims_json: str,
    *,
    access_count: int,
) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO claims_cache
                (chunk_signature, doc_id, claims_json, access_count)
            VALUES (?, ?, ?, ?)
            """,
            (chunk_signature, "corrupt-paper", claims_json, access_count),
        )
        connection.commit()


def _read_claim_cache_row(db_path: Path, chunk_signature: str) -> tuple[str, int]:
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT claims_json, access_count
            FROM claims_cache
            WHERE chunk_signature = ?
            """,
            (chunk_signature,),
        ).fetchone()

    assert row is not None
    return str(row[0]), int(row[1])


def _read_claim_cache_identity(
    db_path: Path,
    chunk_signature: str,
) -> tuple[str, str, str]:
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT claims_json, llm_model, cached_at
            FROM claims_cache
            WHERE chunk_signature = ?
            """,
            (chunk_signature,),
        ).fetchone()

    assert row is not None
    return str(row[0]), str(row[1]), str(row[2])


def test_claim_cache_keeps_first_valid_write(tmp_path: Path) -> None:
    db_path = tmp_path / "claims.db"
    cache = ClaimCache(db_path=str(db_path))
    chunk_signature = "shared-signature"
    first_claims = [
        {"claim_id": "first", "subject": "Laser", "confidence": 0.9}
    ]
    second_claims = [
        {"claim_id": "second", "subject": "Optics", "confidence": 0.7}
    ]
    first_cached_at = "2001-02-03 04:05:06"

    cache.save_claims(
        chunk_signature,
        first_claims,
        metadata={"doc_id": "first-paper", "llm_model": "first-model"},
    )
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            UPDATE claims_cache
            SET cached_at = ?
            WHERE chunk_signature = ?
            """,
            (first_cached_at, chunk_signature),
        )
        connection.commit()

    first_identity = _read_claim_cache_identity(db_path, chunk_signature)
    cache.save_claims(
        chunk_signature,
        second_claims,
        metadata={"doc_id": "second-paper", "llm_model": "second-model"},
    )

    assert _read_claim_cache_identity(db_path, chunk_signature) == first_identity
    assert cache.get_claims(chunk_signature) == first_claims


def test_claim_cache_replaces_malformed_json_row(tmp_path: Path) -> None:
    db_path = tmp_path / "claims.db"
    cache = ClaimCache(db_path=str(db_path))
    chunk_signature = "malformed-json"
    malformed_json = '[{"claim_id": "broken"}'
    initial_access_count = 4
    repaired_claims = [
        {"claim_id": "repaired", "subject": "Laser", "confidence": 0.9}
    ]
    _seed_claim_cache_row(
        db_path,
        chunk_signature,
        malformed_json,
        access_count=initial_access_count,
    )

    assert cache.get_claims(chunk_signature) is None
    assert _read_claim_cache_row(db_path, chunk_signature) == (
        malformed_json,
        initial_access_count,
    )

    cache.save_claims(
        chunk_signature,
        repaired_claims,
        metadata={"doc_id": "repaired-paper", "llm_model": "test-model"},
    )

    assert cache.get_claims(chunk_signature) == repaired_claims
    _, access_count = _read_claim_cache_row(db_path, chunk_signature)
    assert access_count == initial_access_count + 1


def test_claim_cache_replaces_list_with_non_object_row(tmp_path: Path) -> None:
    db_path = tmp_path / "claims.db"
    cache = ClaimCache(db_path=str(db_path))
    chunk_signature = "list-with-non-object"
    invalid_claims_json = '[{"claim_id": "valid"}, 7]'
    initial_access_count = 6
    repaired_claims = [
        {"claim_id": "repaired", "subject": "Optics", "confidence": 0.8}
    ]
    _seed_claim_cache_row(
        db_path,
        chunk_signature,
        invalid_claims_json,
        access_count=initial_access_count,
    )

    assert cache.get_claims(chunk_signature) is None
    assert _read_claim_cache_row(db_path, chunk_signature) == (
        invalid_claims_json,
        initial_access_count,
    )

    cache.save_claims(
        chunk_signature,
        repaired_claims,
        metadata={"doc_id": "repaired-paper", "llm_model": "test-model"},
    )

    assert cache.get_claims(chunk_signature) == repaired_claims
    _, access_count = _read_claim_cache_row(db_path, chunk_signature)
    assert access_count == initial_access_count + 1
