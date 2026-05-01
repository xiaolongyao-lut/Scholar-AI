# -*- coding: utf-8 -*-
"""
Focus Registry - 关注点规范化、去重、别名管理、文献映射

Role: 负责关注点的核心数据管理
  - 规范化和去重（跨文献、文献内、提及级）
  - 别名归并和同义词处理
  - 文献到关注点的映射维护
  - 提及的出现位置记录

输入：raw focus points from LLM (可能有重复、大小写混乱、多种语言变体)
输出：规范化的 focus_points.json（含 focus_registry、doc_map、mentions）

设计参考：
  - Microsoft Dynamics 365 数据统一 (deduplication + normalization)
  - ASIM Aliases (canonical references + aliases)
  - Unicode 规范化标准 (NFKC)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# 预编译正则表达式（性能优化）
_RE_REMOVE_SYMBOLS = re.compile(r'[^\w\u4e00-\u9fff\s]')
_RE_NORMALIZE_SPACE = re.compile(r'\s+')
_RE_SLUG_CLEAN = re.compile(r'[^\w]')

# 配置日志
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class FocusRecord:
    """规范化的关注点记录"""
    id: str
    canonical_name: str
    aliases: List[str] = field(default_factory=list)
    category: str = ""
    description: str = ""
    source_docs: List[str] = field(default_factory=list)
    mention_count: int = 0
    created_at: str = ""
    last_updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DocMapEntry:
    """文献级关注点映射"""
    title: str
    source_path: str
    focus_ids: List[str] = field(default_factory=list)
    focus_names: List[str] = field(default_factory=list)
    mention_count: Dict[str, int] = field(default_factory=dict)
    processed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MentionRecord:
    """关注点的出现记录"""
    mention_id: str
    focus_id: str
    doc_id: str
    doc_title: str
    section: str = ""
    page: int = 0
    paragraph: int = 0
    snippet: str = ""
    source_type: str = "text"
    evidence_hash: str = ""
    extracted_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Focus Registry 核心类
# ============================================================================

class FocusRegistry:
    """
    关注点规范化注册表

    核心职责：
    1. 文本规范化（Unicode、清理、大小写）
    2. 别名识别和同义词归并
    3. 去重（全局、文献级、提及级）
    4. 文献到关注点的映射维护
    5. 提及出现位置的记录
    """

    def __init__(
        self,
        alias_map: Optional[Dict[str, str]] = None,
        category_map: Optional[Dict[str, str]] = None,
        safe_root: Optional[str] = None
    ):
        """
        初始化注册表

        Args:
            alias_map: 手工别名表 {text → canonical_name}
            category_map: 关注点分类表 {canonical_name → category}
            safe_root: 安全根目录（save() 时强制校验路径必须在该目录下），默认为当前工作目录
        """
        # 规范化别名表的键：确保别名匹配时的一致性
        self.alias_map = self._normalize_dict_keys(alias_map or {})
        self.category_map = category_map or {}

        # 安全根目录：默认为当前工作目录，防止目录穿越
        self.safe_root = Path(safe_root or ".").resolve()

        # 核心数据结构
        self.focus_records: Dict[str, FocusRecord] = {}  # {canonical_name → FocusRecord}
        self.doc_map: Dict[str, DocMapEntry] = {}  # {doc_id → DocMapEntry}
        self.mentions: List[MentionRecord] = []

        # 缓存：规范化形式 → canonical_name（用于快速查重）
        self._normalized_to_canonical: Dict[str, str] = {}
        # focus_id → FocusRecord（用于 O(1) 查询）
        self._id_to_record: Dict[str, FocusRecord] = {}
        # 提及去重索引：(doc_id, focus_id, evidence_hash) → mention_id（优化查找）
        self._mention_dedupe_map: Dict[Tuple[str, str, str], str] = {}

        # 元数据
        self.version = "v2"
        self.created_at = datetime.now().isoformat()
        self.last_updated_at = datetime.now().isoformat()

    # ========================================
    # 工具方法
    # ========================================

    @staticmethod
    def _normalize_dict_keys(input_dict: Dict[str, str]) -> Dict[str, str]:
        """
        规范化字典的键（用于 alias_map 和 category_map）

        确保所有键都被规范化，使得后续查询时能正确匹配。

        Args:
            input_dict: 输入字典

        Returns:
            键被规范化后的字典

        Note:
            如果规范化过程中发生异常（如文本过短/过长），该条目会被跳过并记录日志
        """
        normalized = {}
        for key, value in input_dict.items():
            try:
                normalized_key = FocusRegistry.normalize_focus_text(key)
                normalized[normalized_key] = value
            except ValueError as e:
                logger.warning(f"Skipping invalid alias key '{key}': {e}")
        return normalized

    # ========================================
    # 规范化和去重方法
    # ========================================

    @staticmethod
    def normalize_focus_text(text: str) -> str:
        """
        规范化关注点文本

        步骤：
        1. Unicode NFKC 规范化（统一字符形式）
        2. 清理符号和多余空格
        3. 转换为小写

        Args:
            text: 原始文本

        Returns:
            规范化后的小写文本

        Raises:
            ValueError: 输入无效时
        """
        if not isinstance(text, str) or len(text.strip()) == 0:
            raise ValueError(f"Invalid focus text: '{text}' (must be non-empty string)")

        # Unicode 规范化
        normalized = unicodedata.normalize('NFKC', text)

        # 移除符号（保留中文、英文、数字、空格）
        normalized = _RE_REMOVE_SYMBOLS.sub('', normalized)

        # 规范化空格（多个连续空格 → 单个）
        normalized = _RE_NORMALIZE_SPACE.sub(' ', normalized)

        # 去首尾空格
        normalized = normalized.strip()

        # 转为小写
        normalized = normalized.lower()

        if len(normalized) > 100:
            raise ValueError(f"Focus text too long (max 100 chars): '{text}'")

        if len(normalized) < 2:
            raise ValueError(f"Focus text too short (min 2 chars): '{text}'")

        return normalized

    def canonicalize_focus(
        self,
        text: str,
        prefer_chinese: bool = True,
        _visited: Optional[Set[str]] = None
    ) -> str:
        """
        确定规范化文本应该映射到的标准名称 (canonical_name)

        优先级（从低到高） :
        1. 规范化后精确匹配已有的 canonical_name
        2. 查询手工别名表 (alias_map)
        3. 返回原始 text（作为新的 canonical_name）

        Args:
            text: 原始文本
            prefer_chinese: 在中英文变体中优先选择中文

        Returns:
            该文本应该归属的 canonical_name

        Raises:
            ValueError: 检测到循环别名映射时
        """
        normalized = self.normalize_focus_text(text)

        if _visited is None:
            _visited = set()
        if normalized in _visited:
            raise ValueError(f"Circular alias mapping detected: {normalized}")
        _visited.add(normalized)

        # 检查缓存：是否已映射过
        if normalized in self._normalized_to_canonical:
            return self._normalized_to_canonical[normalized]

        # 检查别名表
        if normalized in self.alias_map:
            target = self.alias_map[normalized]
            canonical = self.canonicalize_focus(target, prefer_chinese=prefer_chinese, _visited=_visited)
            self._normalized_to_canonical[normalized] = canonical
            return canonical

        # 都未找到，返回原始 text 作为新的 canonical_name
        self._normalized_to_canonical[normalized] = text
        return text

    def build_focus_id(self, canonical_name: str) -> str:
        """
        为 canonical_name 生成唯一的 focus_id

        规则：
        - focus_<hash of normalized canonical_name>
        - 例：focus_热输入控制 → focus_heat_input_abc123

        Args:
            canonical_name: 规范化的关注点名称

        Returns:
            格式化的 focus_id
        """
        normalized = self.normalize_focus_text(canonical_name)
        # 使用规范化形式的 hash 作为 id 的一部分，保证同义词得到相同 id
        hash_suffix = hashlib.md5(normalized.encode()).hexdigest()[:6]
        # 取 canonical_name 的拼音简写或英文缩写（简化版）
        slug = _RE_SLUG_CLEAN.sub('', normalized)[:20]
        return f"focus_{slug}_{hash_suffix}"

    def build_mention_id(self, doc_id: str, focus_id: str, snippet: str) -> str:
        """
        为单条提及生成唯一 mention_id

        规则：
        - mention_<doc_id>_<focus_id>_<snippet_hash>

        Args:
            doc_id: 文献 ID
            focus_id: 关注点 ID
            snippet: 出现的文本片段

        Returns:
            mention_id
        """
        snippet_hash = hashlib.md5(snippet.encode()).hexdigest()[:8]
        return f"mention_{doc_id}_{focus_id}_{snippet_hash}"

    def _compute_evidence_hash(self, snippet: str) -> str:
        """计算证据的 SHA256 hash（用于提及去重）"""
        return hashlib.sha256(snippet.encode()).hexdigest()

    # ========================================
    # 核心写入操作
    # ========================================

    def upsert_focus(
        self,
        text: str,
        canonical_name: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        category: str = "",
        description: str = ""
    ) -> Tuple[str, bool]:
        """
        插入或更新一个关注点

        Args:
            text: 原始提取的文本
            canonical_name: 指定的标准名称（如果 None 则自动确定）
            aliases: 额外的别名列表
            category: 关注点分类
            description: 描述

        Returns:
            (focus_id, is_new) - focus_id 和 是否为新记录

        Raises:
            ValueError: 输入无效或存在冲突时
        """
        # 确定 canonical_name
        if canonical_name is None:
            canonical_name = self.canonicalize_focus(text)

        # 验证
        if not canonical_name or len(canonical_name.strip()) == 0:
            raise ValueError(f"Invalid canonical_name: '{canonical_name}'")

        # 规范化
        normalized_canonical = self.normalize_focus_text(canonical_name)

        now = datetime.now().isoformat()

        # 使用缓存进行 O(1) 查询：从规范化形式查找已存在的 canonical_name
        existing_canonical_name = self._normalized_to_canonical.get(normalized_canonical)
        existing_focus = None
        if existing_canonical_name and existing_canonical_name in self.focus_records:
            existing_focus = self.focus_records[existing_canonical_name]
            canonical_name = existing_canonical_name

        if existing_focus:
            # 更新现有记录
            is_new = False
            focus_id = existing_focus.id

            # 合并别名
            if aliases:
                existing_focus.aliases.extend(aliases)
                existing_focus.aliases = list(set(existing_focus.aliases))

            existing_focus.last_updated_at = now

            # 更新分类（如果未设置）
            if not existing_focus.category and category:
                existing_focus.category = category

            logger.info(f"? Updated focus: {canonical_name} (id={focus_id})")

        else:
            # 创建新记录
            is_new = True
            focus_id = self.build_focus_id(canonical_name)

            record = FocusRecord(
                id=focus_id,
                canonical_name=canonical_name,
                aliases=aliases or [],
                category=category or self.category_map.get(canonical_name, ""),
                description=description,
                source_docs=[],
                mention_count=0,
                created_at=now,
                last_updated_at=now
            )

            self.focus_records[canonical_name] = record
            logger.info(f"? Created new focus: {canonical_name} (id={focus_id})")

        # 统一刷新索引/缓存（无论新建或更新）
        record_for_index = existing_focus if existing_focus else self.focus_records[canonical_name]
        self._id_to_record[record_for_index.id] = record_for_index
        self._normalized_to_canonical[normalized_canonical] = record_for_index.canonical_name

        return focus_id, is_new

    def add_mention(
        self,
        focus_id: str,
        doc_id: str,
        doc_title: str,
        snippet: str,
        section: str = "",
        page: int = 0,
        paragraph: int = 0,
        source_type: str = "text"
    ) -> str:
        """
        为一个关注点添加出现记录

        Args:
            focus_id: 关注点 ID
            doc_id: 文献 ID
            doc_title: 文献标题
            snippet: 包含关注点的文本片段
            section: 所在章节（如 results、discussion）
            page: 页码
            paragraph: 段落号
            source_type: 来源类型（text、figure、table）

        Returns:
            mention_id

        Raises:
            ValueError: focus_id 不存在时
        """
        # 验证 focus_id 存在：优先使用索引，失败则遍历并更新索引
        focus_record = self._id_to_record.get(focus_id)
        if not focus_record:
            # 索引未命中，进行线性搜索并更新索引以优化后续查询
            for record in self.focus_records.values():
                if record.id == focus_id:
                    focus_record = record
                    self._id_to_record[focus_id] = record  # 更新索引
                    logger.debug(f"Updated _id_to_record cache for focus_id={focus_id}")
                    break

        if not focus_record:
            raise ValueError(f"Focus ID not found: {focus_id}")

        # 先对 snippet 截断，保证 ID、哈希与存储数据一致
        snippet_truncated = snippet[:200]

        # 生成 mention_id 和计算证据 hash（基于截断后的内容）
        mention_id = self.build_mention_id(doc_id, focus_id, snippet_truncated)
        evidence_hash = self._compute_evidence_hash(snippet_truncated)
        dedupe_key = (doc_id, focus_id, evidence_hash)

        # 检查是否已存在（O(1) 查找）
        if dedupe_key in self._mention_dedupe_map:
            existing_mention_id = self._mention_dedupe_map[dedupe_key]
            logger.debug(f"Mention already exists (skipped): {existing_mention_id}")
            return existing_mention_id

        now = datetime.now().isoformat()

        # 创建新 mention
        mention = MentionRecord(
            mention_id=mention_id,
            focus_id=focus_id,
            doc_id=doc_id,
            doc_title=doc_title,
            section=section,
            page=page,
            paragraph=paragraph,
            snippet=snippet_truncated,
            source_type=source_type,
            evidence_hash=evidence_hash,
            extracted_at=now
        )

        self.mentions.append(mention)
        self._mention_dedupe_map[dedupe_key] = mention_id

        # 更新 focus_record 的统计
        focus_record.mention_count += 1
        focus_record.last_updated_at = now

        # 如果这个文献还不在 source_docs 里，添加它
        if doc_id not in focus_record.source_docs:
            focus_record.source_docs.append(doc_id)

        return mention_id

    def update_doc_map(self, doc_id: str, doc_title: str, source_path: str = ""):
        """
        更新或创建文献级映射

        Args:
            doc_id: 文献 ID（通常是文件名去后缀）
            doc_title: 文献标题
            source_path: 原始文件路径
        """
        now = datetime.now().isoformat()
        if doc_id not in self.doc_map:
            self.doc_map[doc_id] = DocMapEntry(
                title=doc_title,
                source_path=source_path,
                processed_at=now
            )

        # 优化：使用已维护的 _id_to_record 索引，避免重建字典
        # 更新该文献涉及的 focus_ids 和 focus_names
        focus_ids_for_doc: Set[str] = set()
        focus_names_for_doc: Set[str] = set()
        mention_counts: Dict[str, int] = {}

        for mention in self.mentions:
            if mention.doc_id == doc_id:
                focus_ids_for_doc.add(mention.focus_id)
                # 直接从 _id_to_record 查询，O(1)
                record = self._id_to_record.get(mention.focus_id)
                if record:
                    focus_names_for_doc.add(record.canonical_name)
                mention_counts[mention.focus_id] = mention_counts.get(mention.focus_id, 0) + 1

        entry = self.doc_map[doc_id]
        entry.focus_ids = sorted(list(focus_ids_for_doc))
        entry.focus_names = sorted(list(focus_names_for_doc))
        entry.mention_count = mention_counts
        entry.processed_at = now

    # ========================================
    # 导出和序列化
    # ========================================

    def to_dict(self) -> dict:
        """
        将 registry 转换为字典（用于 JSON 序列化）
        """
        # 生成 points 字段（用于向后兼容）
        points = sorted([r.canonical_name for r in self.focus_records.values()])

        return {
            "version": self.version,
            "updated_at": self.last_updated_at,

            # 兼容字段
            "points": points,

            # 新字段
            "focus_registry": [r.to_dict() for r in self.focus_records.values()],
            "doc_map": {doc_id: entry.to_dict() for doc_id, entry in self.doc_map.items()},
            "mentions": [m.to_dict() for m in self.mentions],

            # 配置和映射表（用于 load() 恢复）
            "alias_map": self.alias_map,
            "category_map": self.category_map,

            # 元数据
            "metadata": {
                "total_focus_points": len(self.focus_records),
                "total_documents": len(self.doc_map),
                "total_mentions": len(self.mentions),
                "processing_stats": {
                    "created_at": self.created_at,
                    "last_updated_at": self.last_updated_at
                }
            }
        }

    def save(self, output_path: str) -> None:
        """
        保存 registry 到 JSON 文件

        Args:
            output_path: 输出文件路径（必须在 safe_root 目录下，防止目录穿越）

        Raises:
            ValueError: 路径不在 safe_root 下时
        """
        output_file = Path(output_path).resolve()

        # 🔒 强制路径安全校验：确保输出路径必须在 safe_root 下
        try:
            output_file.relative_to(self.safe_root)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: '{output_path}' is not under safe root '{self.safe_root}'. "
                f"All save operations must write to '{self.safe_root}' or subdirectories."
            )

        output_file.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Focus registry saved: {output_path}")
        logger.info(f"  - Focus points: {len(self.focus_records)}")
        logger.info(f"  - Documents: {len(self.doc_map)}")
        logger.info(f"  - Mentions: {len(self.mentions)}")

    @classmethod
    def load(cls, path: str, safe_root: Optional[str] = None) -> FocusRegistry:
        """
        从 JSON 文件加载 registry

        Args:
            path: JSON 文件路径
            safe_root: 安全根目录（可选，用于加载后的 save() 校验）

        Returns:
            FocusRegistry 实例

        Raises:
            FileNotFoundError: 文件不存在时
            json.JSONDecodeError: JSON 格式无效时
            ValueError: 数据验证失败时
        """
        # 解析并规范化路径
        load_file = Path(path).resolve()

        try:
            with open(load_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError as e:
            logger.error(f"Focus registry file not found: {path}")
            raise FileNotFoundError(f"Cannot load registry: file does not exist '{path}'") from e
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format in file: {path}")
            raise json.JSONDecodeError(
                f"Cannot load registry: invalid JSON in file '{path}'",
                e.doc,
                e.pos
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error reading file '{path}': {e}")
            raise

        # 恢复 alias_map 和 category_map（若存在）
        alias_map = data.get("alias_map", {})
        category_map = data.get("category_map", {})

        try:
            registry = cls(alias_map=alias_map, category_map=category_map, safe_root=safe_root)
        except Exception as e:
            logger.error(f"Failed to initialize registry: {e}")
            raise ValueError(f"Cannot initialize registry from data: {e}") from e

        focus_fields = {f.name for f in fields(FocusRecord)}
        doc_fields = {f.name for f in fields(DocMapEntry)}
        mention_fields = {f.name for f in fields(MentionRecord)}

        # 加载 focus_registry
        if "focus_registry" in data:
            for record_dict in data["focus_registry"]:
                safe_record = {k: v for k, v in record_dict.items() if k in focus_fields}
                record = FocusRecord(**safe_record)
                registry.focus_records[record.canonical_name] = record
                registry._id_to_record[record.id] = record
                normalized = cls.normalize_focus_text(record.canonical_name)
                registry._normalized_to_canonical[normalized] = record.canonical_name

        # 重建 _normalized_to_canonical 缓存，包括所有别名映射
        # 这确保加载后的 canonicalize_focus() 和原始状态一致
        for alias_text, canonical in alias_map.items():
            registry._normalized_to_canonical[alias_text] = canonical

        # 加载 doc_map
        if "doc_map" in data:
            for doc_id, entry_dict in data["doc_map"].items():
                safe_entry = {k: v for k, v in entry_dict.items() if k in doc_fields}
                entry = DocMapEntry(**safe_entry)
                registry.doc_map[doc_id] = entry

        # 加载 mentions
        if "mentions" in data:
            for mention_dict in data["mentions"]:
                safe_mention = {k: v for k, v in mention_dict.items() if k in mention_fields}
                mention = MentionRecord(**safe_mention)
                registry.mentions.append(mention)
                dedupe_key = (mention.doc_id, mention.focus_id, mention.evidence_hash)
                registry._mention_dedupe_map[dedupe_key] = mention.mention_id

        # 恢复元数据（确保一致性）
        if "metadata" in data and "processing_stats" in data["metadata"]:
            stats = data["metadata"]["processing_stats"]
            registry.created_at = stats.get("created_at", registry.created_at)
            registry.last_updated_at = stats.get("last_updated_at", registry.last_updated_at)
        if "version" in data:
            registry.version = data["version"]

        logger.info(f"📥 Focus registry loaded: {path}")
        logger.info(f"  - Focus points: {len(registry.focus_records)}")
        logger.info(f"  - Documents: {len(registry.doc_map)}")
        logger.info(f"  - Mentions: {len(registry.mentions)}")
        logger.info(f"  - Alias mappings: {len(registry.alias_map)}")

        return registry

    # ========================================
    # 查询和统计
    # ========================================

    def get_focus_by_id(self, focus_id: str) -> Optional[FocusRecord]:
        """根据 focus_id 查询关注点"""
        record = self._id_to_record.get(focus_id)
        if record:
            return record
        for record in self.focus_records.values():
            if record.id == focus_id:
                self._id_to_record[focus_id] = record
                return record
        return None

    def get_focus_by_name(self, canonical_name: str) -> Optional[FocusRecord]:
        """根据 canonical_name 查询关注点"""
        return self.focus_records.get(canonical_name)

    def get_mentions_for_focus(self, focus_id: str) -> List[MentionRecord]:
        """获取某个关注点的所有提及"""
        return [m for m in self.mentions if m.focus_id == focus_id]

    def get_mentions_for_doc(self, doc_id: str) -> List[MentionRecord]:
        """获取某个文献中的所有提及"""
        return [m for m in self.mentions if m.doc_id == doc_id]

    def get_statistics(self) -> dict:
        """获取统计信息"""
        return {
            "total_focus_points": len(self.focus_records),
            "total_documents": len(self.doc_map),
            "total_mentions": len(self.mentions),
            "avg_mentions_per_focus": round(len(self.mentions) / len(self.focus_records), 2) if self.focus_records else 0,
            "avg_focuses_per_doc": round(sum(len(entry.focus_ids) for entry in self.doc_map.values()) / len(self.doc_map), 2) if self.doc_map else 0
        }


# ============================================================================
# 测试和演示
# ============================================================================

def demo():
    """演示 FocusRegistry 的基本功能"""

    print("=" * 60)
    print("Focus Registry Demo")
    print("=" * 60)

    # 创建别名表
    alias_map = {
        "热输入": "热输入控制",
        "heat input": "热输入控制",
        "焊接热输入": "热输入控制"
    }

    # 初始化 registry
    registry = FocusRegistry(alias_map=alias_map)

    # 示例 1: 提取和规范化
    print("\n[1] Normalization Demo")
    raw_texts = [
        "热输入",
        "Heat Input",
        "焊接热输入",
        "  多个  空格  ",
        "晶粒细化"
    ]

    for text in raw_texts:
        try:
            normalized = FocusRegistry.normalize_focus_text(text)
            canonical = registry.canonicalize_focus(text)
            print(f"  '{text}' → normalized='{normalized}' → canonical='{canonical}'")
        except ValueError as e:
            print(f"  '{text}' → ERROR: {e}")

    # 示例 2: 插入关注点
    print("\n[2] Upsert Demo")
    focus_id_1, is_new_1 = registry.upsert_focus(
        "热输入",
        canonical_name="热输入控制",
        category="工艺参数",
        description="激光焊接过程中的输入热量"
    )
    print(f"  Created focus: {focus_id_1} (new={is_new_1})")

    focus_id_1_dup, is_new_1_dup = registry.upsert_focus("heat input")
    print(f"  Duplicate insert: {focus_id_1_dup} (new={is_new_1_dup})")

    focus_id_2, is_new_2 = registry.upsert_focus("晶粒细化", category="组织控制")
    print(f"  Created focus: {focus_id_2} (new={is_new_2})")

    # 示例 3: 添加提及
    print("\n[3] Mention Demo")
    mention_id_1 = registry.add_mention(
        focus_id=focus_id_1,
        doc_id="paper_a",
        doc_title="Laser Welding Study",
        snippet="With increase in the heat input, the HAZ width increases",
        section="results",
        page=5
    )
    print(f"  Added mention: {mention_id_1}")

    mention_id_2 = registry.add_mention(
        focus_id=focus_id_1,
        doc_id="paper_a",
        doc_title="Laser Welding Study",
        snippet="The thermal input directly affects cooling rate",
        section="discussion",
        page=7
    )
    print(f"  Added mention: {mention_id_2}")

    # 示例 4: 更新文献映射
    print("\n[4] Doc Map Demo")
    registry.update_doc_map("paper_a", "Laser Welding Study", "/path/to/paper_a.pdf")
    print(f"  Updated doc_map for paper_a")

    # 示例 5: 统计
    print("\n[5] Statistics")
    stats = registry.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 示例 6: 序列化
    print("\n[6] Serialization")
    registry_dict = registry.to_dict()
    print(f"  Generated dict with keys: {list(registry_dict.keys())}")
    print(f"  points: {registry_dict['points']}")
    print(f"  Total focus_registry entries: {len(registry_dict['focus_registry'])}")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    demo()
