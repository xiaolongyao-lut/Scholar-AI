from __future__ import annotations
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
from pydantic import BaseModel, Field

class ConflictType(str, Enum):
    NO_CONFLICT = "NO_CONFLICT"
    DIRECT_CONFLICT = "DIRECT_CONFLICT"       # 直接矛盾
    CONDITIONAL_CONFLICT = "CONDITIONAL_CONFLICT" # 条件冲突
    INDIRECT_CONFLICT = "INDIRECT_CONFLICT"     # 间接冲突 (因果不一致)
    QUANTITATIVE_CONFLICT = "QUANTITATIVE_CONFLICT" # 量化数值冲突

class ConflictResult(BaseModel):
    """冲突检测的中间结果"""
    conflict_type: ConflictType
    severity_level: int
    explanation: str
    claims_involved: List[Claim] = []

class SourceMeta(BaseModel):
    """文献元数据 (用于 P2 权威性评估)"""
    doc_id: str
    title: str
    authors: List[str] = []
    corresponding_author: Optional[str] = None
    year: int
    journal: str
    impact_factor: float = 0.0
    citation_count: int = 0
    doi: Optional[str] = None

class Claim(BaseModel):
    """结构化语义声明。"""
    claim_id: str
    subject: str                   # 主体 (如: 激光功率)
    predicate: str                 # 谓词 (如: 增加, 影响)
    object: str                    # 宾体 (如: 熔深)
    context: Dict[str, str] = {}   # 条件上下文 (如: {"material": "TC4"})
    confidence: float = 1.0
    evidence_text: str             # 证据原文
    source: SourceMeta
    
    # 量化属性
    quantitative_value: Optional[float] = None
    quantitative_unit: Optional[str] = None
    quantitative_range: Optional[Tuple[float, float]] = None

class ClassifiedConflict(BaseModel):
    """已分类分级的冲突报告 (P2 专业版)"""
    conflict_id: str
    type: ConflictType
    severity_level: int = 1        # 1-4 (低到严重)
    claims_involved: List[Claim]
    
    # 时间演变分析
    evolution_type: str            # "STABLE" | "EVOLUTION" | "CONTRADICTORY"
    interpretation: str            # 专家级解读
    
    # 权威性评估 (基于 IF 和 被引数)
    authority_score: float = 0.0
    authority_summary: str
    
    # 建议行动
    resolution_path: List[str] = []

class ReasoningStep(BaseModel):
    """推演链步骤"""
    step_id: int
    type: str                      # RETRIEVAL | EXTRACTION | CONFLICT | SYNTHESIS
    description: str
    outputs: List[str] = []

class ReasoningChain(BaseModel):
    """完整逻辑推演报告 (包含成本统计)"""
    chain_id: str
    query: str
    steps: List[ReasoningStep] = []
    conflicts: List[ClassifiedConflict] = []
    final_conclusion: Optional[str] = None
    overall_confidence: float = 0.0
    cost_summary: Dict[str, Any] = {}  # 优化 3: 成本统计 {"total_cost": 0.1, "call_count": 2}
