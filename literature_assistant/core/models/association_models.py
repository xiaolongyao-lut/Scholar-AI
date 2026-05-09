from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class EntityMention(BaseModel):
    """实体在文档中的单次提及"""
    entity_id: str
    entity_name: str
    entity_type: str  # material, process, parameter, defect, etc.
    paper_id: str
    doc_title: str
    mention_text: str
    context_summary: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 1.0

class EntityTrajectory(BaseModel):
    """实体的演变轨迹"""
    entity_id: str
    entity_name: str
    mentions: List[EntityMention] = []
    first_seen: Optional[str] = None
    latest_seen: Optional[str] = None
    evolution_path: List[Dict[str, Any]] = []  # Time-ordered evolution claims
    coverage_gaps: List[str] = []              # Detected missing time periods

class LogicStep(BaseModel):
    """逻辑推演的一个步骤"""
    step_id: int
    action: str
    reason: str
    result: Any
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

class LogicTracingPath(BaseModel):
    """完整逻辑溯源路径"""
    entry_claim: str
    steps: List[LogicStep] = []
    final_score: float = 0.0

class StructuralRisk(BaseModel):
    """结构化论证风险监测"""
    type: str  # SINGLE_EVIDENCE, EVIDENCE_STALE, CONTRADICTORY_FOUND
    severity: str  # low, medium, high, critical
    description: str
    suggestion: str

class AssociationOutput(BaseModel):
    """逻辑引擎的最终结构化输出契约 (P2 预留)"""
    related_signals: List[Dict[str, Any]] = []
    logic_tracing_path: Optional[LogicTracingPath] = None
    structural_risks: List[StructuralRisk] = []
    conflict_report: Optional[Dict[str, Any]] = None
    entity_trajectories: List[EntityTrajectory] = []
