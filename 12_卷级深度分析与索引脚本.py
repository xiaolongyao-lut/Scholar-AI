# -*- coding: utf-8 -*-
"""
12_卷级深度分析与索引脚本.py
卷级合卷后的自动深度分析脚本 (第二/三阶段整合)

功能:
1. 从 volume_bundle.json 加载卷级数据
2. 自动触发第三阶段跨文分析
3. 生成冲突检测报告和技术趋势表
4. 构建全局索引支持 RAG 查询
5. 生成卷级深度分析报告
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VolumeDeepAnalysis")

try:
    from layers.v_layer_volume_bundle import build_volume_bundle, dump_volume_bundle
    from layers.w_layer_cross_paper_analysis import CrossPaperAnalyzer
except ImportError as e:
    logger.error(f"导入失败: {e}")
    sys.exit(1)


def analyze_volume_bundle(bundle_path: Path, output_dir: Path) -> dict:
    """
    对卷级数据包进行深度分析。
    """
    logger.info(f"加载卷级数据包: {bundle_path}")

    try:
        with open(bundle_path, 'r', encoding='utf-8') as f:
            bundle = json.load(f)
    except Exception as e:
        logger.error(f"加载卷数据失败: {e}")
        return {"status": "failed", "error": str(e)}

    volume_id = bundle.get('volume_id', 'unknown')
    logger.info(f"卷 ID: {volume_id}, 包含 {bundle.get('paper_count', 0)} 篇文献")

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 第三阶段: 跨文分析
    logger.info(">>> [第三阶段] 开始卷级深度分析...")
    analyzer = CrossPaperAnalyzer()
    analysis_result = analyzer.analyze_volume_bundle(bundle, bundle_path)

    # 导出冲突检测报告
    conflict_report_path = output_dir / f"03_conflict_analysis_{volume_id}.json"
    try:
        with open(conflict_report_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result['conflict_analysis'], f, ensure_ascii=False, indent=2)
        logger.info(f"✓ 冲突检测报告: {conflict_report_path}")
    except Exception as e:
        logger.warning(f"保存冲突报告失败: {e}")

    # 导出技术趋势表
    trend_report_path = output_dir / f"04_technology_trends_{volume_id}.json"
    try:
        with open(trend_report_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result['technology_trends'], f, ensure_ascii=False, indent=2)
        logger.info(f"✓ 技术趋势表: {trend_report_path}")
    except Exception as e:
        logger.warning(f"保存趋势报告失败: {e}")

    # 构建并导出全局索引
    master_index_path = output_dir / f"05_master_global_index_{volume_id}.json"
    try:
        analyzer.index_builder.export_to_file(master_index_path)
        logger.info(f"✓ 全局索引: {master_index_path}")
    except Exception as e:
        logger.warning(f"保存全局索引失败: {e}")

    # 生成完整的深度分析报告
    deep_analysis_report = {
        'schema_version': 'v3.volume-deep-analysis',
        'volume_id': volume_id,
        'generated_at': datetime.now().isoformat(),
        'pipeline_phases': {
            'phase_1_intelligence_injection': 'completed (LLM-powered claim extraction)',
            'phase_2_batch_automation': 'completed (multi-paper processing)',
            'phase_3_cross_paper_indexing': 'completed'
        },
        'analysis_results': {
            'conflict_analysis': f"{conflict_report_path}",
            'technology_trends': f"{trend_report_path}",
            'master_global_index': f"{master_index_path}"
        },
        'statistics': {
            'paper_count': bundle.get('paper_count', 0),
            'writing_point_count': bundle.get('stats', {}).get('writing_point_count', 0),
            'figure_count': bundle.get('stats', {}).get('figure_count', 0),
            'unique_parameters_tracked': len(analyzer.conflict_detector.parameter_claims),
            'conflict_parameters': len(analysis_result['conflict_analysis'].get('high_conflict_parameters', [])),
            'consensus_parameters': len(analysis_result['conflict_analysis'].get('consensus_parameters', []))
        },
        'status': 'deep_analysis_complete'
    }

    report_path = output_dir / f"02_volume_deep_analysis_report_{volume_id}.json"
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(deep_analysis_report, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ 深度分析报告: {report_path}")
    except Exception as e:
        logger.warning(f"保存分析报告失败: {e}")

    return {
        "status": "success",
        "volume_id": volume_id,
        "analysis_report": str(report_path),
        "conflict_report": str(conflict_report_path),
        "trend_report": str(trend_report_path),
        "master_index": str(master_index_path),
        "statistics": deep_analysis_report['statistics']
    }


def main():
    parser = argparse.ArgumentParser(
        description='卷级深度分析与全局索引构建脚本 (第三阶段)'
    )
    parser.add_argument('bundle_json', help='卷级数据包 (volume_bundle.json) 路径')
    parser.add_argument('--output', default='volume_analysis_output', help='输出目录')

    args = parser.parse_args()

    try:
        bundle_path = Path(args.bundle_json)
        output_dir = Path(args.output) / bundle_path.stem

        result = analyze_volume_bundle(bundle_path, output_dir)

        logger.info("\n" + "="*60)
        logger.info("卷级深度分析完成!")
        logger.info("="*60)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"深度分析失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
