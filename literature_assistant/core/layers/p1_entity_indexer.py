# layers/p1_entity_indexer.py

from dataclasses import dataclass, asdict
from typing import Dict, List, Set, Optional, Tuple
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("P1_EntityIndexer")

@dataclass
class EntityRecord:
    """单个科研实体记录 (P1 WBS 1.2 对齐)"""
    entity_id: str
    canonical_name: str
    aliases: List[str]
    category: str      # "material" | "process" | "property" | "anomaly"
    doc_refs: List[str] # [doc_id, ...]
    years_covered: List[int]
    mention_count: int

class EntityIndexer:
    """
    实体管理器：建立实体与文档、时间的映射关系
    """
    
    def __init__(self, focus_registry_path: str = "layers/focus_registry.py"):
        """
        初始化实体索引器
        """
        self.entities: Dict[str, EntityRecord] = {}
        self.entity_timeline: Dict[str, Dict[int, int]] = {}  # entity_id -> {year: mention_count}
        
        # 尝试从 focus_registry 加载映射逻辑等
        self._load_focus_aliases(focus_registry_path)
    
    def _load_focus_aliases(self, registry_path: str):
        """预留逻辑：从现有 registry 加载别名"""
        if Path(registry_path).exists():
            logger.info(f"Registry found at {registry_path}, placeholder for alias loading.")
            # 这里的实际解析逻辑取决于 focus_registry.py 的内容
            pass

    def register_entity(self, entity_name: str, category: str, doc_id: str, year: int = 2024):
        """
        注册一个实体出现 (P1 关键逻辑)
        """
        canonical = self._canonicalize(entity_name)
        
        if canonical not in self.entities:
            self.entities[canonical] = EntityRecord(
                entity_id=f"entity_{len(self.entities):05d}",
                canonical_name=canonical,
                aliases=[entity_name],
                category=category,
                doc_refs=[doc_id],
                years_covered=[year],
                mention_count=1
            )
            self.entity_timeline[canonical] = {year: 1}
        else:
            rec = self.entities[canonical]
            if doc_id not in rec.doc_refs:
                rec.doc_refs.append(doc_id)
            if entity_name not in rec.aliases:
                rec.aliases.append(entity_name)
            if year not in rec.years_covered:
                rec.years_covered.append(year)
                rec.years_covered.sort()
            rec.mention_count += 1
            
            self.entity_timeline[canonical][year] = self.entity_timeline[canonical].get(year, 0) + 1
    
    def compute_coverage_gap(self, canonical_id: str, threshold_years: int = 2) -> Dict:
        """
        计算实体的覆盖缺口 (算法对齐 WBS 1.2)
        """
        if canonical_id not in self.entity_timeline:
            return {"gaps": [], "gap_severity": "unknown"}
        
        timeline = sorted(self.entity_timeline[canonical_id].keys())
        gaps = []
        for i in range(len(timeline) - 1):
            gap_len = timeline[i + 1] - timeline[i]
            if gap_len > threshold_years:
                gaps.append((timeline[i] + 1, gap_len - 1))
        
        # 评估严重程度
        max_gap = max(g[1] for g in gaps) if gaps else 0
        if max_gap > 5:
            severity = "high"
        elif max_gap > 2:
            severity = "medium"
        else:
            severity = "low"
        
        return {
            "entity": canonical_id,
            "coverage": timeline,
            "gaps": gaps,
            "gap_severity": severity
        }
    
    def export_registry(self, output_path: str):
        """导出实体注册表为 JSON"""
        data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "entity_count": len(self.entities)
            },
            "entities": {k: asdict(v) for k, v in self.entities.items()},
            "entity_timeline": self.entity_timeline
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Entity registry exported to {output_path}")

    def _canonicalize(self, name: str) -> str:
        """规范化实体名称"""
        return name.lower().strip().replace("-", "_").replace(" ", "_")

if __name__ == "__main__":
    # Test case
    indexer = EntityIndexer()
    indexer.register_entity("Ti-6Al-4V", "material", "doc_001", 2020)
    indexer.register_entity("Ti6Al4V", "material", "doc_002", 2024)
    print(indexer.compute_coverage_gap("ti_6al_4v"))
