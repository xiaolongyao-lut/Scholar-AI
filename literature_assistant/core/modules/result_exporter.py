"""
Result Exporter Module
Exports scoring results to various formats (JSON, CSV, Markdown)
"""

import json
import logging
import csv
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from modules.paper_processor import PaperProcessReport
from modules.configuration_manager import get_configuration

logger = logging.getLogger(__name__)


class ResultExporter:
    """Exports batch processing results to structured and human-readable files"""

    def __init__(self, config=None):
        """Initialize exporter"""
        self.config = config or get_configuration()

    def export_all(self, reports: List[PaperProcessReport], output_dir: str, base_name: str = "scoring_results"):
        """
        Export reports in all supported formats
        
        Args:
            reports: List of reports to export
            output_dir: Target directory
            base_name: Base filename (without extension)
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_base = f"{base_name}_{timestamp}"

        # Export formats
        json_file = self.export_json(reports, str(out_path / f"{final_base}.json"))
        csv_file = self.export_csv(reports, str(out_path / f"{final_base}.csv"))
        md_file = self.export_markdown_batch(reports, str(out_path / f"{final_base}.md"))
        
        return {
            "json": json_file,
            "csv": csv_file,
            "markdown": md_file
        }

    def export_json(self, reports: List[PaperProcessReport], file_path: str) -> str:
        """Export raw data to JSON"""
        data = []
        for r in reports:
            report_dict = {
                "paper_id": r.paper_id,
                "source_pdf": r.source_pdf,
                "overall_score": round(r.overall_score, 4),
                "overall_confidence": round(r.overall_confidence, 4),
                "goals": {}
            }
            for goal, res in r.goal_results.items():
                report_dict["goals"][goal] = {
                    "max_score": round(res.max_score, 4),
                    "average_score": round(res.average_score, 4),
                    "hits_count": res.hits_count,
                    "quality": res.quality_label,
                    "best_claim": res.best_claim,
                    "page": res.best_page,
                    "evidence_types": res.evidence_types
                }
            data.append(report_dict)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported JSON to {file_path}")
        return file_path

    def export_csv(self, reports: List[PaperProcessReport], file_path: str) -> str:
        """Export summary to CSV"""
        if not reports:
            return ""

        # Flatten results for CSV
        goals = sorted(list(reports[0].goal_results.keys()))
        headers = ["Paper ID", "Overall Score", "Confidence"]
        for g in goals:
            headers.append(f"{g} Score")
            headers.append(f"{g} Hits")

        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            for r in reports:
                row = [r.paper_id, round(r.overall_score, 4), round(r.overall_confidence, 4)]
                for g in goals:
                    res = r.goal_results.get(g)
                    if res:
                        row.append(round(res.max_score, 4))
                        row.append(res.hits_count)
                    else:
                        row.extend([0.0, 0])
                writer.writerow(row)

        logger.info(f"Exported CSV to {file_path}")
        return file_path

    def export_markdown_batch(self, reports: List[PaperProcessReport], file_path: str) -> str:
        """Export human-readable summary to Markdown"""
        lines = [
            "# 学术论文评分系统 - 批处理总结报告",
            f"**处理日期**: {datetime.now().strftime('%Y-%m-0%d %H:%M:%S')}",
            f"**文献总数**: {len(reports)}",
            "",
            "## 1. 评分纵览",
            "",
            "| 文献 ID | 总体评分 | 可信度 | 最高质量目标 |",
            "| :--- | :--- | :--- | :--- |"
        ]

        for r in reports:
            # Find best performing goal
            best_goal = max(r.goal_results.items(), key=lambda x: x[1].max_score, default=(None, None))
            bg_name = best_goal[0] or "N/A"
            bg_score = best_goal[1].max_score if best_goal[1] else 0.0
            
            lines.append(f"| {r.paper_id} | {r.overall_score:.2f} | {r.overall_confidence:.2f} | {bg_name} ({bg_score:.2f}) |")

        lines.append("")
        lines.append("## 2. 详细证据提取")
        
        for r in reports:
            lines.append(f"\n### 文献: {r.paper_id}")
            lines.append(f"- **总分**: {r.overall_score:.4f}")
            lines.append("- **核心证据列表**:")
            
            for goal, res in r.goal_results.items():
                if res.hits_count > 0:
                    lines.append(f"  - **[{goal}]** (得分: {res.max_score:.2f}, 类型: {', '.join(res.evidence_types)})")
                    lines.append(f"    - > {res.best_claim}")
                    lines.append(f"    - *来源: 第 {res.best_page} 页, 块 {res.best_chunk_id}*")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
            
        logger.info(f"Exported Markdown to {file_path}")
        return file_path
