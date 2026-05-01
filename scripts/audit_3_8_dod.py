"""
§3.8 DoD audit script for evidence packing and generation prompt contracts.

Audits three items:
1. Token budget: Any answer prompt actual input tokens ≤ EVIDENCE_TOKEN_BUDGET
2. Material duplication: Same material appears ≤ 2 times in final prompt
3. Answer citations: 100% answers contain [chunk_id] references (grep verification)
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

import main_rag_workflow
from evidence_packer import format_evidence_item, pack_evidence
from token_utils import count_tokens


def _measure_generation_prompt_tokens() -> dict:
    """
    DoD 1: Measure actual token count of a packed generation prompt.
    Returns evidence that any prompt ≤ EVIDENCE_TOKEN_BUDGET.
    """
    evidence_budget = max(1, int(os.environ.get("EVIDENCE_TOKEN_BUDGET", "4000")))
    evidence_hard_cap = max(
        evidence_budget,
        int(os.environ.get("EVIDENCE_TOKEN_HARD_CAP", "5000")),
    )
    evidence_top_k = max(1, int(os.environ.get("EVIDENCE_PACK_TOP_K", "5")))
    evidence_max_per_material = max(
        1,
        int(os.environ.get("EVIDENCE_MAX_PER_MATERIAL", "2")),
    )

    # Simulate realistic candidates with varying material_ids
    test_candidates = [
        {
            "chunk_id": f"chunk-{i}",
            "material_id": f"paper-{i % 3}",  # 3 different papers
            "score": 1.0 - i * 0.05,
            "text": "一段激光焊接研究的证据文本，长度适中，包含足够的技术细节用于估算 token 量。" * 10,
        }
        for i in range(10)
    ]

    # Pack evidence using the same logic as _generate_answer
    packed = pack_evidence(
        candidates=test_candidates,
        budget_tokens=evidence_budget,
        hard_cap_tokens=evidence_hard_cap,
        max_per_material=evidence_max_per_material,
        top_k=evidence_top_k,
    )

    # Build the actual evidence section that would go into the prompt
    evidence_section = "\n".join(format_evidence_item(c) for c in packed)

    # Construct a minimal prompt structure like _generate_answer does
    minimal_prompt = f"""用户问题：测试问题

关注点：
- 测试关注点

检索到的证据：
{evidence_section}

