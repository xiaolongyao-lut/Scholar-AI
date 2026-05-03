# 2026-05-03 LLM-Wiki + RAG 文献助手优化执行计划

## 目标

把当前 RAG 文献助手从“每次查询即时检索、即时生成、事后遗忘”的工作流，升级为“RAG 证据层 + LLM-Wiki 编译层 + citation/graph/doctor 治理层”的可回档、可审计、可长期演化系统。

核心判断：不推倒现有 RAG，不替换 TOLF / hybrid retrieval / evidence_refs；先在现有证据链上增量加入 wiki 编译、结构化 claim、持久 synthesis、引用校验和图谱影响分析。

## 执行硬规则

- 每个非平凡代码切片开始前必须创建回档点。
- 每个架构、数据、接口、评测或治理切片开始前必须搜索成熟方案或官方/上游项目做对标。
- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码，不改外部参考库。
- 产品代码优先放入 `literature_assistant/core/`。
- 计划、执行记录、交接提示放入 `docs/plans/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链、不默认启用 rerank、不改变 corpus/goldset/qrels，除非有独立 gate 和回滚记录。
- 对外部资料源 Zotero / EndNote / Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference；无法溯源的内容只能进入 draft/review。

## 本次回档点

- 回档 id：`20260503-122353-llmwiki-rag-plan`
- 回档路径：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260503-122353-llmwiki-rag-plan`
- 工作树状态：存在用户/历史改动，包含 `literature_assistant/core/query_expander.py`、多项 tests、eval scripts、`.claude/*`、`backups/` 等；本计划只新增本文档。

## 成熟方案与本地证据

### 已读本地借鉴库

|参考项目|本地路径|可借鉴点|
|---|---|---|
|PaperQA2|`C:\Users\xiao\Downloads\llmwiki借鉴库\paper-qa-main`|科学文献 RAG、metadata-aware retrieval、in-text citations、RCS、contradiction detection|
|OpenKB|`C:\Users\xiao\Downloads\llmwiki借鉴库\OpenKB-main`|short/long document split、PageIndex tree、wiki compilation、lint/watch/chat/save|
|llm-wiki-compiler|`C:\Users\xiao\Downloads\llmwiki借鉴库\llm-wiki-compiler-main`|two-phase compile、hash skip、query --save、chunk-aware query、paragraph source markers|
|obsidian-llm-wiki-local|`C:\Users\xiao\Downloads\llmwiki借鉴库\obsidian-llm-wiki-local-master`|draft approval/reject、hand-edit protection、git undo、local-first provider、inline citation toggle|
|TheKnowledge|`C:\Users\xiao\Downloads\llmwiki借鉴库\TheKnowledge-main`|source immutability、citation density、wiki validator、draft/finalize、MCP gateway|
|WikiLoom|`C:\Users\xiao\Downloads\llmwiki借鉴库\wikiloom-main`|stable chunk_id、chunk store、hybrid linking、duplicates、linked-page expansion|
|Keppi|`C:\Users\xiao\Downloads\llmwiki借鉴库\keppi-master`|graph build、blast radius、semantic search、MCP graph tools|
|OmegaWiki|`C:\Users\xiao\Downloads\llmwiki借鉴库\OmegaWiki-main`|research entity model、typed edges、papers/concepts/claims/experiments lifecycle|
|SwarmVault|`C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main`|context packs、doctor、retrieval manifest、review queues、graph share|

### 已读 `github/` RAG 参考库

|参考项目|本地路径|可借鉴点|
|---|---|---|
|LightRAG|`github/LightRAG-1.4.15`|graph RAG、entity/relation extraction、query modes、reranker as first-class capability、storage locks|
|RAG-Anything|`github/RAG-Anything-1.2.10`|multimodal document parsing、image/table/equation processors、context extractor|
|nano-graphrag|`github/nano-graphrag-0.0.8`|轻量 GraphRAG storage/query 边界|
|Knowledge-Base-Gateway|`github/Knowledge-Base-Gateway-1.2.2026.10009`|Zotero/EndNote/Obsidian 本地科研库接入、fast/deep 模式|
|WeKnora|`github/WeKnora-main`|Wiki Mode、knowledge graph UI、observability、agent orchestration|
|Quivr|`github/quivr-core-0.0.33`|文档知识库 API 与 retrieval 应用边界|
|open-webui|`github/open-webui-0.8.12`|知识库 UI、用户权限、模型/检索配置体验|

### 网上成熟方案

- Karpathy LLM-Wiki gist：`https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f`
- PaperQA2 upstream：`https://github.com/Future-House/paper-qa`
- OpenKB upstream：`https://github.com/VectifyAI/OpenKB`
- LightRAG upstream：`https://github.com/HKUDS/LightRAG`
- RAG-Anything upstream：`https://github.com/HKUDS/RAG-Anything`
- Microsoft GraphRAG upstream：`https://github.com/microsoft/graphrag`

## 当前项目证据锚点

|能力|当前文件|说明|
|---|---|---|
|RAG 主流程|`literature_assistant/core/main_rag_workflow.py`|已有 `RAGResult.evidence_refs`、SemanticRouter、RAGFlow/local fallback、generation|
|证据打包|`literature_assistant/core/evidence_packer.py`|已有 `EvidenceReference`、rank、source_labels、query_overlap_tokens|
|引用审计|`literature_assistant/core/citation_auditor.py`|已有 quote-in-source 检查，但需要扩展到 wiki claim/finalize|
|检索 provenance|`literature_assistant/core/retrieval_provenance.py`|已有 source_labels normalize/merge/attach|
|向量 store|`literature_assistant/core/chunk_vector_store.py`|已有 embedding manifest/cache guard，但缺 wiki/source registry contract|
|项目路径|`literature_assistant/core/project_paths.py`|后续 wiki/runtime 输出必须通过路径 helper 落入 workspace_artifacts|
|API 服务|`literature_assistant/core/python_adapter_server.py`、`routers/*`|后续 wiki/query/save/doctor UI contract 从这里接|
|前端|`frontend/src/*`|后续 Evidence/Wiki/Graph/Doctor 面板从现有页面增量接入|
|评测|`tools/eval/*`、`workspace_tests/evaluation_scripts/*`|后续加 wiki-aware retrieval/evidence/audit 对照，不改现有 qrels|

## 总体架构落点

```text
raw/project docs + PDFs + Zotero/EndNote/Obsidian notes
  -> source registry + stable chunks + existing RAG evidence_refs
  -> LLM-Wiki compiler writes draft wiki pages
  -> citation validator + duplicate/graph/doctor gates
  -> finalized wiki pages
  -> query reads wiki first, then linked pages, then raw RAG fallback
  -> answer can be saved as synthesis/exploration page
```

## 推荐落地目录

```text
literature_assistant/core/wiki/
  models.py
  source_registry.py
  chunk_registry.py
  page_store.py
  frontmatter.py
  compiler.py
  query.py
  citation_validator.py
  graph.py
  doctor.py
  review_queue.py
  export.py

workspace_artifacts/runtime_state/wiki/
  wiki.db
  graph.json
  retrieval_manifest.json
  review_queue.jsonl

workspace_artifacts/generated/wiki/
  index.md
  sources/
  papers/
  concepts/
  claims/
  synthesis/
  explorations/
  reports/
```

## 验证命令基线

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

## 任务编号说明

本计划从现有 master plan 的 TASK-223 后续接续，使用 `LMWR-224` 到 `LMWR-463`，共 240 个细分任务。每个任务默认执行顺序：

1. 回档。
2. 搜索成熟方案或读取本地参考项目对应实现。
3. 小范围实现。
4. focused tests / compileall / contract smoke。
5. 写回执行记录与证据路径。

## 高难任务核心代码蓝图

本节给后续执行者一份“先建骨架”的代码蓝图。实现时不要把这些片段机械粘贴后放任不管；每个切片仍必须先回档、再读取参考文件、再按现有项目 import/path/test 约束落地。蓝图的价值是先固定难点接口、数据边界和防守逻辑，避免每个 agent 重新发明一套不兼容的模型。

### 蓝图参考目录索引

