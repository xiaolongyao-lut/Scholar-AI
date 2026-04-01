# -*- coding: utf-8 -*-
"""
layers/w_layer_cross_paper_analysis.py
合卷级深度索引与跨文分析层 (W-Layer: Cross-paper Web Analysis)

第三阶段核心功能:
1. 跨文冲突检测: 分析不同文献对同一参数的结论是否一致
2. 技术趋势分析: 生成参数级别的趋势表和共识评估
3. 全局索引构建: 生成 master_global_index.json 支持卷级 RAG
4. 图表级交叉索引: 参数-图表-结论的多维索引
"""

import json
import logging
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

logger = logging.getLogger("WLayer_CrossPaperAnalysis")


class ConflictDetector:
    """
    跨文冲突检测器。
    分析同一参数在不同文献中的结论是否存在矛盾。
    """

    def __init__(self):
        self.parameter_claims = defaultdict(list)  # {param: [{source, claim, confidence}, ...]}
        self.consensus_map = {}  # {param: {consensus, disagreement_count, papers}}

    def register_parameter_claim(self, paper_id: str, parameter: str, claim: str, 
                                 confidence: float, writing_point_id: str):
        """注册一篇文献对某参数的结论。"""
        self.parameter_claims[parameter].append({
            'paper_id': paper_id,
            'parameter': parameter,
            'claim': claim,
            'confidence': confidence,
            'writing_point_id': writing_point_id,
            'timestamp': datetime.now().isoformat()
        })

    def detect_conflicts(self) -> Dict[str, Any]:
        """
        检测参数级别的冲突。
        返回冲突矩阵和共识评估。
        """
        conflicts = {
            'parameter_consensus': {},
            'high_conflict_parameters': [],
            'consensus_parameters': [],
            'conflict_matrix': {}
        }

        for param, claims in self.parameter_claims.items():
            if len(claims) < 2:
                # 单篇文献，直接通过
                conflicts['parameter_consensus'][param] = {
                    'consensus_level': 'single_source',
                    'paper_count': 1,
                    'papers': [c['paper_id'] for c in claims]
                }
                continue

            # 多篇文献：进行相似度分析
            claim_texts = [c['claim'] for c in claims]
            papers = [c['paper_id'] for c in claims]

            # 简单的文本相似度检查（可扩展为 LLM 语义相似度）
            unique_claims = len(set(claim_texts))
            paper_count = len(set(papers))

            if unique_claims == 1:
                conflict_level = 'full_agreement'
            elif unique_claims / paper_count < 0.5:
                conflict_level = 'weak_agreement'
            else:
                conflict_level = 'high_conflict'

            consensus_info = {
                'parameter': param,
                'conflict_level': conflict_level,
                'unique_claims': unique_claims,
                'paper_count': paper_count,
                'papers': papers,
                'claims': [
                    {
                        'text': c['claim'],
                        'source_papers': [cc['paper_id'] for cc in claims if cc['claim'] == c['claim']]
                    }
                    for c in claims
                ]
            }

            conflicts['parameter_consensus'][param] = consensus_info

            if conflict_level == 'high_conflict':
                conflicts['high_conflict_parameters'].append(consensus_info)
            elif conflict_level == 'full_agreement':
                conflicts['consensus_parameters'].append(consensus_info)

        logger.info(f"冲突检测完成: {len(conflicts['high_conflict_parameters'])} 个高冲突参数, "
                   f"{len(conflicts['consensus_parameters'])} 个共识参数")

        return conflicts

    def generate_trend_table(self, conflicts: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成技术趋势表。
        展示各参数在不同文献中的变化趋势。
        """
        trend_table = {
            'generated_at': datetime.now().isoformat(),
            'parameter_trends': {},
            'consensus_summary': {
                'full_agreement_count': len(conflicts.get('consensus_parameters', [])),
                'high_conflict_count': len(conflicts.get('high_conflict_parameters', []))
            }
        }

        for param, info in conflicts['parameter_consensus'].items():
            if info.get('conflict_level') in ['full_agreement', 'weak_agreement']:
                # 共识参数
                trend_table['parameter_trends'][param] = {
                    'consensus': True,
                    'trend': 'stable',
                    'papers_count': info['paper_count'],
                    'representative_claim': info['claims'][0]['text'] if info.get('claims') else None
                }
            else:
                # 有分歧的参数
                trend_table['parameter_trends'][param] = {
                    'consensus': False,
                    'trend': 'divergent',
                    'papers_count': info['paper_count'],
                    'claim_variants': len(info.get('claims', []))
                }

        return trend_table


class GlobalIndexBuilder:
    """
    全局索引构建器。
    生成 master_global_index.json 支持卷级 RAG 系统。
    """

    def __init__(self):
        self.parameters_index = defaultdict(list)  # {parameter: [writing_points]}
        self.figures_index = defaultdict(list)     # {figure_id: {claims, papers}}
        self.paper_map = {}                        # {paper_id: metadata}
        self.claim_index = []                      # All claims in searchable format

    def index_volume_bundle(self, bundle: Dict[str, Any], bundle_path: Path):
        """
        索引卷级数据包。
        """
        bundle_id = bundle.get('volume_id', 'unknown')

        # 索引 writing points
        for wp in bundle.get('writing_points', []):
            # 1. 参数索引
            for param in self._extract_parameters(wp.get('claim', '')):
                self.parameters_index[param].append({
                    'writing_point_id': wp.get('writing_point_id'),
                    'paper_id': wp.get('source_paper_id'),
                    'claim': wp.get('claim'),
                    'relevance_score': wp.get('relevance_score'),
                    'point_type': wp.get('point_type'),
                    'volume_id': bundle_id
                })

            # 2. Claim 索引
            self.claim_index.append({
                'writing_point_id': wp.get('writing_point_id'),
                'paper_id': wp.get('source_paper_id'),
                'volume_id': bundle_id,
                'claim': wp.get('claim'),
                'point_type': wp.get('point_type'),
                'relevance_score': wp.get('relevance_score')
            })

        # 索引图表
        for fig in bundle.get('figures', []):
            fig_id = fig.get('figure_id')
            self.figures_index[fig_id] = {
                'figure_number': fig.get('figure_number'),
                'caption': fig.get('caption'),
                'papers': list(set(wp.get('source_paper_id') for wp in bundle.get('writing_points', [])
                                  if fig_id in wp.get('linked_figures', []))),
                'volume_id': bundle_id,
                'reference_count': len([wp for wp in bundle.get('writing_points', [])
                                       if fig_id in wp.get('linked_figures', [])])
            }

        # 记录卷信息
        self.paper_map[bundle_id] = {
            'bundle_path': str(bundle_path),
            'paper_count': bundle.get('paper_count', 0),
            'created_at': bundle.get('created_at'),
            'stats': bundle.get('stats', {})
        }

    @staticmethod
    def _extract_parameters(text: str) -> Set[str]:
        """从文本中提取工艺参数。"""
        parameters = set()
        param_keywords = [
            'power', 'speed', 'frequency', 'temperature', 'pressure',
            'laser power', 'scan speed', 'heat input', 'cooling rate',
            'composition', 'content', 'ratio', 'percentage', 'wt%', 'at%'
        ]
        text_lower = text.lower()
        for param in param_keywords:
            if param in text_lower:
                parameters.add(param)
        return parameters

    def build_master_index(self) -> Dict[str, Any]:
        """
        构建主索引文件。
        """
        master_index = {
            'schema_version': 'v3.cross-paper-aware',
            'generated_at': datetime.now().isoformat(),
            'statistics': {
                'unique_parameters': len(self.parameters_index),
                'indexed_claims': len(self.claim_index),
                'indexed_figures': len(self.figures_index),
                'volumes': len(self.paper_map)
            },
            'parameter_index': dict(self.parameters_index),
            'figure_index': dict(self.figures_index),
            'claim_index': self.claim_index,
            'volume_metadata': self.paper_map
        }

        logger.info(f"主索引构建完成: {master_index['statistics']}")
        return master_index

    def export_to_file(self, output_path: Path) -> bool:
        """导出主索引文件。"""
        try:
            index = self.build_master_index()
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            logger.info(f"主索引已导出: {output_path}")
            return True
        except Exception as e:
            logger.error(f"导出主索引失败: {e}")
            return False


class CrossPaperAnalyzer:
    """
    跨文分析协调器。
    整合冲突检测和全局索引构建。
    """

    def __init__(self):
        self.conflict_detector = ConflictDetector()
        self.index_builder = GlobalIndexBuilder()

    def analyze_volume_bundle(self, bundle: Dict[str, Any], bundle_path: Path) -> Dict[str, Any]:
        """
        对卷级数据包进行全面的跨文分析。
        """
        logger.info(f"开始跨文分析: {bundle.get('volume_id')}")

        # 1. 提取参数和结论
        for wp in bundle.get('writing_points', []):
            paper_id = wp.get('source_paper_id', 'unknown')
            writing_point_id = wp.get('writing_point_id')
            claim = wp.get('claim', '')

            # 提取参数
            for param in self.index_builder._extract_parameters(claim):
                self.conflict_detector.register_parameter_claim(
                    paper_id=paper_id,
                    parameter=param,
                    claim=claim,
                    confidence=wp.get('relevance_score', 0.5),
                    writing_point_id=writing_point_id
                )

        # 2. 检测冲突
        conflicts = self.conflict_detector.detect_conflicts()

        # 3. 生成趋势表
        trends = self.conflict_detector.generate_trend_table(conflicts)

        # 4. 构建索引
        self.index_builder.index_volume_bundle(bundle, bundle_path)

        return {
            'volume_id': bundle.get('volume_id'),
            'analysis_timestamp': datetime.now().isoformat(),
            'conflict_analysis': conflicts,
            'technology_trends': trends,
            'status': 'cross_paper_analysis_complete'
        }

    def generate_final_report(self, output_path: Path) -> bool:
        """
        生成最终的跨文分析报告。
        """
        try:
            report = {
                'schema_version': 'v3.cross-paper-aware',
                'generated_at': datetime.now().isoformat(),
                'master_index': self.index_builder.build_master_index(),
                'conflict_summary': {
                    'total_parameters_tracked': len(self.conflict_detector.parameter_claims),
                    'conflict_detection_timestamp': datetime.now().isoformat()
                }
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

            logger.info(f"最终报告已生成: {output_path}")
            return True
        except Exception as e:
            logger.error(f"生成最终报告失败: {e}")
            return False


def main():
    """示例用法。"""
    import argparse

    parser = argparse.ArgumentParser(description='卷级跨文分析和全局索引构建')
    parser.add_argument('--volume-bundle', required=True, help='卷级数据包 JSON 路径')
    parser.add_argument('--output', required=True, help='输出分析报告路径')

    args = parser.parse_args()

    try:
        with open(args.volume_bundle, 'r', encoding='utf-8') as f:
            bundle = json.load(f)

        analyzer = CrossPaperAnalyzer()
        result = analyzer.analyze_volume_bundle(bundle, Path(args.volume_bundle))
        analyzer.generate_final_report(Path(args.output))

        print(json.dumps({
            'status': 'success',
            'output': str(Path(args.output).resolve())
        }, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()
