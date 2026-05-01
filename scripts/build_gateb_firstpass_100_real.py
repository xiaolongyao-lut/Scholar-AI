from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "eval_audit"
HIGH_CONF_SOURCE = ARTIFACT_DIR / "gateb_goldset.jsonl"
DOC_STORE_PATH = ROOT / "output" / "doc_store" / "laser_welding_109.json"
ZOTERO_DB_PATH = Path(r"D:\zotero\zoterodate\zotero.sqlite")
ZOTERO_PREFS_PATH = Path(r"C:\Users\xiao\AppData\Roaming\Zotero\Zotero\Profiles\o952gbx8.default\prefs.js")

OUT_ALL = ARTIFACT_DIR / "gateb_firstpass_100_all.jsonl"
OUT_HIGH = ARTIFACT_DIR / "gateb_firstpass_100_high_confidence.jsonl"
OUT_REVIEW = ARTIFACT_DIR / "gateb_firstpass_100_review_needed.jsonl"
OUT_QRELS = ARTIFACT_DIR / "gateb_firstpass_100_qrels.tsv"
OUT_POOLS = ARTIFACT_DIR / "gateb_firstpass_100_review_pools.jsonl"
OUT_MANIFEST = ARTIFACT_DIR / "gateb_firstpass_100_manifest.json"

TARGET_TOTAL = 100
HIGH_CONF_COUNT = 36
REVIEW_COUNT = TARGET_TOTAL - HIGH_CONF_COUNT
REVIEW_POOL_SIZE = 5

EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "study",
    "the",
    "to",
    "under",
    "via",
    "with",
}
ZH_BIGRAM_STOPWORDS = {"研究", "分析", "影响", "机制", "数值", "综述", "进展", "激光", "焊接", "过程", "性能"}


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
    text = re.sub(r"\s+", " ", text)
    return text


def _title_tokens(value: str) -> set[str]:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2 and word not in EN_STOPWORDS:
            tokens.add(word)
    for seq in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(seq) == 2:
            if seq not in ZH_BIGRAM_STOPWORDS:
                tokens.add(seq)
            continue
        for index in range(max(0, len(seq) - 1)):
            bigram = seq[index : index + 2]
            if len(bigram) == 2 and bigram not in ZH_BIGRAM_STOPWORDS:
                tokens.add(bigram)
    return tokens


def _load_zotero_items() -> list[dict]:
    connection = sqlite3.connect(f"file:{ZOTERO_DB_PATH}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT
                i.itemID,
                it.typeName,
                idv.value AS title,
                MIN(ia.path) AS attachment_path
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            JOIN itemData id ON id.itemID = i.itemID
            JOIN fields f ON f.fieldID = id.fieldID AND f.fieldName = 'title'
            JOIN itemDataValues idv ON idv.valueID = id.valueID
            LEFT JOIN itemAttachments ia ON ia.parentItemID = i.itemID
            WHERE
                i.itemID NOT IN (SELECT itemID FROM deletedItems)
                AND it.typeName NOT IN ('annotation', 'note')
            GROUP BY i.itemID, it.typeName, idv.value
            ORDER BY i.itemID
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "zotero_item_id": str(item_id),
            "item_type": item_type,
            "title": title,
            "attachment_path": attachment_path,
            "normalized_title": _normalize_title(title),
        }
        for item_id, item_type, title, attachment_path in rows
        if title
    ]


def _build_overlap_records(doc_store: dict[str, dict], high_conf_records: list[dict]) -> list[dict]:
    positive_doc_ids = {
        str(qrel.get("doc_id", "")).strip()
        for record in high_conf_records
        for qrel in record.get("qrels", [])
        if int(qrel.get("relevance", 0)) >= 1 and str(qrel.get("doc_id", "")).strip()
    }
    title_to_doc: dict[str, tuple[str, dict]] = {}
    for doc_id, payload in doc_store.items():
        normalized = _normalize_title(str(payload.get("title", "")))
        if normalized and normalized not in title_to_doc:
            title_to_doc[normalized] = (doc_id, payload)

    overlaps: list[dict] = []
    for item in _load_zotero_items():
        matched = title_to_doc.get(item["normalized_title"])
        if matched is None:
            continue
        doc_id, payload = matched
        overlaps.append(
            {
                "doc_id": doc_id,
                "query_text": item["title"],
                "zotero_item_id": item["zotero_item_id"],
                "item_type": item["item_type"],
                "attachment_path": item["attachment_path"],
                "title": str(payload.get("title", "")).strip(),
                "content_preview": str(payload.get("content", "")).strip()[:400],
                "normalized_title": item["normalized_title"],
                "tokens": _title_tokens(item["title"]),
                "already_positive": doc_id in positive_doc_ids,
            }
        )
    overlaps.sort(key=lambda item: (item["already_positive"], item["query_text"].casefold(), item["doc_id"]))
    return overlaps