|蓝图|对应任务|优先参考本项目文件|优先参考借鉴库文件|
|---|---|---|---|
|Wiki domain models|LMWR-239~253|`literature_assistant/core/evidence_packer.py`、`literature_assistant/core/chunk_models.py`、`literature_assistant/core/models/common.py`|`OmegaWiki-main/tools/research_wiki.py`、`wikiloom-main/wikiloom/frontmatter.py`、`llm-wiki-compiler-main/src/utils/types.ts`|
|Source/chunk registry|LMWR-254~268|`literature_assistant/core/chunk_vector_store.py`、`literature_assistant/core/project_paths.py`、`literature_assistant/core/db.py`|`wikiloom-main/wikiloom/chunk_store.py`、`TheKnowledge-main/src/gateway/validator.py`、`LightRAG-1.4.15/lightrag/lightrag.py`|
|Markdown page store|LMWR-269~283|`literature_assistant/core/project_paths.py`、`literature_assistant/core/manifest_builder.py`|`llm-wiki-compiler-main/src/utils/markdown.ts`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/vault.py`、`wikiloom-main/wikiloom/frontmatter.py`|
|Citation validator|LMWR-284~298|`literature_assistant/core/citation_auditor.py`、`literature_assistant/core/evidence_packer.py`|`TheKnowledge-main/src/gateway/citations.py`、`TheKnowledge-main/src/gateway/validator.py`|
|Evidence adapter|LMWR-299~313|`literature_assistant/core/evidence_packer.py`、`literature_assistant/core/retrieval_provenance.py`、`literature_assistant/core/main_rag_workflow.py`|`llm-wiki-compiler-main/src/commands/query.ts`、`PaperQA2 paperqa/types.py`|
|Compiler dry-run|LMWR-314~328|`literature_assistant/core/main_rag_workflow.py`、`literature_assistant/core/model_call_gateway.py`、`literature_assistant/core/prompt_templates/`|`llm-wiki-compiler-main/src/compiler/`、`OpenKB-main/openkb/cli.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|
|Wiki-aware retrieval|LMWR-344~358|`literature_assistant/core/hybrid_search_runtime.py`、`literature_assistant/core/layers/r_layer_hybrid_retriever.py`、`literature_assistant/core/chunk_vector_store.py`|`wikiloom-main/wikiloom/query.py`、`llm-wiki-compiler-main/src/commands/query.ts`、`keppi-master/keppi/search/semantic.py`|
|Graph/doctor/review|LMWR-359~388|`literature_assistant/core/recovery_*`、`literature_assistant/core/harness_store.py`、`literature_assistant/core/routers/*`|`keppi-master/keppi/analysis/blast_radius.py`、`swarmvault-main/packages/engine/src/doctor.ts`、`wikiloom-main/wikiloom/duplicates.py`|
|API router|LMWR-389~403|`literature_assistant/core/python_adapter_server.py`、`literature_assistant/core/routers/intelligent_chat_router.py`、`literature_assistant/core/routers/resources_router.py`|`swarmvault-main/packages/engine/src/mcp.ts`、`OpenKB-main/openkb/cli.py`|
|Frontend Wiki 工作台|LMWR-404~418|`frontend/src/lib/evidenceReferences.ts`、`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/pages/Workbench.tsx`|`swarmvault-desktop-main/src/renderer/`、`WeKnora-main/frontend/`、`LightRAG-1.4.15/lightrag_webui/`|

### 蓝图 A：`wiki/models.py`

对应任务：`LMWR-239` 到 `LMWR-253`。

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence


class WikiPageStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    FINAL = "final"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class WikiPageKind(StrEnum):
    SOURCE = "source"
    PAPER = "paper"
    CONCEPT = "concept"
    CLAIM = "claim"
    SYNTHESIS = "synthesis"
    EXPLORATION = "exploration"
    REPORT = "report"


class WikiEdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    RELATED_TO = "related_to"
    DERIVED_FROM = "derived_from"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


@dataclass(frozen=True)
class WikiEvidenceRef:
    chunk_id: str
    material_id: str
    text: str
    compressed_text: str = ""
    quote: str = ""
    label: str = ""
    source: str = ""
    source_labels: tuple[str, ...] = ()
    page: int | str | None = None
    rank: int | None = None
    score: float | str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WikiEvidenceRef":
        if not isinstance(raw, Mapping):
            raise TypeError("raw evidence reference must be a mapping")
        chunk_id = require_non_empty(str(raw.get("chunk_id") or ""), "chunk_id")
        material_id = require_non_empty(str(raw.get("material_id") or chunk_id), "material_id")
        text = str(raw.get("text") or raw.get("compressed_text") or raw.get("quote") or "").strip()
        if not text:
            raise ValueError("evidence reference must include text, compressed_text, or quote")
        labels = raw.get("source_labels") or ()
        if isinstance(labels, str):
            source_labels = (labels.strip(),) if labels.strip() else ()
        elif isinstance(labels, Sequence):
            source_labels = tuple(str(label).strip() for label in labels if str(label).strip())
        else:
            raise TypeError("source_labels must be a string or sequence of strings")
        return cls(
            chunk_id=chunk_id,
            material_id=material_id,
            text=text,
            compressed_text=str(raw.get("compressed_text") or "").strip(),
            quote=str(raw.get("quote") or "").strip(),
            label=str(raw.get("label") or "").strip(),
            source=str(raw.get("source") or "").strip(),
            source_labels=source_labels,
            page=raw.get("page"),
            rank=int(raw["rank"]) if raw.get("rank") is not None else None,
            score=raw.get("score"),
        )

    def to_citation_target(self) -> str:
        target = f"sources/{self.material_id}#{self.chunk_id}"
        if self.page is not None:
            target = f"{target};p={self.page}"
        return target


