from __future__ import annotations

from citation_auditor import CitationAuditor


def test_citation_auditor_accepts_text_and_bracketed_chunk_ids() -> None:
    auditor = CitationAuditor()
    response = {
        "evidence": [
            {
                "statement": "Beam power affects penetration.",
                "chunk_ids": ["[chunk-1]"],
                "quote": "Beam power correlates with penetration depth.",
            }
        ],
        "limitations": "",
        "status": "success",
    }
    source_chunks = [
        {
            "chunk_id": "chunk-1",
            "text": "Beam power correlates with penetration depth.",
        }
    ]

    audited, passed = auditor.audit(response, source_chunks)

    assert passed is True
    assert audited["evidence"][0]["audit_status"] == "passed"


def test_citation_auditor_accepts_compressed_text() -> None:
    auditor = CitationAuditor()
    response = {
        "evidence": [
            {
                "statement": "Compressed evidence remains traceable.",
                "chunk_ids": ["chunk-2"],
                "quote": "traceable quote",
            }
        ],
        "limitations": "",
        "status": "success",
    }
    source_chunks = [{"chunk_id": "chunk-2", "compressed_text": "minimal traceable quote"}]

    audited, passed = auditor.audit(response, source_chunks)

    assert passed is True
    assert audited["status"] == "success"