请基于上述证据回答。每条事实必须绑定真实 [chunk_id]。若缺失信息，写"文中未提及"。"""

    prompt_tokens = count_tokens(minimal_prompt)
    evidence_tokens = count_tokens(evidence_section)

    return {
        "prompt_tokens": prompt_tokens,
        "evidence_tokens": evidence_tokens,
        "budget": evidence_budget,
        "hard_cap": evidence_hard_cap,
        "packed_count": len(packed),
        "within_budget": prompt_tokens <= evidence_budget,
        "evidence_within_budget": evidence_tokens <= evidence_budget,
    }


def _measure_material_duplication() -> dict:
    """
    DoD 2: Verify same material appears ≤ 2 times in final prompt.
    Returns evidence that material cap is enforced.
    """
    evidence_top_k = max(1, int(os.environ.get("EVIDENCE_PACK_TOP_K", "5")))
    evidence_max_per_material = max(
        1,
        int(os.environ.get("EVIDENCE_MAX_PER_MATERIAL", "2")),
    )

    # Simulate 10 candidates with 3 from same material
    test_candidates = [
        {
            "chunk_id": f"same-material-{i}",
            "material_id": "paper-a",
            "score": 1.0 - i * 0.01,
            "text": f"Evidence from paper-a chunk {i}",
        }
        for i in range(3)
    ] + [
        {
            "chunk_id": f"other-{i}",
            "material_id": f"paper-{i}",
            "score": 0.8 - i * 0.05,
            "text": f"Evidence from paper-{i}",
        }
        for i in range(3, 7)
    ]

    packed = pack_evidence(
        candidates=test_candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=evidence_max_per_material,
        top_k=evidence_top_k,
    )

    # Count material_id occurrences
    material_counts = Counter(c.get("material_id") for c in packed)
    max_per_material_observed = max(material_counts.values()) if material_counts else 0

    return {
        "max_per_material_setting": evidence_max_per_material,
        "max_per_material_observed": max_per_material_observed,
        "within_limit": max_per_material_observed <= evidence_max_per_material,
        "material_distribution": dict(material_counts),
    }


def _grep_chunk_id_citations() -> dict:
    """
    DoD 3: Grep check for [chunk_id] references in generation answers.
    
    Plan requirement: "答案 100% 含 [chunk_id] 引用（grep 校验）"
    This requires answer-level evidence, not just prompt template verification.
    
    Since we don't have a stable grepable runtime artifact path for generated answers,
    this DoD item cannot be closed with truthful evidence in this surgical slice.
    """
    # Check prompt requirements (necessary but NOT sufficient for DoD 3)
    workflow_file = Path("main_rag_workflow.py")
    if not workflow_file.exists():
        return {
            "status": "blocked",
            "reason": "main_rag_workflow.py not found",
            "blocker": "Cannot verify answer-level citations without runtime artifact path",
        }

    workflow_code = workflow_file.read_text(encoding="utf-8")

    # Check for mandatory citation requirements in prompt
    citation_patterns = [
        r"每条事实必须绑定真实\s*\[chunk_id\]",
        r"\[chunk_id\]",
        r"文中未提及",
    ]

    found_requirements = []
    for pattern in citation_patterns:
        if re.search(pattern, workflow_code):
            found_requirements.append(pattern)

    # Check that evidence_packer.format_evidence_item uses [chunk_id] format
    packer_file = Path("evidence_packer.py")
    if packer_file.exists():
        packer_code = packer_file.read_text(encoding="utf-8")
        has_chunk_id_format = re.search(r'\[.*chunk_id.*\]', packer_code)
    else:
        has_chunk_id_format = None

    prompt_enforces = len(found_requirements) >= 2 and has_chunk_id_format

    return {
        "prompt_requires_citations": len(found_requirements) >= 2,
        "found_requirements": found_requirements,
        "evidence_format_uses_chunk_id": bool(has_chunk_id_format),
        "status": "blocked",
        "blocker": "No stable grepable runtime artifact path for answer-level citation verification. Prompt enforcement (necessary condition) verified, but plan requires answer-level grep proof.",
        "prompt_enforcement_verified": bool(prompt_enforces),
    }


def main():
    print("=== §3.8 DoD Audit ===\n")

    # DoD 1: Token budget
    print("DoD 1: Token Budget Check")
    print("-" * 60)
    token_result = _measure_generation_prompt_tokens()
    print(f"Evidence Budget: {token_result['budget']} tokens")
    print(f"Hard Cap: {token_result['hard_cap']} tokens")
    print(f"Actual Prompt Tokens: {token_result['prompt_tokens']} tokens")
    print(f"Evidence Section Tokens: {token_result['evidence_tokens']} tokens")
    print(f"Packed Count: {token_result['packed_count']} items")
    print(f"✅ Within Budget: {token_result['within_budget']}")
    print(f"✅ Evidence Within Budget: {token_result['evidence_within_budget']}")
    dod1_pass = token_result['within_budget']
    print()

    # DoD 2: Material duplication
    print("DoD 2: Material Duplication Check")
    print("-" * 60)
    material_result = _measure_material_duplication()
    print(f"Max Per Material Setting: {material_result['max_per_material_setting']}")
    print(f"Max Per Material Observed: {material_result['max_per_material_observed']}")
    print(f"Material Distribution: {material_result['material_distribution']}")
    print(f"✅ Within Limit: {material_result['within_limit']}")
    dod2_pass = material_result['within_limit']
    print()

    # DoD 3: Citation grep
    print("DoD 3: [chunk_id] Citation Check")
    print("-" * 60)
    citation_result = _grep_chunk_id_citations()
    print(f"Status: {citation_result['status']}")
    print(f"Prompt Enforcement Verified: {citation_result.get('prompt_enforcement_verified', False)}")
    print(f"Prompt Requires Citations: {citation_result['prompt_requires_citations']}")
    print(f"Evidence Format Uses [chunk_id]: {citation_result['evidence_format_uses_chunk_id']}")
    print(f"Found Requirements: {citation_result['found_requirements']}")
    print(f"⚠️  Blocker: {citation_result['blocker']}")
    dod3_pass = False
    print()

    # Summary
    print("=== Summary ===")
    print(f"DoD 1 (Token Budget): {'✅ PASS' if dod1_pass else '❌ FAIL'}")
    print(f"DoD 2 (Material Limit): {'✅ PASS' if dod2_pass else '❌ FAIL'}")
    print(f"DoD 3 ([chunk_id] Citations): {'❌ BLOCKED' if not dod3_pass else '✅ PASS'}")
    print()

    all_pass = dod1_pass and dod2_pass and dod3_pass
    print(f"Overall: {'✅ ALL PASS' if all_pass else '❌ BLOCKED - See DoD 3 blocker'}")

    # Save results
    results_file = Path("output") / "audit_3_8_dod_results.json"
    results_file.parent.mkdir(exist_ok=True)
    results = {
        "dod_1_token_budget": token_result,
        "dod_2_material_limit": material_result,
        "dod_3_citation_check": citation_result,
        "summary": {
            "dod_1_pass": dod1_pass,
            "dod_2_pass": dod2_pass,
            "dod_3_pass": dod3_pass,
            "all_pass": all_pass,
        },
    }
    results_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to: {results_file}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