@dataclass(frozen=True)
class WikiPage:
    kind: WikiPageKind
    page_id: str
    title: str
    status: WikiPageStatus
    body: str
    evidence_refs: tuple[WikiEvidenceRef, ...] = ()
    source_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        require_non_empty(self.page_id, "page_id")
        require_non_empty(self.title, "title")
        if not isinstance(self.kind, WikiPageKind):
            raise TypeError("kind must be WikiPageKind")
        if not isinstance(self.status, WikiPageStatus):
            raise TypeError("status must be WikiPageStatus")
        if self.status is WikiPageStatus.FINAL and not self.evidence_refs and self.kind in {
            WikiPageKind.CLAIM,
            WikiPageKind.SYNTHESIS,
            WikiPageKind.PAPER,
        }:
            raise ValueError("final evidence-bearing pages require evidence_refs")

    def frontmatter(self) -> dict[str, Any]:
        return {
            "id": self.page_id,
            "kind": self.kind.value,
            "title": self.title,
            "status": self.status.value,
            "source_ids": list(self.source_ids),
            "aliases": list(self.aliases),
            "evidence_refs": [ref.__dict__ for ref in self.evidence_refs],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class WikiWritePlan:
    page: WikiPage
    relative_path: Path
    old_hash: str | None
    new_hash: str
    reason: str
```

### 蓝图 B：`wiki/source_registry.py`

对应任务：`LMWR-254` 到 `LMWR-268`。

```python
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wiki_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    page TEXT,
    section TEXT,
    span_start INTEGER,
    span_end INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES wiki_sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_wiki_chunks_source_id ON wiki_chunks(source_id);
"""


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_type: str
    title: str
    source_hash: str
    source_path: Path


@dataclass(frozen=True)
class ChunkInput:
    text: str
    chunk_index: int
    page: str | None = None
    section: str | None = None
    span_start: int | None = None
    span_end: int | None = None


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value:
        raise ValueError("value cannot be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_source_id(source_type: str, title: str, source_hash: str) -> str:
    source_type = source_type.strip().lower()
    title = title.strip()
    if not source_type or not title or not source_hash:
        raise ValueError("source_type, title, and source_hash are required")
    readable = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    readable = "-".join(part for part in readable.split("-") if part)[:64] or "source"
    return f"{source_type}-{readable}-{source_hash[:12]}"


def derive_chunk_id(source_hash: str, chunk_index: int) -> str:
    if not source_hash:
        raise ValueError("source_hash is required")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    return hashlib.sha256(f"{source_hash}:{chunk_index}".encode("utf-8")).hexdigest()[:16]


class WikiRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_source(self, record: SourceRecord, *, now_iso: str) -> bool:
        if not record.source_id or not record.source_hash:
            raise ValueError("source_id and source_hash are required")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT source_hash FROM wiki_sources WHERE source_id = ?",
                (record.source_id,),
            ).fetchone()
            if existing and existing["source_hash"] != record.source_hash:
                raise ValueError(
                    f"source immutability violation for {record.source_id}: "
                    f"{existing['source_hash']} != {record.source_hash}"
                )
            conn.execute(
                """
                INSERT INTO wiki_sources (
                    source_id, source_type, title, source_hash, source_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title = excluded.title,
                    source_path = excluded.source_path,
                    updated_at = excluded.updated_at
                """,
                (
                    record.source_id,
                    record.source_type,
                    record.title,
                    record.source_hash,
                    str(record.source_path),
                    now_iso,
                    now_iso,
                ),
            )
            return existing is None

    def replace_chunks(self, source: SourceRecord, chunks: Iterable[ChunkInput], *, now_iso: str) -> list[str]:
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("chunks cannot be empty")
        for chunk in chunk_list:
            if not chunk.text.strip():
                raise ValueError("chunk text cannot be empty")
            if chunk.chunk_index < 0:
                raise ValueError("chunk_index must be non-negative")
        with self.connect() as conn:
            conn.execute("DELETE FROM wiki_chunks WHERE source_id = ?", (source.source_id,))
            ids: list[str] = []
            for chunk in chunk_list:
                chunk_id = derive_chunk_id(source.source_hash, chunk.chunk_index)
                ids.append(chunk_id)
                conn.execute(
                    """
                    INSERT INTO wiki_chunks (
                        chunk_id, source_id, source_hash, chunk_index, text_hash, text,
                        page, section, span_start, span_end, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        source.source_id,
                        source.source_hash,
                        chunk.chunk_index,
                        sha256_text(chunk.text),
                        chunk.text,
                        chunk.page,
                        chunk.section,
                        chunk.span_start,
                        chunk.span_end,
                        now_iso,
                    ),
                )
            return ids
```

### 蓝图 C：`wiki/page_store.py`

对应任务：`LMWR-269` 到 `LMWR-283`。

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


AUTO_START = "<!-- literature-assistant:auto:start -->"
AUTO_END = "<!-- literature-assistant:auto:end -->"


@dataclass(frozen=True)
class RenderedPage:
    relative_path: Path
    text: str
    content_hash: str


def stable_slug(title: str) -> str:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    value = title.strip().lower()
    if not value:
        raise ValueError("title cannot be empty")
    chars: list[str] = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_", ".", "/"}:
            chars.append("-")
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug[:96] or hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


def render_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    if "id" not in frontmatter or "kind" not in frontmatter or "title" not in frontmatter:
        raise ValueError("frontmatter requires id, kind, and title")
    payload = json.dumps(dict(sorted(frontmatter.items())), ensure_ascii=False, indent=2)
    return f"---json\n{payload}\n---\n"


def render_page(relative_path: Path, frontmatter: Mapping[str, Any], body: str) -> RenderedPage:
    if not isinstance(relative_path, Path):
        relative_path = Path(relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("relative_path must stay inside the wiki root")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body cannot be empty")
    text = f"{render_frontmatter(frontmatter)}\n{AUTO_START}\n{body.strip()}\n{AUTO_END}\n"
    return RenderedPage(
        relative_path=relative_path,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def atomic_write_text(path: Path, text: str) -> None:
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class WikiPageStore:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = Path(wiki_root)
        self.wiki_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: Path) -> Path:
        candidate = (self.wiki_root / relative_path).resolve()
        root = self.wiki_root.resolve()
        if root not in {candidate, *candidate.parents}:
            raise ValueError(f"path escapes wiki root: {relative_path}")
        return candidate

    def write_rendered(self, rendered: RenderedPage, *, allow_overwrite: bool = True) -> None:
        target = self.resolve(rendered.relative_path)
        if target.exists() and not allow_overwrite:
            raise FileExistsError(target)
        old_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if old_text and AUTO_START not in old_text:
            raise ValueError(f"manual page lacks auto marker and will not be overwritten: {target}")
        atomic_write_text(target, rendered.text)

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        base = self.wiki_root / kind_dir if kind_dir else self.wiki_root
        if not base.exists():
            return []
        return sorted(path.relative_to(self.wiki_root) for path in base.rglob("*.md"))
```

### 蓝图 D：`wiki/citation_validator.py`

对应任务：`LMWR-284` 到 `LMWR-298`。

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


SOURCE_LINK_RE = re.compile(r"\[\[sources/(?P<source>[^#\];]+)(?:#(?P<chunk>[^;\]]+))?(?:;p=(?P<page>[^\]]+))?\]\]")
FENCE_RE = re.compile(r"```")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


class ChunkLookup(Protocol):
    def get_chunk_text(self, chunk_id: str) -> str | None:
        ...


@dataclass(frozen=True)
class CitationIssue:
    rule: str
    message: str
    line_no: int | None = None
    severity: str = "error"


@dataclass(frozen=True)
class CitationReport:
    ok: bool
    cited_claims: int
    total_claims: int
    citation_density: float
    issues: tuple[CitationIssue, ...] = field(default_factory=tuple)


def strip_code_fence_lines(text: str) -> list[tuple[int, str]]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    in_fence = False
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.search(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((idx, line))
    return out


def claim_lines(body: str) -> list[tuple[int, str]]:
    claims: list[tuple[int, str]] = []
    for line_no, line in strip_code_fence_lines(body):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("-", "*", "+")) and stripped.count("[[") == stripped.count("]]") and len(stripped) < 160:
            continue
        for sentence in SENTENCE_SPLIT_RE.split(stripped):
            sentence = sentence.strip()
            if len(sentence.split()) >= 5 or len(sentence) >= 24:
                if sentence.endswith((".", "!", "?", "。", "！", "？")):
                    claims.append((line_no, sentence))
    return claims


def validate_citations(
    body: str,
    *,
    lookup: ChunkLookup,
    final_mode: bool,
    min_density: float = 0.95,
) -> CitationReport:
    if not 0.0 <= min_density <= 1.0:
        raise ValueError("min_density must be between 0 and 1")
    claims = claim_lines(body)
    issues: list[CitationIssue] = []
    cited = 0
    for line_no, claim in claims:
        links = list(SOURCE_LINK_RE.finditer(claim))
        if not links:
            issues.append(CitationIssue("missing-citation", "claim has no source citation", line_no))
            continue
        cited += 1
        for link in links:
            chunk_id = link.group("chunk")
            if not chunk_id:
                issues.append(CitationIssue("missing-chunk", "citation lacks chunk id", line_no))
                continue
            chunk_text = lookup.get_chunk_text(chunk_id)
            if chunk_text is None:
                issues.append(CitationIssue("unknown-chunk", f"chunk not found: {chunk_id}", line_no))
    total = len(claims)
    density = 1.0 if total == 0 else cited / total
    if final_mode and density < min_density:
        issues.append(CitationIssue("citation-density", f"citation density {density:.3f} below {min_density:.3f}"))
    errors = [issue for issue in issues if issue.severity == "error"]
    return CitationReport(
        ok=not errors if final_mode else True,
        cited_claims=cited,
        total_claims=total,
        citation_density=density,
        issues=tuple(issues),
    )
```

### 蓝图 E：`wiki/evidence_adapter.py`

对应任务：`LMWR-299` 到 `LMWR-313`。

```python
from __future__ import annotations

from typing import Any, Iterable

from wiki.models import WikiEvidenceRef


def coerce_evidence_refs(raw_refs: Iterable[dict[str, Any]]) -> tuple[WikiEvidenceRef, ...]:
    if raw_refs is None:
        raise ValueError("raw_refs cannot be None")
    refs: list[WikiEvidenceRef] = []
    for raw in raw_refs:
        refs.append(WikiEvidenceRef.from_mapping(raw))
    if not refs:
        raise ValueError("at least one evidence reference is required")
    return tuple(refs)


def evidence_ref_to_markdown(ref: WikiEvidenceRef) -> str:
    quote = ref.quote or ref.compressed_text or ref.text
    if not quote.strip():
        raise ValueError("evidence reference has no quotable text")
    return f"{quote.strip()} [[{ref.to_citation_target()}]]"


def build_synthesis_body(question: str, answer: str, refs: Iterable[WikiEvidenceRef]) -> str:
    question = question.strip()
    answer = answer.strip()
    if not question:
        raise ValueError("question cannot be empty")
    if not answer:
        raise ValueError("answer cannot be empty")
    ref_tuple = tuple(refs)
    if not ref_tuple:
        raise ValueError("synthesis requires evidence references")
    evidence_lines = "\n".join(f"- {evidence_ref_to_markdown(ref)}" for ref in ref_tuple)
    return f"# {question}\n\n{answer}\n\n## Evidence\n\n{evidence_lines}\n"
```

### 蓝图 F：`wiki/compiler.py`

对应任务：`LMWR-314` 到 `LMWR-343`。

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from wiki.evidence_adapter import build_synthesis_body, coerce_evidence_refs
from wiki.models import WikiPage, WikiPageKind, WikiPageStatus, WikiWritePlan
from wiki.page_store import WikiPageStore, render_page, stable_slug


@dataclass(frozen=True)
class CompileInput:
    question: str
    answer: str
    evidence_refs: tuple[dict, ...]
    source_ids: tuple[str, ...] = ()
    save_kind: WikiPageKind = WikiPageKind.SYNTHESIS


@dataclass(frozen=True)
class CompileResult:
    dry_run: bool
    plans: tuple[WikiWritePlan, ...]
    written_paths: tuple[Path, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


class WikiCompiler:
    def __init__(self, store: WikiPageStore) -> None:
        self.store = store

    def plan_synthesis(self, item: CompileInput) -> WikiWritePlan:
        if item.save_kind not in {WikiPageKind.SYNTHESIS, WikiPageKind.EXPLORATION}:
            raise ValueError("plan_synthesis only supports synthesis or exploration pages")
        refs = coerce_evidence_refs(item.evidence_refs)
        body = build_synthesis_body(item.question, item.answer, refs)
        slug = stable_slug(item.question)
        page_id = f"{item.save_kind.value}/{slug}"
        page = WikiPage(
            kind=item.save_kind,
            page_id=page_id,
            title=item.question.strip(),
            status=WikiPageStatus.DRAFT,
            body=body,
            evidence_refs=refs,
            source_ids=item.source_ids,
        )
        relative_path = Path(item.save_kind.value) / f"{slug}.md"
        rendered = render_page(relative_path, page.frontmatter(), body)
        return WikiWritePlan(
            page=page,
            relative_path=relative_path,
            old_hash=None,
            new_hash=hashlib.sha256(rendered.text.encode("utf-8")).hexdigest(),
            reason="query-save",
        )

    def compile(self, items: Iterable[CompileInput], *, dry_run: bool) -> CompileResult:
        plans = tuple(self.plan_synthesis(item) for item in items)
        if dry_run:
            return CompileResult(dry_run=True, plans=plans)
        written: list[Path] = []
        for plan in plans:
            rendered = render_page(plan.relative_path, plan.page.frontmatter(), plan.page.body)
            self.store.write_rendered(rendered)
            written.append(plan.relative_path)
        return CompileResult(dry_run=False, plans=plans, written_paths=tuple(written))
```

### 蓝图 G：`wiki/query.py`

对应任务：`LMWR-344` 到 `LMWR-358`。

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WikiHit:
    page_id: str
    title: str
    path: Path
    score: float
    reason: str


@dataclass(frozen=True)
class WikiContextPack:
    query: str
    primary_hits: tuple[WikiHit, ...]
    linked_hits: tuple[WikiHit, ...] = field(default_factory=tuple)
    omitted: tuple[str, ...] = field(default_factory=tuple)


class WikiQueryEngine:
    def __init__(self, db_path: Path, wiki_root: Path) -> None:
        self.db_path = Path(db_path)
        self.wiki_root = Path(wiki_root)

    def search_pages(self, query: str, *, limit: int = 8) -> tuple[WikiHit, ...]:
        if not query.strip():
            raise ValueError("query cannot be empty")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not self.db_path.exists():
            return ()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT page_id, title, path, bm25(wiki_pages_fts) AS score
                FROM wiki_pages_fts
                WHERE wiki_pages_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return tuple(
            WikiHit(
                page_id=str(row["page_id"]),
                title=str(row["title"]),
                path=Path(str(row["path"])),
                score=float(row["score"]),
                reason="wiki_fts",
            )
            for row in rows
        )

    def build_context_pack(self, query: str, *, max_pages: int = 8) -> WikiContextPack:
        primary = self.search_pages(query, limit=max_pages)
        return WikiContextPack(query=query, primary_hits=primary)
```

### 蓝图 H：`wiki/doctor.py` 与 `wiki/review_queue.py`

对应任务：`LMWR-374` 到 `LMWR-388`。

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DoctorAction:
    command: str
    description: str
    safe_auto_repair: bool = False


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    label: str
    status: str
    summary: str
    detail: str = ""
    actions: tuple[DoctorAction, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: tuple[DoctorCheck, ...]


class WikiDoctor:
    def __init__(self, wiki_root: Path, db_path: Path) -> None:
        self.wiki_root = Path(wiki_root)
        self.db_path = Path(db_path)

    def run(self) -> DoctorReport:
        checks = [
            self._check_workspace(),
            self._check_registry(),
        ]
        return DoctorReport(ok=all(check.status == "ok" for check in checks), checks=tuple(checks))

    def _check_workspace(self) -> DoctorCheck:
        if self.wiki_root.exists():
            return DoctorCheck("workspace", "Workspace", "ok", "Wiki workspace exists.")
        return DoctorCheck(
            "workspace",
            "Workspace",
            "error",
            "Wiki workspace is missing.",
            actions=(DoctorAction("wiki init", "Create wiki workspace.", safe_auto_repair=True),),
        )

    def _check_registry(self) -> DoctorCheck:
        if self.db_path.exists():
            return DoctorCheck("registry", "Registry", "ok", "Wiki registry database exists.")
        return DoctorCheck(
            "registry",
            "Registry",
            "warning",
            "Wiki registry database is missing.",
            actions=(DoctorAction("wiki doctor --repair", "Initialize registry schema.", safe_auto_repair=True),),
        )
```

### 蓝图 I：`routers/wiki_router.py`

对应任务：`LMWR-389` 到 `LMWR-403`。

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/wiki", tags=["wiki"])


class WikiStatusResponse(BaseModel):
    enabled: bool
    page_count: int = 0
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class WikiCompileRequest(BaseModel):
    dry_run: bool = True
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence_refs: list[dict[str, Any]]


class WikiCompileResponse(BaseModel):
    dry_run: bool
    planned_paths: list[str]
    written_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def wiki_enabled() -> bool:
    import os
    return os.getenv("LITERATURE_ASSISTANT_WIKI_ENABLED", "0").strip() in {"1", "true", "yes", "on"}


@router.get("/status", response_model=WikiStatusResponse)
def wiki_status() -> WikiStatusResponse:
    if not wiki_enabled():
        return WikiStatusResponse(enabled=False, warnings=["wiki integration is disabled"])
    return WikiStatusResponse(enabled=True)


@router.post("/compile", response_model=WikiCompileResponse)
def wiki_compile(request: WikiCompileRequest) -> WikiCompileResponse:
    if not wiki_enabled():
        raise HTTPException(status_code=409, detail={"error_code": "wiki_disabled"})
    if not request.evidence_refs:
        raise HTTPException(status_code=422, detail={"error_code": "missing_evidence_refs"})
    return WikiCompileResponse(dry_run=request.dry_run, planned_paths=["synthesis/example.md"])
```

### 蓝图 J：首批测试文件布局

对应任务：`LMWR-250`、`LMWR-266`、`LMWR-280`、`LMWR-295`、`LMWR-309`、`LMWR-325`、`LMWR-399`。

```text
tests/wiki/
  test_models.py
  test_source_registry.py
  test_page_store.py
  test_citation_validator.py
  test_evidence_adapter.py
  test_compiler_dry_run.py
  test_wiki_router_contract.py
```

首批 focused 命令：

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant tests\wiki
```

## Wave 执行前必读文件清单

每个 Wave 开始前，执行者先读本表对应文件，再做回档和实现。读取时只摘取与本任务相关的接口/约束，不要批量复制参考项目代码。

|Wave|本项目必读|借鉴库必读|备注|
|---|---|---|---|
|Wave 0|`AGENTS.md`、`AI_WORKSPACE_GUIDE.md`、`docs/plans/README.md`、本文件|`longrun-autopilot/references/mature-solution-research.md`|先统一执行纪律和文档落点|
|Wave 1|`evidence_packer.py`、`chunk_models.py`、`models/common.py`、`retrieval_provenance.py`|`OmegaWiki-main/tools/research_wiki.py`、`wikiloom-main/wikiloom/frontmatter.py`|先定类型，不接 runtime|
|Wave 2|`chunk_vector_store.py`、`db.py`、`project_paths.py`、`sqlite_maintenance.py`|`wikiloom-main/wikiloom/chunk_store.py`、`TheKnowledge-main/src/gateway/validator.py`|关键是 stable id、hash guard、不可变 source|
|Wave 3|`project_paths.py`、`manifest_builder.py`、`material_bundler.py`|`llm-wiki-compiler-main/src/utils/markdown.ts`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/vault.py`|重点看 atomic write 和手工编辑保护|
|Wave 4|`citation_auditor.py`、`evidence_packer.py`、`prompt_templates/generation.txt`|`TheKnowledge-main/src/gateway/citations.py`、`TheKnowledge-main/src/gateway/validator.py`|不要让无引用 claim 进入 final|
|Wave 5|`main_rag_workflow.py`、`evidence_packer.py`、`retrieval_provenance.py`|`llm-wiki-compiler-main/src/commands/query.ts`、`paper-qa-main/README.md`|保持现有 evidence_refs 向后兼容|
|Wave 6|`main_rag_workflow.py`、`model_call_gateway.py`、`runtime_env.py`、`prompt_templates/`|`llm-wiki-compiler-main/src/commands/compile.ts`、`OpenKB-main/openkb/cli.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|先 dry-run，再写 draft|
|Wave 7|`model_call_gateway.py`、`runtime_env.py`、`llm_defaults.py`、`.github/skills/env-test-discipline/SKILL.md`|`paper-qa-main/README.md`、`OpenKB-main/openkb/agent/` 如存在|所有 LLM 调用必须走 env/test discipline|
|Wave 8|`hybrid_search_runtime.py`、`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`tolf_text_selector.py`|`wikiloom-main/wikiloom/query.py`、`keppi-master/keppi/search/semantic.py`|wiki-first 必须 default-off|
|Wave 9|`graph_keyword_retriever.py`、`layers/p2_conflict_detector.py`、`layers/p3_consistency_validator.py`|`keppi-master/keppi/graph/builder.py`、`keppi-master/keppi/analysis/blast_radius.py`、`OmegaWiki-main/tools/_schemas.py`|先图索引和影响分析，后自动推理|
|Wave 10|`recovery_api.py`、`recovery_store_provider.py`、`harness_store.py`、`routers/recovery_router.py`|`swarmvault-main/packages/engine/src/doctor.ts`、`wikiloom-main/wikiloom/lint.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|doctor repair 只能做安全子集|
|Wave 11|`python_adapter_server.py`、`routers/intelligent_chat_router.py`、`routers/resources_router.py`、`models/runtime.py`|`OpenKB-main/openkb/cli.py`、`swarmvault-main/packages/engine/src/mcp.ts`|API 默认 disabled contract 先行|
|Wave 12|`frontend/src/lib/evidenceReferences.ts`、`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/pages/Workbench.tsx`、`frontend/src/services/*`|`swarmvault-desktop-main/src/renderer/`、`WeKnora-main/frontend/`、`LightRAG-1.4.15/lightrag_webui/`|先工作台信息密度，不做营销页|
|Wave 13|`project_paths.py`、`runtime_env.py`、`routers/resources_router.py`|`Knowledge-Base-Gateway-1.2.2026.10009/README.md`、`keppi-master/keppi/parser/`|只读 connector，绝不写用户 Zotero/EndNote/Obsidian|
|Wave 14|`tools/eval/compare_tolf_context_selector.py`、`workspace_tests/evaluation_scripts/eval_retrieval_runtime.py`、`tests/test_eval_runtime.py`|`LightRAG-1.4.15/lightrag/evaluation/`、`paper-qa-main/README.md`|新增独立 eval，不改现有 qrels|
|Wave 15|`README.md`、`AI_WORKSPACE_GUIDE.md`、`docs/plans/runbooks/`|`llm-wiki-coordination-main/README.md`、`swarmvault-main/README.md`|迁移/发布/协作策略，不急于实现 MCP|

## 难点切片的执行备注

### Registry 切片备注

- 不要把现有 `ChunkVectorStore` 直接替换掉；先做 `WikiRegistry`，再通过 adapter 从现有 chunks/evidence_refs 注册 source/chunk。
- `chunk_id` 必须可复现，不依赖当前时间、数据库自增 id 或随机数。
- `source_hash` 变化时不要静默覆盖；进入 review 或报 immutability violation。
- 参考 `wikiloom-main/wikiloom/chunk_store.py` 的 deterministic chunk id，参考 `TheKnowledge-main/src/gateway/validator.py` 的 source immutability。

### Citation 切片备注

- `citation_auditor.py` 现在只做 response evidence quote 检查；新 validator 要能处理 markdown 页面、claim sentence、wiki citation target。
- final mode 要 fail-closed；draft mode 可以 warning-open。
- 引用密度只是一层指标，不能替代 quote/chunk existence。
- 参考 `TheKnowledge-main/src/gateway/citations.py` 的 claim detection 和 citation density。

### Compiler 切片备注

- 第一版编译器不要直接调用 LLM；先 deterministic stub + dry-run + draft writer。
- LLM 接入必须等 schema validator、citation validator、review queue 都有最小实现后再开。
- 写入必须先生成 `WikiWritePlan`，dry-run 和真实写入共用同一个 plan。
- 参考 `llm-wiki-compiler-main/src/commands/compile.ts` 的 two-phase 思路，参考 OpenKB `add_single_file` 的 short/long doc 分流。

### Wiki-aware retrieval 切片备注

- 不要把 wiki-first 直接变默认；必须 env/config gate。
- 查询顺序建议：wiki FTS -> wiki linked pages -> wiki embeddings optional -> raw RAG fallback。
- 每次 fallback 都要写 trace：为什么 fallback、wiki hits 几个、raw hits 几个。
- 参考 `wikiloom-main/wikiloom/query.py` 的 primary/secondary context，参考 `llm-wiki-compiler-main/src/commands/query.ts` 的 chunk-aware page selection。

### Doctor/review 切片备注

- doctor 的 `repair` 只能自动做安全动作：建目录、建 schema、重建 index/log/manifest。
- 修改正文、删除页面、finalize draft、resolve duplicates 都必须进入 review queue。
- review queue 的 approve/reject 要记录 reason、actor、time、old status、new status。
- 参考 SwarmVault `doctor.ts` 的 check/action 结构，参考 OLW 的 approve/reject/undo 工作流。

### API/frontend 切片备注

- API 默认返回 `wiki_disabled`，不能在无配置时偷偷创建大目录或运行编译。
- 前端 first screen 应该是工作台式状态与任务队列，不做落地页。
- UI 中不要用大段解释文字替代真实控件；以 status、doctor、review、pages、graph tabs 为主。
- Evidence UI 已经能展示 `evidence_refs`，新增 wiki 功能应从这些引用跳转到 page/citation，而不是重复造一套证据对象。

## Wave 0：治理、回档、调研固化

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-224|为 LLM-Wiki 集成建立专用 rollback/runbook 模板|`docs/plans/runbooks/`|模板包含回档、成熟方案搜索、实现、验证、显式恢复命令|
|LMWR-225|建立参考项目对照索引|`docs/plans/specs/`|列出 PaperQA/OpenKB/llmwiki/OLW/TheKnowledge/WikiLoom/Keppi/LightRAG/RAG-Anything 对照|
|LMWR-226|冻结现有 RAG evidence contract 快照|`docs/plans/specs/`、`tests/`|记录 `EvidenceReference` 当前字段和兼容边界|
|LMWR-227|补全 dirty worktree 风险记录|`.squad/decisions/inbox/` 或本文档追加|列出不得覆盖的已改文件|
|LMWR-228|定义 wiki 集成 feature flag 命名|`runtime_env.py`、spec|所有新能力默认关闭，有 env/config gate|
|LMWR-229|定义 wiki 输出路径策略|`project_paths.py`、spec|所有 wiki 产物落入 `workspace_artifacts/`|
|LMWR-230|定义只读外部参考库规则|`docs/plans/runbooks/`|明确 `github/` 与下载库不得被改|
|LMWR-231|定义任务完成证据包格式|`docs/plans/runbooks/`|Facts/Decision/Evidence/Rollback/Open/Next 模板可复用|
|LMWR-232|定义 wiki 页面状态枚举|spec|`draft/review/final/deprecated/archived` 语义清晰|
|LMWR-233|定义 claim 审计分级|spec|`passed/warning/failed/draft_only` 可机器解析|
|LMWR-234|建立 LLM-Wiki 集成风险登记表|spec|覆盖 hallucination、stale source、duplicate、license、cost、privacy|
|LMWR-235|建立 LLM-Wiki task dependency graph|spec|每个 wave 依赖和阻塞条件可追踪|
|LMWR-236|补充 Copilot/Agent 执行提示模板|`docs/plans/runbooks/`|提示强制包含回档和成熟方案搜索|
|LMWR-237|建立 wiki integration stop conditions|spec|涉及评测口径、外部写回、默认链替换必须停下确认或独立 gate|
|LMWR-238|创建 Wave 0 focused verification|tests/docs|只验证新增文档路径和无代码行为变更|

## Wave 1：数据模型与 schema

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-239|新增 wiki domain model spec|`docs/plans/specs/`|定义 Source/Paper/Concept/Claim/Synthesis/Exploration/Edge|
|LMWR-240|实现 `WikiSource` 类型草案|`literature_assistant/core/wiki/models.py`|包含 source_id/source_hash/path/title/source_type/created_at|
|LMWR-241|实现 `WikiChunk` 类型草案|`wiki/models.py`|包含 stable chunk_id/material_id/page/span/text_hash|
|LMWR-242|实现 `WikiEvidenceRef` 兼容映射|`wiki/models.py`|可从现有 `EvidenceReference` 无损转换|
|LMWR-243|实现 `WikiPaperPage` 类型草案|`wiki/models.py`|包含 metadata、summary、claims、concepts、source_ids|
|LMWR-244|实现 `WikiConceptPage` 类型草案|`wiki/models.py`|包含 aliases、sources、related_concepts、open_questions|
|LMWR-245|实现 `WikiClaimPage` 类型草案|`wiki/models.py`|包含 claim_text、evidence_refs、confidence、status|
|LMWR-246|实现 `WikiSynthesisPage` 类型草案|`wiki/models.py`|包含 question、answer、evidence_refs、derived_from_pages|
|LMWR-247|实现 `WikiEdge` 类型草案|`wiki/models.py`|支持 `supports/contradicts/extends/depends_on/related_to`|
|LMWR-248|定义 frontmatter JSON/YAML schema|`docs/plans/specs/`|每类页面必填字段和可选字段清晰|
|LMWR-249|实现 schema validation helper 草案|`wiki/schema.py`|非法类型/空 id/坏状态 fail fast|
|LMWR-250|补充 model serialization 测试|`tests/`|模型可 JSON roundtrip|
|LMWR-251|补充 EvidenceReference backward compatibility 测试|`tests/`|旧 evidence refs 不丢字段|
|LMWR-252|补充 page status transition 测试|`tests/`|非法 transition 被拒绝|
|LMWR-253|Wave 1 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 2：source registry 与 stable chunk registry

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-254|设计 source registry SQLite schema|`docs/plans/specs/`|sources/chunks/source_aliases/source_events 表结构明确|
|LMWR-255|实现 registry path resolver|`wiki/source_registry.py`|通过 `project_paths.py` 定位 runtime db|
|LMWR-256|实现 source_hash 计算|`wiki/source_registry.py`|同内容 hash 稳定，空文件拒绝|
|LMWR-257|实现 source_id 生成规则|`wiki/source_registry.py`|paper/pdf/web/note/other 有确定性 id|
|LMWR-258|实现 source upsert|`wiki/source_registry.py`|同 hash skip，变更写 event|
|LMWR-259|实现 source immutability guard|`wiki/source_registry.py`|raw source 变更不静默覆盖旧记录|
|LMWR-260|实现 chunk_id 派生规则|`wiki/chunk_registry.py`|参考 WikiLoom：source_hash + chunk_index|
|LMWR-261|实现 chunk upsert|`wiki/chunk_registry.py`|同 source reingest 不产生重复 chunk|
|LMWR-262|实现 page/span 元数据保存|`wiki/chunk_registry.py`|page、section、start/end 可保存|
|LMWR-263|实现 chunk text_hash|`wiki/chunk_registry.py`|chunk 内容变化可检测|
|LMWR-264|实现 chunk lookup by evidence_ref|`wiki/chunk_registry.py`|现有 evidence_ref 可回源|
|LMWR-265|迁移现有 local project chunks 到 registry 只读 adapter|`wiki/chunk_registry.py`|不改现有 chunk store，只提供 adapter|
|LMWR-266|测试 source/chunk registry roundtrip|`tests/`|SQLite 临时库插入/读取通过|
|LMWR-267|测试 source immutability 失败路径|`tests/`|同 source_id 不同 hash 进入 review/warning|
|LMWR-268|Wave 2 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 3：Markdown/frontmatter page store

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-269|设计 wiki markdown output layout|spec|`sources/papers/concepts/claims/synthesis/explorations/reports` 明确|
|LMWR-270|实现 safe slugify|`wiki/page_store.py`|中英文标题稳定转路径，非法字符处理|
|LMWR-271|实现 frontmatter parser|`wiki/frontmatter.py`|YAML/JSON frontmatter 解析失败有清晰错误|
|LMWR-272|实现 frontmatter renderer|`wiki/frontmatter.py`|字段排序稳定，日期格式 ISO|
|LMWR-273|实现 atomic markdown write|`wiki/page_store.py`|写入使用临时文件替换，失败不留半文件|
|LMWR-274|实现 markdown read_page|`wiki/page_store.py`|返回 frontmatter/body/path/hash|
|LMWR-275|实现 page_exists/list_pages|`wiki/page_store.py`|支持按 kind 过滤|
|LMWR-276|实现 generated section markers|`wiki/page_store.py`|保护人工编辑区，自动区可替换|
|LMWR-277|实现 hand-edit detection|`wiki/page_store.py`|参考 OLW，用户改动后进入 review/skip|
|LMWR-278|实现 index.md rebuild|`wiki/page_store.py`|按 kind/title/source 排序稳定|
|LMWR-279|实现 log.md append|`wiki/page_store.py`|所有 compile/query/save 写入 timeline|
|LMWR-280|测试 frontmatter roundtrip|`tests/`|多语言标题、list、dict 字段不丢|
|LMWR-281|测试 atomic write failure path|`tests/`|模拟异常不破坏旧页|
|LMWR-282|测试 hand-edit protection|`tests/`|人工区保留，自动区更新|
|LMWR-283|Wave 3 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 4：citation validator 与 finalize gate

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-284|定义 citation syntax|spec|支持 `[[sources/id#chunk]]`、`[chunk_id]`、page/span|
|LMWR-285|扩展 `CitationAuditor` 输入模型|`citation_auditor.py` 或 `wiki/citation_validator.py`|支持 evidence_refs + wiki claim|
|LMWR-286|实现 citation parser|`wiki/citation_validator.py`|能提取 source_id/chunk_id/page/span|
|LMWR-287|实现 claim sentence detector|`wiki/citation_validator.py`|参考 TheKnowledge，跳过代码块/header/list-only links|
|LMWR-288|实现 citation density metric|`wiki/citation_validator.py`|返回 cited_claims/total/ratio|
|LMWR-289|实现 quote exact match|`wiki/citation_validator.py`|quote 必须存在于 source/chunk text|
|LMWR-290|实现 quote fuzzy fallback metric|`wiki/citation_validator.py`|只作为 warning，不自动通过|
|LMWR-291|实现 source existence validation|`wiki/citation_validator.py`|引用不存在 source/chunk 时 fail|
|LMWR-292|实现 draft vs final validation mode|`wiki/citation_validator.py`|draft 可 warning，final 缺引用 fail|
|LMWR-293|实现 finalize command/service 草案|`wiki/review_queue.py`|finalize 前必须过 citation gate|
|LMWR-294|实现 validation report JSON|`wiki/citation_validator.py`|机器可读 errors/warnings/metrics|
|LMWR-295|测试无引用 claim 被拒绝|`tests/`|final mode fail|
|LMWR-296|测试 quote hallucination warning/fail|`tests/`|不存在 quote 被标记|
|LMWR-297|测试 draft finalize 成功路径|`tests/`|补齐 citation 后 status final|
|LMWR-298|Wave 4 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 5：RAG evidence_refs 到 wiki evidence 映射

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-299|设计 evidence_refs -> wiki citation mapping|spec|字段无损映射表|
|LMWR-300|实现 EvidenceReference coercer|`wiki/evidence_adapter.py`|旧 dict/TypedDict 均支持|
|LMWR-301|实现 evidence_ref source lookup|`wiki/evidence_adapter.py`|按 chunk_id/material_id 查 registry|
|LMWR-302|实现 evidence_ref normalized citation string|`wiki/evidence_adapter.py`|生成稳定 markdown citation|
|LMWR-303|实现 prompt evidence to wiki evidence conversion|`wiki/evidence_adapter.py`|`SOURCE_ID/MATERIAL/QUOTE/BODY` 可解析|
|LMWR-304|扩展 `RAGResult` 保存 wiki-ready evidence|`main_rag_workflow.py`|默认不改变输出，只增加可选字段或 helper|
|LMWR-305|实现 last_answer 到 synthesis draft adapter|`wiki/compiler.py`|可从 `last_answer.json` 生成 draft synthesis|
|LMWR-306|实现 missing evidence_ref fallback policy|`wiki/evidence_adapter.py`|缺 chunk_id 时进入 review，不伪造 final|
|LMWR-307|实现 source_labels 到 retrieval trail 保存|`wiki/evidence_adapter.py`|bm25/dense/graph/rrf/rerank 标签不丢|
|LMWR-308|实现 query_overlap_tokens 到 evidence note|`wiki/evidence_adapter.py`|方便 UI 解释证据命中|
|LMWR-309|测试 evidence_refs 无损转换|`tests/`|text/compressed/quote/page/rank/source_labels 都保留|
|LMWR-310|测试缺 chunk_id fallback|`tests/`|进入 draft/review|
|LMWR-311|测试 last_answer -> synthesis draft|`tests/`|生成 markdown + frontmatter|
|LMWR-312|测试 citation validator 接受 evidence adapter 输出|`tests/`|draft/final 两模式通过|
|LMWR-313|Wave 5 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 6：wiki 编译器最小闭环

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-314|设计 compile input contract|spec|输入 source/chunks/evidence_refs/config 清晰|
|LMWR-315|实现 compiler service skeleton|`wiki/compiler.py`|`compile_source`、`compile_project` 接口存在|
|LMWR-316|实现 dry-run compile plan|`wiki/compiler.py`|不写文件只返回将创建/更新页面|
|LMWR-317|实现 source summary page writer|`wiki/compiler.py`|从 source/chunks 写 `sources/*.md`|
|LMWR-318|实现 paper page draft writer|`wiki/compiler.py`|写 `papers/*.md`，不调用外部 LLM 的模板路径先通|
|LMWR-319|实现 concept page draft writer|`wiki/compiler.py`|从 focus/concepts/claims 初步聚合|
|LMWR-320|实现 claim page draft writer|`wiki/compiler.py`|每个 claim 有 evidence_refs|
|LMWR-321|实现 synthesis draft writer|`wiki/compiler.py`|从 query result 保存|
|LMWR-322|实现 compile skip by source_hash|`wiki/compiler.py`|无变更不重复写|
|LMWR-323|实现 compile transaction manifest|`wiki/compiler.py`|记录 touched pages / old hash / new hash|
|LMWR-324|实现 compile rollback metadata|`wiki/compiler.py`|为手动回滚提供 page manifest|
|LMWR-325|测试 dry-run 不写磁盘|`tests/`|临时目录无新增 wiki 文件|
|LMWR-326|测试 first compile 生成 index/log/pages|`tests/`|最小 source 生成完整目录|
|LMWR-327|测试 unchanged source skip|`tests/`|第二次 compile 无多余写入|
|LMWR-328|Wave 6 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 7：LLM 生成接入与 prompt 治理

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-329|设计 wiki compiler prompt templates|`prompt_templates/`、spec|summary/concept/claim/synthesis 模板分离|
|LMWR-330|对标 PaperQA RCS 和 OpenKB compile prompt|spec|记录取舍，不直接复制|
|LMWR-331|实现 provider-gated wiki LLM client wrapper|`wiki/compiler.py` 或 `model_call_gateway.py`|复用现有 env/test discipline|
|LMWR-332|实现 no-LLM deterministic stub mode|`wiki/compiler.py`|测试不需要外部 API|
|LMWR-333|实现 paper summary prompt|`prompt_templates/wiki_paper_summary.txt`|要求输出 JSON schema|
|LMWR-334|实现 concept extraction prompt|`prompt_templates/wiki_concept_extract.txt`|要求概念、aliases、evidence_refs|
|LMWR-335|实现 claim extraction prompt|`prompt_templates/wiki_claim_extract.txt`|要求每 claim 绑定证据|
|LMWR-336|实现 synthesis save prompt|`prompt_templates/wiki_synthesis.txt`|保存 query answer 时带 citation|
|LMWR-337|实现 LLM JSON repair/validation path|`wiki/compiler.py`|无效 JSON 进入 review，不写 final|
|LMWR-338|实现 token budget planner|`wiki/compiler.py`|长 source 按 chunk/evidence budget 裁剪|
|LMWR-339|实现 prompt audit trace|`workspace_artifacts/runtime_state/wiki/`|保存 masked prompt hash/model/cost，不泄露 key|
|LMWR-340|测试 stub mode compile|`tests/`|无 API key 也能跑|
|LMWR-341|测试 invalid LLM response 进入 review|`tests/`|不写 final|
|LMWR-342|测试 token budget guard|`tests/`|超长输入不爆 context|
|LMWR-343|Wave 7 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 8：wiki-aware retrieval 与 query pipeline

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-344|设计 wiki retrieval status manifest|`wiki/query.py`、spec|记录 index hash、page count、stale|
|LMWR-345|实现 wiki page FTS index|`wiki/query.py` 或 `wiki/index.py`|SQLite FTS 可搜 page/title/body|
|LMWR-346|实现 wiki page embedding adapter|`wiki/query.py`|复用 `ChunkVectorStore`，默认可关闭|
|LMWR-347|实现 wiki-first retrieval flag|`main_rag_workflow.py`|默认关闭，开启后先读 wiki|
|LMWR-348|实现 primary wiki page retrieval|`wiki/query.py`|top-k pages + scores|
|LMWR-349|实现 linked page expansion|`wiki/query.py`|参考 WikiLoom，primary -> outbound/inbound|
|LMWR-350|实现 raw RAG fallback bridge|`wiki/query.py`|wiki 无命中时回现有 RAG|
|LMWR-351|实现 wiki context pack renderer|`wiki/query.py`|token bounded, cited context|
|LMWR-352|实现 query debug trace|`wiki/query.py`|wiki_hits/raw_hits/fallback_reason|
|LMWR-353|实现 saved exploration page flow|`wiki/query.py`|query answer 可保存到 `explorations/`|
|LMWR-354|测试 wiki-first no-hit fallback|`tests/`|不影响现有 RAG answer|
|LMWR-355|测试 linked expansion ranking|`tests/`|被多个 primary 引用的 page 排名前|
|LMWR-356|测试 context pack token budget|`tests/`|超预算截断且记录 omitted|
|LMWR-357|测试 saved exploration citation|`tests/`|保存页过 citation validator|
|LMWR-358|Wave 8 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 9：graph 与 typed relations

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-359|设计 typed edge ontology|spec|参考 OmegaWiki/Coordination/Keppi|
|LMWR-360|实现 graph store JSON/SQLite schema|`wiki/graph.py`|nodes/edges/status/hash|
|LMWR-361|实现 wikilink parser|`wiki/graph.py`|解析 `[[kind/slug]]`|
|LMWR-362|实现 edge extraction from frontmatter|`wiki/graph.py`|sources/claims/concepts 关系入图|
|LMWR-363|实现 inbound/outbound backlinks|`wiki/graph.py`|页面可查双向链接|
|LMWR-364|实现 orphan detection|`wiki/doctor.py`|孤立页报告|
|LMWR-365|实现 duplicate concept candidates|`wiki/doctor.py`|slug/fuzzy/embedding 候选|
|LMWR-366|实现 blast radius|`wiki/graph.py`|参考 Keppi，按 edge weight BFS|
|LMWR-367|实现 claim contradiction edge stub|`wiki/graph.py`|先存人工/LLM 标记，不自动判 final|
|LMWR-368|实现 graph export JSON|`wiki/export.py`|前端/Obsidian 可用|
|LMWR-369|测试 backlinks|`tests/`|in/out 关系正确|
|LMWR-370|测试 orphan report|`tests/`|孤立 concept 被标记|
|LMWR-371|测试 duplicate candidates|`tests/`|近似 slug 被发现|
|LMWR-372|测试 blast radius|`tests/`|深度/阈值正确|
|LMWR-373|Wave 9 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 10：doctor、review queue、治理面

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-374|设计 wiki doctor report schema|spec|workspace/source/retrieval/citation/graph/review|
|LMWR-375|实现 workspace doctor|`wiki/doctor.py`|检查目录、db、config|
|LMWR-376|实现 source doctor|`wiki/doctor.py`|stale hash、missing source、orphan source|
|LMWR-377|实现 retrieval doctor|`wiki/doctor.py`|index stale/missing|
|LMWR-378|实现 citation doctor|`wiki/doctor.py`|uncited claims、broken citations|
|LMWR-379|实现 graph doctor|`wiki/doctor.py`|broken links、orphans、duplicates|
|LMWR-380|实现 review queue schema|`wiki/review_queue.py`|draft/fail/warning/manual_edit queue|
|LMWR-381|实现 review list/read|`wiki/review_queue.py`|可查看待处理项|
|LMWR-382|实现 review approve/reject|`wiki/review_queue.py`|approve finalize，reject 记录 reason|
|LMWR-383|实现 auto-repair safe subset|`wiki/doctor.py`|只允许 rebuild index/log，禁止改内容|
|LMWR-384|实现 doctor CLI/API service boundary|`routers/` or service|返回机器可读 report|
|LMWR-385|测试 doctor empty workspace|`tests/`|缺目录报 error|
|LMWR-386|测试 review approve/reject|`tests/`|状态转移正确|
|LMWR-387|测试 doctor repair safe subset|`tests/`|只重建索引，不改页面正文|
|LMWR-388|Wave 10 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 11：API contract 与 CLI/服务入口

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-389|设计 `/api/wiki/status` contract|`routers/wiki_router.py`|返回 status/paths/counts/stale|
|LMWR-390|设计 `/api/wiki/compile` contract|`routers/wiki_router.py`|支持 dry_run、source_id、project_id|
|LMWR-391|设计 `/api/wiki/query` contract|`routers/wiki_router.py`|支持 wiki_first、save、debug|
|LMWR-392|设计 `/api/wiki/pages` contract|`routers/wiki_router.py`|list/read/filter|
|LMWR-393|设计 `/api/wiki/review` contract|`routers/wiki_router.py`|list/approve/reject|
|LMWR-394|设计 `/api/wiki/doctor` contract|`routers/wiki_router.py`|report/repair=false|
|LMWR-395|实现 router skeleton default-off|`routers/wiki_router.py`|未开启时返回 disabled status|
|LMWR-396|接入 FastAPI app|`python_adapter_server.py`|OpenAPI 可见 wiki routes|
|LMWR-397|实现 CLI runbook wrapper|`run_literature_assistant.py` 或 new tool|支持 status/doctor dry-run|
|LMWR-398|补充 OpenAPI schema snapshot|`workspace_artifacts` or tests|schema 生成成功|
|LMWR-399|测试 status disabled|`tests/`|默认关闭不破坏服务|
|LMWR-400|测试 compile dry-run API|`tests/`|不写磁盘|
|LMWR-401|测试 doctor API|`tests/`|返回机器可读 report|
|LMWR-402|测试 review API contract|`tests/`|approve/reject 状态正确|
|LMWR-403|Wave 11 compileall/pytest 收口|verification|focused tests + OpenAPI pass|

## Wave 12：前端 Wiki 工作台最小产品面

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-404|设计 Wiki 面板信息架构|`frontend/src/`、spec|Status/Pages/Review/Graph/Doctor 分区|
|LMWR-405|新增 wiki API client types|`frontend/src/lib`|TypeScript strict，无 `any`|
|LMWR-406|新增 WikiStatusCard|`frontend/src/components`|显示 enabled/stale/page counts|
|LMWR-407|新增 WikiCompileDryRunPanel|frontend|展示将写入页面，不直接执行写入|
|LMWR-408|新增 WikiPageList|frontend|按 kind/status/filter|
|LMWR-409|新增 WikiPagePreview|frontend|frontmatter + body preview|
|LMWR-410|新增 ReviewQueuePanel|frontend|approve/reject UI，带 reason|
|LMWR-411|新增 DoctorReportPanel|frontend|errors/warnings/actions|
|LMWR-412|新增 CitationWarnings view|frontend|uncited/broken quote 可读|
|LMWR-413|新增 GraphJson debug view|frontend|先 JSON/列表，后续再图可视化|
|LMWR-414|接入 existing Evidence UI|frontend|evidence_refs 可跳转 wiki citation|
|LMWR-415|测试 API client parsing|frontend tests|unknown payload 防守|
|LMWR-416|测试 ReviewQueuePanel|frontend tests|approve/reject 状态|
|LMWR-417|测试 DoctorReportPanel|frontend tests|error/warning/action 渲染|
|LMWR-418|Wave 12 frontend test/build 收口|verification|Vitest focused + build pass|

## Wave 13：Zotero/EndNote/Obsidian 只读 connector 设计与最小接入

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-419|设计 connector interface|spec / `wiki/connectors/`|list_sources/read_source/extract_metadata|
|LMWR-420|对标 Knowledge-Base-Gateway source model|spec|记录 Zotero/EndNote/Obsidian 可读字段|
|LMWR-421|实现 filesystem markdown connector|`wiki/connectors/markdown.py`|只读扫描 Obsidian-like notes|
|LMWR-422|实现 PDF folder connector skeleton|`wiki/connectors/pdf_folder.py`|只读列出 PDF metadata/path|
|LMWR-423|实现 Zotero connector spec only|spec|不读用户真实库，先定义接口|
|LMWR-424|实现 EndNote connector spec only|spec|不读用户真实库，先定义接口|
|LMWR-425|实现 connector permission guard|`wiki/connectors/base.py`|外部路径必须显式配置|
|LMWR-426|实现 connector source_id namespace|`wiki/connectors/base.py`|`zotero:`, `endnote:`, `obsidian:`|
|LMWR-427|实现 connector dry-run scan report|`wiki/connectors/base.py`|不写 registry，只返回 counts|
|LMWR-428|实现 connector errors sanitization|`wiki/connectors/base.py`|不泄露本地隐私路径到公开日志|
|LMWR-429|测试 markdown connector|`tests/`|临时目录 notes 扫描正确|
|LMWR-430|测试 external path guard|`tests/`|未配置路径拒绝|
|LMWR-431|测试 source_id namespace|`tests/`|不同 connector 不冲突|
|LMWR-432|测试 dry-run no writes|`tests/`|registry/page store 无变化|
|LMWR-433|Wave 13 compileall/pytest 收口|verification|focused tests pass|

## Wave 14：评测、回归、质量门禁

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-434|设计 wiki-aware retrieval eval manifest|`tools/eval/` spec|不改现有 qrels，只新增独立 manifest|
|LMWR-435|实现 wiki vs raw RAG zero-cost comparison|`tools/eval/`|比较 top-k overlap/empty/fallback|
|LMWR-436|实现 citation audit eval report|`tools/eval/`|统计 citation pass/warn/fail|
|LMWR-437|实现 compile quality smoke dataset|`workspace_tests/fixtures`|小型论文/notes fixture|
|LMWR-438|实现 duplicate/graph doctor fixtures|fixtures|覆盖 broken link/orphan/duplicate|
|LMWR-439|实现 cost guard for wiki LLM compile|`wiki/compiler.py`|预算超限拒绝或 dry-run|
|LMWR-440|实现 no-secret trace check|tests|trace 不包含 API key|
|LMWR-441|实现 performance baseline|`tools/eval/`|compile/query 时间记录|
|LMWR-442|实现 rollback restore rehearsal runbook|runbook|只列命令，不自动恢复|
|LMWR-443|实现 CI-friendly test subset marker|tests|wiki tests 可 focused 跑|
|LMWR-444|测试 wiki eval manifest dry-run|tests|不调用模型|
|LMWR-445|测试 citation audit metrics|tests|pass/warn/fail 统计正确|
|LMWR-446|测试 no-secret trace|tests|密钥 mask|
|LMWR-447|跑 workspace verification|verification|system_verification JSON pass 或记录 blocker|
|LMWR-448|Wave 14 compileall/pytest 收口|verification|focused + collect-only pass|

## Wave 15：迁移、发布门禁、长期维护

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-449|编写 migration plan：evidence_refs 到 wiki registry|`docs/plans/specs/`|说明现有数据如何只读导入|
|LMWR-450|编写 migration dry-run command|runbook|不写入时输出 would-import|
|LMWR-451|编写 backup/export plan|runbook|wiki db/pages/graph 一键打包|
|LMWR-452|编写 wiki cleanup policy|spec|stale/deprecated/archived 处理|
|LMWR-453|编写 human edit policy|spec|自动区/人工区/冲突处理|
|LMWR-454|编写 multi-agent coordination policy|spec|参考 llm-wiki-coordination，不强制引入|
|LMWR-455|编写 wiki MCP/tool exposure plan|spec|后续给 Codex/Claude 使用，先不实现|
|LMWR-456|编写 frontend release checklist|runbook|build/test/e2e/manual smoke|
|LMWR-457|编写 backend release checklist|runbook|compileall/pytest/OpenAPI/system verification|
|LMWR-458|编写 privacy/security checklist|runbook|外部路径、secret、source text、export|
|LMWR-459|编写 rollback checklist|runbook|恢复 checkpoint + 恢复 wiki db/pages|
|LMWR-460|编写 user-facing usage guide draft|docs|说明 wiki-first/query-save/review/doctor|
|LMWR-461|更新 master plan 状态引用|`docs/plans/active/2026-04-27...`|只追加链接，不复制 240 项|
|LMWR-462|做一次端到端 dry-run 验收|verification|source -> compile dry-run -> doctor -> query-save draft|
|LMWR-463|最终 gate：独立复核和证据包|docs/squad|证据路径、测试结果、残留风险写清|

## 推荐优先级

### 图片决策执行包（2026-05-03 固化）

- 决策 P-IMG-01（参考源约束）
    - 参数与模型策略优先参考：`github/` 内 RAG 参考库 + `C:\Users\xiao\Downloads\llmwiki借鉴库` + 官方上游文档。
    - 仅“借鉴设计与参数语义”，不复制外部实现，不改外部仓库。
- 决策 P-IMG-02（执行顺序）
    - 当前批次严格按图片给定顺序推进：`B -> C -> D -> A`（保持原标签命名，不在本计划内重命名）。
- 决策 P-IMG-03（失败处置）
    - 先记录失败（含测试名/报错/归因/证据路径），再进入修复。
    - 修复策略：先简单项（低风险、低耦合、可快速回归），后复杂项（跨模块、需架构变更或新增 gate）。
    - 每个修复切片必须带 focused 回归结果，不允许“只改不验”。

### P0：必须先做

- Wave 0：治理和回档模板。
- Wave 1：数据模型。
- Wave 2：source/chunk registry。
- Wave 4：citation validator。
- Wave 5：evidence_refs 映射。
- Wave 6：compiler dry-run 和最小 markdown 写入。

### P1：有 P0 后再做

- Wave 8：wiki-aware retrieval。
- Wave 10：doctor/review queue。
- Wave 11：API contract。
- Wave 14：评测和质量门禁。

### P2：产品化与扩展

- Wave 9：graph。
- Wave 12：前端 Wiki 工作台。
- Wave 13：Zotero/EndNote/Obsidian 只读 connector。
- Wave 15：迁移、MCP、长期维护。

## 最小可交付闭环

最小闭环不需要 240 项全部完成。第一个可用版本建议只做到：

1. 稳定 source/chunk registry。
2. 从现有 `RAGResult.evidence_refs` 生成 `synthesis` draft。
3. citation validator 能拒绝无引用 final。
4. page store 能写 `workspace_artifacts/generated/wiki/`。
5. doctor 能报告 broken citation / stale index。
6. API 能返回 disabled/status/dry-run。

对应任务范围：`LMWR-224` 到 `LMWR-328`，再加 `LMWR-374` 到 `LMWR-388` 的最小 doctor。

## Copilot/Agent 单任务指令模板

```text
任务：执行 LMWR-<ID>：<任务名>。

必须先做：
1. 创建回档：
   py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-<ID>-<slug>"
2. 搜索/读取成熟方案：
   - 优先读本文列出的本地参考库对应文件。
   - 如涉及架构或库选择，再搜索官方/上游项目文档。
3. 只改本任务范围内文件，不碰 `github/` 和下载参考库。
4. 实现后运行 focused tests 和 compileall。
5. 把执行证据写回 docs/plans 或 .squad/decisions/inbox。

验收：<复制本任务验收列>。
```

## 回滚说明

不得自动恢复回档。只有用户明确要求“回滚/恢复/撤销本次改动”时，才执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
