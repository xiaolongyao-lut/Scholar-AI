from __future__ import annotations

from layers.p3_causal_engine import CausalChain
from layers.p3_consistency_validator import ConsistencyValidator
from models.p2_logic_models import (
    ClassifiedConflict,
    Claim,
    ConflictType,
    SourceMeta,
)


def make_chain(nodes, relations, confidence=0.9):
    return CausalChain(
        nodes=nodes,
        relations=relations,
        confidence=confidence,
        evidence_count=len(relations),
    )


def make_claim(
    claim_id: str,
    subject: str,
    predicate: str,
    object_: str,
    *,
    year: int = 2024,
    impact_factor: float = 3.0,
    citation_count: int = 10,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        subject=subject,
        predicate=predicate,
        object=object_,
        confidence=0.9,
        evidence_text=f"{subject} {predicate} {object_}",
        source=SourceMeta(
            doc_id=f"doc_{claim_id}",
            title=f"Paper {claim_id}",
            year=year,
            journal="Journal of Validation",
            impact_factor=impact_factor,
            citation_count=citation_count,
        ),
    )


def make_conflict(*claims: Claim) -> ClassifiedConflict:
    return ClassifiedConflict(
        conflict_id="CF-001",
        type=ConflictType.DIRECT_CONFLICT,
        severity_level=2,
        claims_involved=list(claims),
        evolution_type="CONTRADICTORY",
        interpretation="同一条件下结论冲突",
        authority_score=0.0,
        authority_summary="synthetic conflict for regression",
        resolution_path=[],
    )


def test_validate_identical_chains_pass() -> None:
    validator = ConsistencyValidator()
    chain_a = make_chain(["LaserPower", "MeltPool", "Hardness"], ["increases", "improves"])
    chain_b = make_chain(["LaserPower", "MeltPool", "Hardness"], ["increases", "improves"], confidence=0.8)

    report = validator.validate([chain_a, chain_b])

    assert report.summary.chain_count == 2
    assert report.summary.pair_count == 1
    assert report.summary.flagged_pair_count == 0
    assert report.summary.review_pair_count == 0
    assert report.summary.overall_status == "PASS"

    pair = report.pair_results[0]
    assert pair.consistency_score == 1.0
    assert pair.issue == "CONSISTENT_PATHS"
    assert pair.shared_nodes == ["LaserPower", "MeltPool", "Hardness"]
    assert pair.shared_relations == ["increases", "improves"]


def test_validate_partial_alignment_marks_review() -> None:
    validator = ConsistencyValidator()
    chain_a = make_chain(["LaserPower", "MeltPool", "Hardness"], ["increases", "improves"])
    chain_b = make_chain(["LaserPower", "MeltPool", "Porosity"], ["increases", "improves"])

    report = validator.validate([chain_a, chain_b])

    assert report.summary.chain_count == 2
    assert report.summary.pair_count == 1
    assert report.summary.flagged_pair_count == 0
    assert report.summary.review_pair_count == 1
    assert report.summary.overall_status == "REVIEW"

    pair = report.pair_results[0]
    assert 0.5 <= pair.consistency_score < 0.75
    assert pair.issue == "DIVERGENT_PATHS"
    assert pair.common_prefix_length == 2
    assert pair.shared_nodes == ["LaserPower", "MeltPool"]


def test_validate_conflicting_chains_penalized_by_conflict() -> None:
    validator = ConsistencyValidator()
    chain_a = make_chain(["LaserPower", "MeltPool", "Hardness"], ["increases", "improves"])
    chain_b = make_chain(["LaserPower", "MeltPool", "Porosity"], ["increases", "improves"])
    conflict = make_conflict(
        make_claim("c1", "MeltPool", "improves", "Hardness", year=2023),
        make_claim("c2", "MeltPool", "improves", "Porosity", year=2024),
    )

    report = validator.validate([chain_a, chain_b], conflicts=[conflict])

    assert report.summary.chain_count == 2
    assert report.summary.pair_count == 1
    assert report.summary.flagged_pair_count == 1
    assert report.summary.overall_status == "FAIL"

    pair = report.pair_results[0]
    assert pair.consistency_score < 0.5
    assert pair.issue == "CONFLICTING_PATHS"
    assert pair.conflict_penalty > 0


def test_validate_empty_input() -> None:
    validator = ConsistencyValidator()

    report = validator.validate([])

    assert report.summary.chain_count == 0
    assert report.summary.pair_count == 0
    assert report.summary.flagged_pair_count == 0
    assert report.summary.review_pair_count == 0
    assert report.summary.overall_status == "EMPTY"
    assert report.pair_results == []
