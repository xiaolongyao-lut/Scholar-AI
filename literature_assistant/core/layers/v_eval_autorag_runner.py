# -*- coding: utf-8 -*-
"""
AutoRAG Evaluation Runner (v2.0 Production)
Role: Benchmarking, Recall Analysis & Q&A Synthesis

职责边界:
    1. 从现有 chunks / raw_extract / MaterialPack 生成符合 AutoRAG 官方 schema 的
       corpus.parquet 和 qa.parquet
    2. 调用 `autorag evaluate` CLI 运行检索评测
    3. 解析 trial_dir / summary.csv 并返回结构化结果
    4. 不做业务推理、不做 LLM 调用

AutoRAG 官方 Schema 对齐:
    qa.parquet:     qid (str) / query (str) / retrieval_gt (list) / generation_gt (list)
    corpus.parquet: doc_id (str) / contents (str) / metadata (dict)

依赖策略:
    - pandas + pyarrow: 必装 (parquet 读写)
    - autorag: 运行时 CLI 依赖, 仅在 run_retrieval_benchmark() 时校验
    - 缺依赖时明确报错, 不静默失败
"""

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── 可选依赖探测 ─────────────────────────────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

# ─── 模块级日志 ───────────────────────────────────────────────────
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())


class AutoRAGRunner:
    """
    AutoRAG 评测运行器: 生成合规数据集 + 调用官方 CLI 进行检索评测。

    使用示例::

        runner = AutoRAGRunner(data_path="./data", output_dir="./autorag_out")
        qa_path = runner.generate_eval_set()
        result = runner.run_retrieval_benchmark(config_path="config.yaml")
        print(result["summary_csv"])
    """

    # AutoRAG 官方 qa.parquet 必须列
    QA_REQUIRED_COLUMNS: tuple = ("qid", "query", "retrieval_gt", "generation_gt")
    # AutoRAG 官方 corpus.parquet 必须列
    CORPUS_REQUIRED_COLUMNS: tuple = ("doc_id", "contents", "metadata")

    # 支持的文本文件后缀 (用于文件系统扫描)
    TEXT_SUFFIXES: set = {".txt", ".md", ".rst", ".json"}

    # Manifest 文件名
    MANIFEST_FILE: str = "autorag_manifest.json"

    def __init__(
        self,
        data_path: str = "./data",
        output_dir: str = "./autorag_out"
    ) -> None:
        """
        初始化 AutoRAG Runner。

        Args:
            data_path: 数据源根目录 (用于文件系统扫描模式)
            output_dir: 输出目录 (parquet 和 manifest 将写入此处)

        Raises:
            ImportError: 缺少 pandas 或 pyarrow 时
        """
        if not HAS_PANDAS:
            raise ImportError(
                "AutoRAGRunner requires pandas and pyarrow. "
                "Install via: pip install pandas pyarrow"
            )

        self.data_path: Path = Path(data_path)
        self.output_dir: Path = Path(output_dir)
        self.qa_path: Path = self.output_dir / "qa.parquet"
        self.corpus_path: Path = self.output_dir / "corpus.parquet"
        self.manifest_path: Path = self.output_dir / self.MANIFEST_FILE

        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "AutoRAGRunner initialized: data_path=%s, output_dir=%s",
            self.data_path, self.output_dir
        )

    # ─── 内部工具 ──────────────────────────────────────────────────

    @staticmethod
    def _make_doc_id() -> str:
        """生成确定性 doc_id。"""
        return f"doc_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _make_qid() -> str:
        """生成确定性 qid。"""
        return f"q_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _serialize_metadata(meta: Any) -> str:
        """
        将 metadata 序列化为 JSON 字符串以确保 parquet 兼容性。
        AutoRAG 官方接受 dict 或 JSON string 格式的 metadata。
        """
        if meta is None:
            return "{}"
        if isinstance(meta, str):
            return meta
        try:
            return json.dumps(meta, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "{}"

    def _write_manifest(
        self,
        qa_path: str,
        corpus_path: str,
        qa_count: int,
        corpus_count: int,
        source_mode: str
    ) -> str:
        """写入 companion manifest JSON。"""
        manifest = {
            "schema_version": "autorag_v2",
            "qa_data_path": qa_path,
            "corpus_data_path": corpus_path,
            "qa_count": qa_count,
            "corpus_count": corpus_count,
            "source_mode": source_mode,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
        }
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.info("Manifest written to: %s", self.manifest_path)
        return str(self.manifest_path)

    @classmethod
    def _validate_qa_schema(cls, df: "pd.DataFrame") -> None:
        """验证 qa.parquet DataFrame 是否包含必须列。"""
        missing = set(cls.QA_REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"qa.parquet schema violation: missing columns {missing}. "
                f"Required: {cls.QA_REQUIRED_COLUMNS}"
            )

    @classmethod
    def _validate_corpus_schema(cls, df: "pd.DataFrame") -> None:
        """验证 corpus.parquet DataFrame 是否包含必须列。"""
        missing = set(cls.CORPUS_REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"corpus.parquet schema violation: missing columns {missing}. "
                f"Required: {cls.CORPUS_REQUIRED_COLUMNS}"
            )

    # ─── 公开 API: 生成评测集 ──────────────────────────────────────

    def generate_eval_set(
        self,
        chunks: Optional[List[Dict[str, Any]]] = None,
        raw_extract: Optional[Dict[str, Any]] = None,
        material_pack: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        生成符合 AutoRAG 官方 schema 的 corpus.parquet 和 qa.parquet。

        支持三种数据源模式 (按优先级):
        1. chunks: 直接传入 list[dict]，每项至少有 text 字段
        2. raw_extract: 传入 raw_extract dict (含 chunks 键)
        3. material_pack: 传入 MaterialPack dict
        4. 以上都未传: 扫描 self.data_path 目录中的 txt/md 文件

        Args:
            chunks: 文本块列表
            raw_extract: 原始解析产物 dict
            material_pack: MaterialPack dict

        Returns:
            qa.parquet 的绝对路径字符串

        Raises:
            ValueError: 无法从任何来源获取数据时
        """
        corpus_data: List[Dict[str, Any]] = []
        qa_data: List[Dict[str, Any]] = []
        source_mode: str = "unknown"

        # ── 模式 1: chunks 直传 ──
        if chunks and isinstance(chunks, list):
            source_mode = "chunks_direct"
            logger.info("Generating eval set from %d direct chunks", len(chunks))
            for idx, chunk in enumerate(chunks):
                text = chunk.get("text", chunk.get("contents", chunk.get("content", "")))
                if not text or not str(text).strip():
                    continue
                text = str(text).strip()

                doc_id = chunk.get("doc_id", chunk.get("chunk_id", self._make_doc_id()))
                source = chunk.get("source", chunk.get("section_title", f"chunk_{idx}"))

                corpus_data.append({
                    "doc_id": str(doc_id),
                    "contents": text[:4000],
                    "metadata": self._serialize_metadata({
                        "source": source,
                        "chunk_index": idx,
                        "origin": "direct_chunks"
                    })
                })

                qa_data.append({
                    "qid": self._make_qid(),
                    "query": f"Summarize the key points in: {source}",
                    "retrieval_gt": [[str(doc_id)]],
                    "generation_gt": [text[:300]]
                })

        # ── 模式 2: raw_extract ──
        elif raw_extract and isinstance(raw_extract, dict):
            source_mode = "raw_extract"
            raw_chunks = raw_extract.get("chunks", [])
            logger.info("Generating eval set from raw_extract (%d chunks)", len(raw_chunks))
            for idx, chunk in enumerate(raw_chunks):
                text = chunk.get("text", "")
                if not text or not str(text).strip():
                    continue
                text = str(text).strip()

                doc_id = chunk.get("chunk_id", self._make_doc_id())
                section = chunk.get("section_title", f"section_{idx}")

                corpus_data.append({
                    "doc_id": str(doc_id),
                    "contents": text[:4000],
                    "metadata": self._serialize_metadata({
                        "source": section,
                        "page": chunk.get("page", 0),
                        "origin": "raw_extract"
                    })
                })

                qa_data.append({
                    "qid": self._make_qid(),
                    "query": f"What does the section '{section}' discuss?",
                    "retrieval_gt": [[str(doc_id)]],
                    "generation_gt": [text[:300]]
                })

        # ── 模式 3: material_pack ──
        elif material_pack and isinstance(material_pack, dict):
            source_mode = "material_pack"
            materials = material_pack.get("materials", material_pack.get("chunks", []))
            logger.info("Generating eval set from material_pack (%d items)", len(materials))
            for idx, item in enumerate(materials):
                text = item.get("text", item.get("content", ""))
                if not text or not str(text).strip():
                    continue
                text = str(text).strip()

                doc_id = item.get("doc_id", item.get("id", self._make_doc_id()))

                corpus_data.append({
                    "doc_id": str(doc_id),
                    "contents": text[:4000],
                    "metadata": self._serialize_metadata({
                        "source": item.get("source", f"material_{idx}"),
                        "origin": "material_pack"
                    })
                })

                qa_data.append({
                    "qid": self._make_qid(),
                    "query": f"What information is provided about {item.get('source', 'this topic')}?",
                    "retrieval_gt": [[str(doc_id)]],
                    "generation_gt": [text[:300]]
                })

        # ── 模式 4: 文件系统扫描 ──
        else:
            source_mode = "filesystem_scan"
            logger.info("Scanning filesystem at %s for text files", self.data_path)
            if self.data_path.exists() and self.data_path.is_dir():
                for file_path in sorted(self.data_path.rglob("*")):
                    if file_path.is_file() and file_path.suffix.lower() in self.TEXT_SUFFIXES:
                        try:
                            content = file_path.read_text(encoding="utf-8").strip()
                            if not content:
                                continue

                            doc_id = self._make_doc_id()
                            corpus_data.append({
                                "doc_id": doc_id,
                                "contents": content[:4000],
                                "metadata": self._serialize_metadata({
                                    "source": file_path.name,
                                    "path": str(file_path),
                                    "origin": "filesystem"
                                })
                            })

                            qa_data.append({
                                "qid": self._make_qid(),
                                "query": f"What is discussed in {file_path.name}?",
                                "retrieval_gt": [[doc_id]],
                                "generation_gt": [content[:300]]
                            })
                        except Exception as exc:
                            logger.warning("Failed to read %s: %s", file_path, exc)

        # ── 兜底: 无数据时抛异常 ──
        if not corpus_data:
            raise ValueError(
                "No valid data found from any source. "
                "Provide chunks, raw_extract, material_pack, or ensure data_path contains text files."
            )

        # ── 写入 parquet ──
        df_corpus = pd.DataFrame(corpus_data)
        self._validate_corpus_schema(df_corpus)
        df_corpus.to_parquet(self.corpus_path, index=False)
        logger.info("Saved corpus.parquet (%d rows) to: %s", len(df_corpus), self.corpus_path)

        df_qa = pd.DataFrame(qa_data)
        self._validate_qa_schema(df_qa)
        df_qa.to_parquet(self.qa_path, index=False)
        logger.info("Saved qa.parquet (%d rows) to: %s", len(df_qa), self.qa_path)

        # ── 写入 manifest ──
        self._write_manifest(
            qa_path=str(self.qa_path.resolve()),
            corpus_path=str(self.corpus_path.resolve()),
            qa_count=len(df_qa),
            corpus_count=len(df_corpus),
            source_mode=source_mode
        )

        return str(self.qa_path.resolve())

    # ─── 公开 API: 运行评测 ────────────────────────────────────────

    def run_retrieval_benchmark(self, config_path: str) -> Dict[str, Any]:
        """
        调用 AutoRAG 官方 CLI 运行检索评测。

        命令:
            autorag evaluate --config <config> \\
                --qa_data_path <qa.parquet> \\
                --corpus_data_path <corpus.parquet> \\
                --project_dir <output_dir>/benchmark_project

        Args:
            config_path: AutoRAG 评测配置文件路径 (YAML)

        Returns:
            dict 包含:
                trial_dir:     str  - 试验输出目录
                summary_csv:   str  - summary.csv 绝对路径
                best_pipeline: str  - 最佳 pipeline ID
                metrics:       list - 评测指标记录

        Raises:
            FileNotFoundError: qa/corpus parquet 或 config 缺失时
            RuntimeError: autorag CLI 未安装或执行失败时
        """
        # 前置校验
        if not self.qa_path.exists() or not self.corpus_path.exists():
            raise FileNotFoundError(
                f"Evaluation datasets missing. "
                f"Expected {self.qa_path} and {self.corpus_path}. "
                "Call generate_eval_set() first."
            )

        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}"
            )

        # 检查 autorag CLI 是否可用
        if shutil.which("autorag") is None:
            raise RuntimeError(
                "autorag CLI command not found. "
                "Install via: pip install autorag"
            )

        project_dir = self.output_dir / "benchmark_project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # 构造官方评测命令
        cmd = [
            "autorag", "evaluate",
            "--config", str(config_file.resolve()),
            "--qa_data_path", str(self.qa_path.resolve()),
            "--corpus_data_path", str(self.corpus_path.resolve()),
            "--project_dir", str(project_dir.resolve())
        ]

        logger.info("Executing: %s", " ".join(cmd))
        start_time = time.perf_counter()

        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600  # 10 分钟超时
            )
            elapsed = time.perf_counter() - start_time
            logger.info(
                "AutoRAG benchmark completed in %.2fs. stdout=%d chars",
                elapsed, len(result.stdout)
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "AutoRAG execution failed (code %d):\n%s",
                exc.returncode, exc.stderr[:1000]
            )
            raise RuntimeError(
                f"AutoRAG benchmark failed (exit code {exc.returncode}): "
                f"{exc.stderr[:500]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "AutoRAG benchmark timed out after 600s"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                "autorag CLI not found. Ensure AutoRAG is installed and in PATH."
            ) from exc

        # ── 解析输出 ──
        summary_files = sorted(
            project_dir.rglob("summary.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        metrics: list = []
        best_pipeline: str = ""
        trial_dir_str: str = ""
        summary_csv_str: str = ""

        if summary_files:
            latest_summary = summary_files[0]
            trial_dir_str = str(latest_summary.parent)
            summary_csv_str = str(latest_summary)

            try:
                summary_df = pd.read_csv(latest_summary)
                metrics = summary_df.to_dict(orient="records")
                if not summary_df.empty and "pipeline_id" in summary_df.columns:
                    best_pipeline = str(summary_df.iloc[0]["pipeline_id"])
                logger.info(
                    "Parsed summary.csv: %d rows, best_pipeline=%s",
                    len(summary_df), best_pipeline
                )
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", latest_summary, exc)
        else:
            logger.warning("summary.csv not found in %s", project_dir)

        return {
            "trial_dir": trial_dir_str,
            "summary_csv": summary_csv_str,
            "best_pipeline": best_pipeline,
            "metrics": metrics
        }


# ═══════════════════════════════════════════════════════════════════
# 最小验收测试 — python -m layers.v_eval_autorag_runner
# ═══════════════════════════════════════════════════════════════════
def _run_acceptance_test() -> None:
    """
    最小验收:
    1. 从 chunks 生成 corpus.parquet + qa.parquet
    2. 验证 parquet schema 正确
    3. 验证 manifest 生成
    4. 验证 doc_id 交叉引用一致
    """
    import tempfile

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    tmpdir = tempfile.mkdtemp(prefix="autorag_runner_test_")
    data_dir = os.path.join(tmpdir, "data")
    out_dir = os.path.join(tmpdir, "output")
    os.makedirs(data_dir)

    print(f"[TEST] Temp dir: {tmpdir}")

    try:
        # ── Test 1: chunks 模式生成 ──
        test_chunks = [
            {"text": "Laser power significantly affects melt pool dynamics.",
             "source": "paper_01.pdf", "chunk_id": "c001"},
            {"text": "Nitrogen transport is driven by temperature gradients.",
             "source": "paper_02.pdf", "chunk_id": "c002"},
            {"text": "Cooling rate determines final grain morphology.",
             "source": "paper_03.pdf", "chunk_id": "c003"},
        ]

        runner = AutoRAGRunner(data_path=data_dir, output_dir=out_dir)
        qa_path = runner.generate_eval_set(chunks=test_chunks)
        assert os.path.isfile(qa_path), f"qa.parquet not found at {qa_path}"
        assert runner.corpus_path.exists(), "corpus.parquet not found"
        print("[TEST] [PASS] Eval set generated from chunks")

        # ── Test 2: Schema 验证 ──
        df_qa = pd.read_parquet(runner.qa_path)
        df_corpus = pd.read_parquet(runner.corpus_path)

        qa_cols = set(df_qa.columns)
        corpus_cols = set(df_corpus.columns)

        for col in ("qid", "query", "retrieval_gt", "generation_gt"):
            assert col in qa_cols, f"qa.parquet missing column: {col}"
        for col in ("doc_id", "contents", "metadata"):
            assert col in corpus_cols, f"corpus.parquet missing column: {col}"

        assert len(df_qa) == 3, f"Expected 3 QA rows, got {len(df_qa)}"
        assert len(df_corpus) == 3, f"Expected 3 corpus rows, got {len(df_corpus)}"
        print(f"[TEST] [PASS] Schema valid: qa={list(df_qa.columns)}, corpus={list(df_corpus.columns)}")

        # ── Test 3: doc_id 交叉引用 ──
        corpus_doc_ids = set(df_corpus["doc_id"].tolist())
        for _, row in df_qa.iterrows():
            gt_ids = row["retrieval_gt"]
            if isinstance(gt_ids, list):
                for id_group in gt_ids:
                    if isinstance(id_group, list):
                        for did in id_group:
                            assert str(did) in corpus_doc_ids, (
                                f"retrieval_gt doc_id '{did}' not in corpus"
                            )
        print("[TEST] [PASS] doc_id cross-reference valid")

        # ── Test 4: Manifest 存在 ──
        assert runner.manifest_path.exists(), "Manifest file not found"
        manifest = json.loads(runner.manifest_path.read_text(encoding="utf-8"))
        assert manifest["qa_count"] == 3
        assert manifest["corpus_count"] == 3
        assert manifest["source_mode"] == "chunks_direct"
        print(f"[TEST] [PASS] Manifest valid: {manifest['source_mode']}, {manifest['qa_count']} QA")

        # ── Test 5: raw_extract 模式 ──
        out_dir_2 = os.path.join(tmpdir, "output_raw")
        runner2 = AutoRAGRunner(data_path=data_dir, output_dir=out_dir_2)
        qa_path_2 = runner2.generate_eval_set(raw_extract={
            "chunks": [
                {"text": "Sample raw extract content.", "chunk_id": "rx001", "section_title": "Intro"}
            ]
        })
        assert os.path.isfile(qa_path_2)
        df_qa_2 = pd.read_parquet(qa_path_2)
        assert len(df_qa_2) == 1
        print("[TEST] [PASS] raw_extract mode works")

        # ── Test 6: 空数据应抛异常 ──
        out_dir_3 = os.path.join(tmpdir, "output_empty")
        runner3 = AutoRAGRunner(data_path=os.path.join(tmpdir, "nonexistent"), output_dir=out_dir_3)
        try:
            runner3.generate_eval_set(chunks=[])
            assert False, "Should have raised ValueError"
        except ValueError:
            print("[TEST] [PASS] Empty data ValueError OK")

        print("\n" + "=" * 60)
        print("[TEST] ALL PASSED - Acceptance test complete!")
        print("=" * 60)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"[TEST] Temp dir cleaned: {tmpdir}")


if __name__ == "__main__":
    _run_acceptance_test()
