from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import asdict

from .contracts import CONTRACT_VERSION, make_bound_contract, is_bound_contract_ready


class KLayerIndexBuilder:
    """
    K-Layer: Knowledge Indexing & Quality Gates.
    Standardizes the conversion of raw extraction data into structured bundles and views.
    """

    def __init__(self, schema_version: str = CONTRACT_VERSION):
        self.schema_version = schema_version

    @staticmethod
    def build_stage_manifest(
        extract: Dict[str, Any],
        bound: Dict[str, Any],
        analysis: Dict[str, Any],
        material_pack: Optional[Dict[str, Any]] = None,
        figure_pack: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Tracks the status and counts across different pipeline stages."""
        return {
            'stage_01_extract': {
                'status': extract.get('status', 'unknown'),
                'key_counts': {
                    'sections': len(extract.get('sections', []) or []),
                    'chunks': len(extract.get('chunks', []) or []),
                    'figures': len(extract.get('figures', []) or []),
                    'tables': len(extract.get('tables', []) or []),
                },
            },
            'stage_02_binding': {
                'status': bound.get('status', 'unknown'),
                'key_counts': {
                    'relation_edges': len(bound.get('relation_edges', []) or []),
                    'evidence_clusters': len(bound.get('evidence_clusters', []) or []),
                },
            },
            'stage_03_analysis': {
                'status': analysis.get('status', 'unknown'),
                'goal': analysis.get('goal', ''),
                'writing_points': len(analysis.get('writing_points', []) or []),
            }
        }

    @staticmethod
    def build_quality_gates(analysis: Dict[str, Any], bound: Dict[str, Any]) -> Dict[str, Any]:
        """Pass/Fail criteria for the evidence network."""
        wp_cards = analysis.get('selected_writing_points', []) or []
        edges = bound.get('relation_edges', []) or []
        clusters = bound.get('evidence_clusters', []) or []
        
        # Criteria
        has_writing_points = len(wp_cards) > 0
        has_evidence_links = len(edges) > 0
        has_clusters = len(clusters) > 0
        boundary_ok = all(bool(wp.get('boundary_type')) and bool(wp.get('boundary_note')) for wp in wp_cards)
        
        return {
            'has_writing_points': has_writing_points,
            'has_evidence_links': has_evidence_links,
            'has_clusters': has_clusters,
            'writing_points_have_boundary_notes': boundary_ok,
            'overall_pass': all([has_writing_points, has_evidence_links, has_clusters, boundary_ok]),
        }

    def build_project_view(
        self,
        extract: Dict[str, Any],
        bound: Dict[str, Any],
        analysis: Dict[str, Any],
        goal: str
    ) -> Dict[str, Any]:
        """Creates a machine-readable comprehensive view of the project."""
        return {
            'schema_version': self.schema_version,
            'source_pdf': extract.get('source_pdf', ''),
            'goal': goal,
            'stage_manifest': self.build_stage_manifest(extract, bound, analysis),
            'quality_gates': self.build_quality_gates(analysis, bound),
            'writing_points': analysis.get('selected_writing_points', []),
            'figures': analysis.get('selected_figures', []),
            'tables': analysis.get('selected_tables', []),
            'parameters': analysis.get('selected_parameters', []),
            'results': analysis.get('selected_results', []),
            'references': analysis.get('selected_references', []),
        }

    @staticmethod
    def build_human_view(project_view: Dict[str, Any]) -> str:
        """Generates a Markdown human-readable summary of the project state."""
        def short_text(text: str, limit: int = 180) -> str:
            text = ' '.join((text or '').split())
            if len(text) <= limit:
                return text
            return text[: limit - 1].rstrip() + '…'

        lines: List[str] = []
        lines.append(f"# Literature Processor - Project View (K-Layer)\n")
        lines.append(f"- **Source**: {Path(project_view.get('source_pdf', '')).name}")
        lines.append(f"- **Current Goal**: {project_view.get('goal', '')}\n")

        gates = project_view.get('quality_gates', {})
        lines.append("## Quality Gates")
        for k, v in gates.items():
            lines.append(f"- {k.replace('_', ' ').capitalize()}: {'✅ PASS' if v else '❌ FAIL'}")
        lines.append("")

        lines.append("## Key Writing Points")
        for idx, wp in enumerate(project_view.get('writing_points', [])[:8], start=1):
            lines.append(f"### {idx}. {wp.get('claim', '')}")
            lines.append(f"- type: `{wp.get('point_type', '')}` | boundary: `{wp.get('boundary_type', '')}`")
            lines.append(f"- evidence: {len(wp.get('linked_figures', []))} figs, {len(wp.get('linked_tables', []))} tables")
            lines.append(f"- snippet: {short_text(wp.get('source_text', ''), 200)}")
            lines.append("")

        lines.append(f"\n---")
        lines.append(f"Generated by K-Layer (Schema: {project_view.get('schema_version', 'N/A')})")
        return '\n'.join(lines)


def export_bundle(project_view: Dict[str, Any], output_path: str | Path) -> None:
    """Exports the final consolidated bundle to a JSON file."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(project_view, f, ensure_ascii=False, indent=2)


class KLayerManager:
    """Convenience orchestrator for K-Layer outputs in integrated pipeline."""

    def __init__(self, output_dir: str | Path, schema_version: str = CONTRACT_VERSION):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.builder = KLayerIndexBuilder(schema_version=schema_version)

    def validate_quality_gates(self, analysis: Dict[str, Any], bound: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
        gates = self.builder.build_quality_gates(analysis, bound)
        failures = [k for k, v in gates.items() if k != 'overall_pass' and not bool(v)]
        result = {'overall_pass': bool(gates.get('overall_pass')), 'failures': failures, 'gates': gates}
        if strict and not result['overall_pass']:
            raise ValueError(f"Quality gates failed: {', '.join(failures)}")
        return result

    def build_project_view(self, extract: Dict[str, Any], bound: Dict[str, Any], analysis: Dict[str, Any], goal: str) -> Dict[str, Any]:
        project_view = self.builder.build_project_view(extract, bound, analysis, goal)
        export_bundle(project_view, self.output_dir / 'project_view.json')
        human_view = self.builder.build_human_view(project_view)
        (self.output_dir / 'human_view.md').write_text(human_view, encoding='utf-8')
        return project_view