def _candidate_pool(target: dict, population: list[dict]) -> list[dict]:
    def score(other: dict) -> tuple[int, int, str]:
        if other["doc_id"] == target["doc_id"]:
            return (10_000, 10_000, other["doc_id"])
        overlap = len(target["tokens"].intersection(other["tokens"]))
        length_bonus = min(len(other["tokens"]), 10)
        return (overlap, length_bonus, other["doc_id"])

    ranked = sorted(population, key=score, reverse=True)
    chosen: list[dict] = []
    seen: set[str] = set()
    for item in ranked:
        if item["doc_id"] in seen:
            continue
        seen.add(item["doc_id"])
        chosen.append(item)
        if len(chosen) >= REVIEW_POOL_SIZE:
            break

    pool: list[dict] = []
    for index, item in enumerate(chosen, start=1):
        shared_terms = sorted(target["tokens"].intersection(item["tokens"]))
        if item["doc_id"] == target["doc_id"]:
            match_basis = "exact_zotero_title_overlap"
        elif shared_terms:
            match_basis = "title_token_overlap"
        else:
            match_basis = "fallback_neighbor"
        pool.append(
            {
                "doc_id": item["doc_id"],
                "title": item["title"],
                "content_preview": item["content_preview"],
                "source_hint": "evidence_set" if item["doc_id"] == target["doc_id"] else "unexpected_unknown_source",
                "rank_in_pool": index,
                "match_basis": match_basis,
                "shared_terms": shared_terms[:8],
                "zotero_item_id": item["zotero_item_id"],
                "zotero_item_type": item["item_type"],
                "zotero_attachment_path": item["attachment_path"],
            }
        )
    return pool


def _build_review_records(overlaps: list[dict], created_at: str) -> tuple[list[dict], list[dict]]:
    review_population = [item for item in overlaps if not item["already_positive"]]
    selected = review_population[:REVIEW_COUNT]
    if len(selected) != REVIEW_COUNT:
        raise RuntimeError(f"Need {REVIEW_COUNT} review-needed overlaps, found {len(selected)}")

    review_records: list[dict] = []
    pool_records: list[dict] = []
    for index, item in enumerate(selected, start=1):
        query_id = f"q_gatebfp100_r{index:03d}"
        pool = _candidate_pool(item, review_population)
        review_records.append(
            {
                "schema_version": "1",
                "query_id": query_id,
                "query_text": item["query_text"],
                "qrels": [],
                "annotator_id": "oracle_firstpass_scaffold",
                "no_gold": True,
                "created_at": created_at,
                "source_stratum": "S1",
                "source_template_id": None,
                "original_query_id": None,
                "reviewer_id": None,
                "notes": (
                    "Review-needed exact-title scaffold from real Zotero↔parsed-corpus overlap; "
                    f"target_doc_id={item['doc_id']}; zotero_item_id={item['zotero_item_id']}"
                ),
                "notes_for_future_tolf": (
                    "Use gateb_firstpass_100_review_pools.jsonl for candidate adjudication; "
                    "target doc is the exact Zotero-title overlap candidate."
                ),
                "pool_size": len(pool),
            }
        )
        pool_records.append(
            {
                "query_id": query_id,
                "query_text": item["query_text"],
                "source_stratum": "S1",
                "source_template_id": None,
                "original_query_id": None,
                "target_doc_id": item["doc_id"],
                "target_title": item["title"],
                "zotero_item_id": item["zotero_item_id"],
                "zotero_item_type": item["item_type"],
                "zotero_attachment_path": item["attachment_path"],
                "pool_size": len(pool),
                "candidates": pool,
            }
        )
    return review_records, pool_records


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


def main() -> None:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    high_conf_records = _load_jsonl(HIGH_CONF_SOURCE)
    if len(high_conf_records) != HIGH_CONF_COUNT:
        raise RuntimeError(f"Expected {HIGH_CONF_COUNT} high-confidence records, found {len(high_conf_records)}")

    doc_store = json.loads(DOC_STORE_PATH.read_text(encoding="utf-8"))
    overlaps = _build_overlap_records(doc_store, high_conf_records)
    review_records, pool_records = _build_review_records(overlaps, created_at)
    all_records = high_conf_records + review_records

    _write_jsonl(OUT_HIGH, high_conf_records)
    _write_jsonl(OUT_REVIEW, review_records)
    _write_jsonl(OUT_ALL, all_records)
    _write_jsonl(OUT_POOLS, pool_records)
    _write_qrels(OUT_QRELS, high_conf_records)

    manifest = {
        "built_at": created_at,
        "total_queries": len(all_records),
        "high_confidence_queries": len(high_conf_records),
        "review_needed_queries": len(review_records),
        "review_pool_size": REVIEW_POOL_SIZE,
        "corpus": {
            "parsed_doc_store_path": str(DOC_STORE_PATH.relative_to(ROOT)),
            "parsed_doc_count": len(doc_store),
            "zotero_prefs_path": str(ZOTERO_PREFS_PATH),
            "zotero_db_path": str(ZOTERO_DB_PATH),
            "zotero_overlap_count": len(overlaps),
            "review_selection_basis": "Exact Zotero title ↔ parsed corpus overlap, excluding docs already positive in reviewed 36-query set.",
        },
        "outputs": {
            "all": str(OUT_ALL.relative_to(ROOT)),
            "high_confidence": str(OUT_HIGH.relative_to(ROOT)),
            "review_needed": str(OUT_REVIEW.relative_to(ROOT)),
            "review_pools": str(OUT_POOLS.relative_to(ROOT)),
            "qrels_tsv": str(OUT_QRELS.relative_to(ROOT)),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
