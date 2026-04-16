import pytest
from models.p2_logic_models import Claim, SourceMeta
from layers.p3_dynamic_updater import DynamicUpdater
from layers.p3_resolver import ConflictResolver

@pytest.fixture
def updater():
    return DynamicUpdater()

@pytest.fixture
def old_claims():
    return [
        Claim(
            claim_id="OLD_001",
            subject="Laser Power",
            predicate="Increases",
            object="Melt Depth",
            source=SourceMeta(doc_id="D2022", title="Study B", year=2022, journal="Journal B", impact_factor=2.0),
            evidence_text="Power increases depth (2022 study).",
            confidence=0.7
        )
    ]

def test_temporal_evolution_replacement(updater, old_claims):
    """验证 2024 年的研究能够替换 2020 年的旧研究 (时间演化)"""
    new_claims = [
        Claim(
            claim_id="NEW_2024",
            subject="laser power", # 语义对齐测试
            predicate="Decreases", # 发现新结论（可能在高功率区间）
            object="melt depth",
            source=SourceMeta(doc_id="D2024", title="Modern Study", year=2024, journal="Top Journal", impact_factor=12.0),
            evidence_text="Modern study shows decrease at extreme power.",
            confidence=0.9
        )
    ]
    
    result = updater.update_knowledge_base(old_claims, new_claims)
    
    # 结果应只保留最新的，因为跨度 >= 3 年且触发了 Resolver
    claim_ids = [c.claim_id for c in result]
    assert "NEW_2024" in claim_ids
    assert "OLD_001" not in claim_ids
    assert len(result) == 1

def test_evidentiary_hierarchy_replacement(updater):
    """验证同一年份下，高权威性文献替换低权威性文献"""
    base = [
        Claim(
            claim_id="LOW_IF",
            subject="Speed",
            predicate="Affects",
            object="Quality",
            source=SourceMeta(doc_id="D1", title="Small Conf", year=2023, journal="Conf", impact_factor=1.0),
            evidence_text="Low quality source.",
            confidence=0.5
        )
    ]
    high_if = [
        Claim(
            claim_id="HIGH_IF",
            subject="Speed",
            predicate="Affects",
            object="Quality",
            source=SourceMeta(doc_id="D2", title="Nature Materials", year=2023, journal="Nature", impact_factor=40.0),
            evidence_text="High quality consensus.",
            confidence=0.95
        )
    ]
    
    result = updater.update_knowledge_base(base, high_if)
    
    claim_ids = [c.claim_id for c in result]
    assert "HIGH_IF" in claim_ids
    assert "LOW_IF" not in claim_ids 

def test_no_conflict_merge(updater, old_claims):
    """验证无冲突声明的正常物理合并"""
    different_claims = [
        Claim(
            claim_id="DIFF_001",
            subject="Atmosphere",
            predicate="Stabilizes",
            object="Keyhole",
            source=SourceMeta(doc_id="D3", title="Gas Study", year=2023, journal="Journal", impact_factor=5.0),
            evidence_text="Gas effects.",
            confidence=0.8
        )
    ]
    
    result = updater.update_knowledge_base(old_claims, different_claims)
    assert len(result) == 2
    claim_ids = [c.claim_id for c in result]
    assert "OLD_001" in claim_ids
    assert "DIFF_001" in claim_ids

def test_stale_data_elimination(updater):
    """验证超过 5 年的知识被自动淘汰 (即便没有新冲突)"""
    very_old = [
        Claim(
            claim_id="ANCIENT",
            subject="X",
            predicate="Y",
            object="Z",
            source=SourceMeta(doc_id="D1990", title="Ancient Scroll", year=1990, journal="History", impact_factor=1.0),
            evidence_text="Ancient knowledge.",
            confidence=0.4
        )
    ]
    # 注意：updater.current_year 固定在加载时，2026 - 1990 > 5
    result = updater.update_knowledge_base(very_old, [])
    assert len(result) == 0
