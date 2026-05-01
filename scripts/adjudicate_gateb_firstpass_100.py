from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "eval_audit"
DOC_STORE_PATH = ROOT / "output" / "doc_store" / "laser_welding_109.json"
ZOTERO_DB_PATH = Path(r"D:\zotero\zoterodate\zotero.sqlite")

IN_HIGH = ARTIFACT_DIR / "gateb_firstpass_100_high_confidence.jsonl"
IN_REVIEW = ARTIFACT_DIR / "gateb_firstpass_100_review_needed.jsonl"
IN_POOLS = ARTIFACT_DIR / "gateb_firstpass_100_review_pools.jsonl"

OUT_HIGH = IN_HIGH
OUT_REVIEW = IN_REVIEW
OUT_ALL = ARTIFACT_DIR / "gateb_firstpass_100_all.jsonl"
OUT_QRELS = ARTIFACT_DIR / "gateb_firstpass_100_qrels.tsv"
OUT_MANIFEST = ARTIFACT_DIR / "gateb_firstpass_100_manifest.json"


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    text = re.sub(r"\.pdf$", "", text)
    text = re.sub(r"^[^\-]+?\s+-\s+\d{4}\s+-\s+", "", text)
    text = re.sub(r"^\d{4}\s+-\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _load_zotero_titles() -> dict[str, str]:
    connection = sqlite3.connect(f"file:{ZOTERO_DB_PATH}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT
                i.itemID,
                idv.value
            FROM items i
            JOIN itemData id ON id.itemID = i.itemID
            JOIN fields f ON f.fieldID = id.fieldID AND f.fieldName = 'title'
            JOIN itemDataValues idv ON idv.valueID = id.valueID
            WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY i.itemID
            """
        ).fetchall()
    finally:
        connection.close()
    return {str(item_id): title for item_id, title in rows if title}


def _extract_zotero_item_id(record: dict) -> str:
    notes = str(record.get("notes", ""))
    match = re.search(r"zotero_item_id=(\d+)", notes)
    if not match:
        raise RuntimeError(f"Missing zotero_item_id in notes for {record.get('query_id')}")
    return match.group(1)


def _write_qrels(path: Path, records: list[dict]) -> None:
    rows = ["query_id\titeration\tdoc_id\trelevance"]
    for record in records:
        if bool(record.get("no_gold")):
            continue
        query_id = str(record.get("query_id", "")).strip()
        for qrel in record.get("qrels", []):
            rows.append(
                f"{query_id}\t0\t{str(qrel.get('doc_id', '')).strip()}\t{int(qrel.get('relevance', 0))}"
            )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _adjudicate_record(
    record: dict,
    pool_record: dict,
    zotero_titles: dict[str, str],
    doc_store: dict[str, dict],
    judged_at: str,
) -> dict:
    zotero_item_id = _extract_zotero_item_id(record)
    zotero_title = zotero_titles.get(zotero_item_id)
    if not zotero_title:
        raise RuntimeError(f"Missing Zotero title for item {zotero_item_id} ({record['query_id']})")

    query_norm = _normalize_title(str(record["query_text"]))
    zotero_norm = _normalize_title(zotero_title)
    if query_norm != zotero_norm:
        raise RuntimeError(
            f"Query/Zotero title mismatch for {record['query_id']}: "
            f"{record['query_text']!r} vs {zotero_title!r}"
        )

    qrels: list[dict] = []
    positive_doc_ids: list[str] = []
    for candidate in pool_record["candidates"]:
        doc_id = str(candidate["doc_id"]).strip()
        if doc_id not in doc_store:
            raise RuntimeError(f"Candidate doc_id not found in doc store: {doc_id} ({record['query_id']})")
        relevance = 2 if _normalize_title(str(candidate["title"])) == query_norm else 0
        if relevance == 2:
            positive_doc_ids.append(doc_id)
        qrels.append(
            {
                "doc_id": doc_id,
                "relevance": relevance,
                "source_hint": str(candidate["source_hint"]),
                "judged_at": judged_at,
            }
        )

    no_gold = not positive_doc_ids
    if no_gold:
        notes = (
            "Adjudicated exact-title review against real Zotero metadata and repo review pool; "
            "no candidate title normalized to the Zotero-backed query title, so this remains a true no-gold."
        )
        notes_for_future_tolf = (
            f"Zotero item {zotero_item_id} confirmed real literature, but none of the {len(qrels)} pooled corpus "
            "docs matched the exact title."
        )
    else:
        notes = (
            "Adjudicated exact-title review against real Zotero metadata and repo review pool; "
            f"rel=2 assigned only to title-equivalent corpus doc(s) {positive_doc_ids} and remaining pooled docs "
            "judged rel=0 as non-identical literature."
        )
        notes_for_future_tolf = (
            f"Zotero-backed title matched query exactly; direct-answer corpus doc(s): {positive_doc_ids}."
        )

    adjudicated = dict(record)
    adjudicated.update(
        {
            "qrels": qrels,
            "annotator_id": "oracle_exact_title_adjudicated",
            "no_gold": no_gold,
            "created_at": judged_at,
            "reviewer_id": "oracle",
            "notes": notes,
            "notes_for_future_tolf": notes_for_future_tolf,
            "judged_at": judged_at,
            "pool_size": len(qrels),
        }
    )
    return adjudicated


def main() -> None:
    judged_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    high_conf_records = _load_jsonl(IN_HIGH)
    review_records = _load_jsonl(IN_REVIEW)
    pool_records = _load_jsonl(IN_POOLS)
    pool_by_query_id = {record["query_id"]: record for record in pool_records}

    doc_store = json.loads(DOC_STORE_PATH.read_text(encoding="utf-8"))
    zotero_titles = _load_zotero_titles()

    adjudicated_review_records = [
        _adjudicate_record(record, pool_by_query_id[record["query_id"]], zotero_titles, doc_store, judged_at)
        for record in review_records
    ]
    all_records = high_conf_records + adjudicated_review_records

    _write_jsonl(OUT_HIGH, high_conf_records)
    _write_jsonl(OUT_REVIEW, adjudicated_review_records)
    _write_jsonl(OUT_ALL, all_records)
    _write_qrels(OUT_QRELS, all_records)

    review_true_no_gold = sum(1 for record in adjudicated_review_records if record["no_gold"])
    review_resolved_positive = len(adjudicated_review_records) - review_true_no_gold
    manifest = {
        "built_at": judged_at,
        "total_queries": len(all_records),
        "high_confidence_queries": len(high_conf_records),
        "adjudicated_review_queries": len(adjudicated_review_records),
        "review_needed_queries": 0,
        "review_pool_size": max((record.get("pool_size", 0) for record in adjudicated_review_records), default=0),
        "adjudication_basis": (
            "Exact-title adjudication only: query_text normalized == Zotero title normalized == candidate title "
            "normalized => rel=2; all other pooled docs => rel=0."
        ),
        "coherence": {
            "scaffold_only_unresolved_entries": 0,
            "resolved_with_gold": review_resolved_positive,
            "true_no_gold_after_review": review_true_no_gold,
        },
        "corpus": {
            "parsed_doc_store_path": str(DOC_STORE_PATH.relative_to(ROOT)),
            "parsed_doc_count": len(doc_store),
            "zotero_db_path": str(ZOTERO_DB_PATH),
            "zotero_backed_review_queries": len(adjudicated_review_records),
        },
        "outputs": {
            "all": str(OUT_ALL.relative_to(ROOT)),
            "high_confidence": str(OUT_HIGH.relative_to(ROOT)),
            "adjudicated_review_subset": str(OUT_REVIEW.relative_to(ROOT)),
            "review_pools": str(IN_POOLS.relative_to(ROOT)),
            "qrels_tsv": str(OUT_QRELS.relative_to(ROOT)),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
