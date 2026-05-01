# 技术规范 #2: ClaimCache (声明缓存系统)

**版本**: v1.0  
**状态**: Ready for Implementation  
**优先级**: 🟠 本周末  
**目标模块**: `layers/claim_cache.py`  
**集成点**: `layers/p2_claim_extractor.py`

---

## 1. 模块设计

### 1.1 核心类

```python
class ClaimCache:
    """
    声明缓存管理器。
    
    目的:
    - 缓存已提取的claims结构化数据
    - 避免重复处理相同文献的重复LLM调用
    - 支持缓存失效和更新
    
    存储介质: SQLite (本地, 无依赖)
    
    性能指标:
    - 缓存命中: 直接返回 (<5ms)
    - 缓存写入: 异步写入 (<10ms)
    - 缓存大小: 每论文 ~200-500KB (depending on claims数量)
    """
    
    def __init__(self, db_path: str = ".cache/claims.db", auto_init: bool = True):
        """
        初始化缓存系统
        
        Args:
            db_path: SQLite数据库路径
            auto_init: 是否自动初始化数据库表
        """
    
    def get_chunk_signature(self, text: str, source_meta: dict) -> str:
        """
        生成chunk的唯一签名。
        
        签名基于:
        - 文本内容的SHA256
        - 论文ID (doc_id)
        - 版本号 (для future compatibility)
        
        Args:
            text: chunk文本
            source_meta: 源元数据 (至少包含 doc_id)
        
        Returns:
            64字符的十六进制签名
        """
    
    def get_claims(self, chunk_sig: str) -> Optional[List[Dict]]:
        """
        从缓存中查询claims。
        
        Args:
            chunk_sig: chunk签名
        
        Returns:
            claims列表或None (未找到)
        """
    
    def save_claims(self, chunk_sig: str, claims: List[Dict], 
                   metadata: Optional[Dict] = None):
        """
        保存claims到缓存。
        
        Args:
            chunk_sig: chunk签名
            claims: 已提取的claims列表
            metadata: 可选元数据 (e.g. llm_model, extraction_time)
        """
    
    def invalidate_paper(self, doc_id: str):
        """
        失效某篇论文的所有缓存。
        
        用途: 当论文被更新时调用
        
        Args:
            doc_id: 论文ID
        """
    
    def get_stats(self) -> Dict[str, int]:
        """
        获取缓存统计信息。
        
        Returns:
            {
                "total_entries": 1234,
                "cache_size_mb": 256,
                "hit_rate": 0.65,
                "papers_cached": 42
            }
        """
```

---

## 2. 数据库设计

### 2.1 Schema

```sql
-- 表1: claims_cache (核心缓存表)
CREATE TABLE IF NOT EXISTS claims_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 签名与标识
    chunk_signature TEXT NOT NULL UNIQUE,
    doc_id TEXT NOT NULL,  -- 论文ID (用于失效整篇论文的缓存)
    chunk_index INTEGER,   -- chunk在论文中的位置
    
    -- 缓存数据
    claims_json TEXT NOT NULL,  -- JSON格式的claims列表
    
    -- 元数据
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,  -- 被使用次数 (用于统计)
    
    -- 版本管理
    cache_version TEXT DEFAULT '1.0',  -- 缓存数据格式版本
    llm_model TEXT,  -- 使用的LLM模型 (gpt-4o-mini等)
    extraction_confidence REAL,  -- 平均置信度
    
    INDEX idx_doc_id (doc_id),
    INDEX idx_cached_at (cached_at)
);

-- 表2: cache_metadata (缓存元数据)
CREATE TABLE IF NOT EXISTS cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 存储: last_cleanup, cache_policy, total_hits等
```

### 2.2 索引策略

```python
# 需要的索引
- chunk_signature (唯一, 快速查询)
- doc_id (快速失效整篇论文)
- cached_at (趋势分析)
- access_count (热点分析)
```

---

## 3. 实现细节

### 3.1 签名生成

```python
def get_chunk_signature(self, text: str, source_meta: dict) -> str:
    """
    生成稳定的chunk签名。
    
    注意:
    - 必须标准化文本 (remove extra spaces, lowercase等)
    - 必须包含doc_id以区分来自不同论文的相同chunk
    - 不应包含时间戳 (为了replay consistency)
    """
    # 标准化文本
    normalized_text = ' '.join(text.split())  # 移除多余空格
    
    # 获取doc_id
    doc_id = source_meta.get('doc_id', 'unknown')
    
    # 组合签名输入
    signature_input = f"{normalized_text}||{doc_id}||v1"
    
    # SHA256哈希
    return hashlib.sha256(signature_input.encode('utf-8')).hexdigest()
```

**测试**:
```python
def test_signature_stability():
    """相同input应生成相同signature"""
    sig1 = cache.get_chunk_signature("Hello  World", {"doc_id": "paper1"})
    sig2 = cache.get_chunk_signature("Hello World", {"doc_id": "paper1"})
    assert sig1 == sig2  # 忽略空格差异
    
def test_signature_different_doc():
    """不同doc_id应生成不同signature"""
    text = "Same text"
    sig1 = cache.get_chunk_signature(text, {"doc_id": "paper1"})
    sig2 = cache.get_chunk_signature(text, {"doc_id": "paper2"})
    assert sig1 != sig2
```

---

### 3.2 缓存查询

```python
def get_claims(self, chunk_sig: str) -> Optional[List[Dict]]:
    """
    快速查询缓存。
    
    流程:
    1. SQL查询 (O(1) 通过唯一索引)
    2. JSON反序列化
    3. 更新 accessed_at 和 access_count
    """
    try:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT claims_json, access_count 
            FROM claims_cache 
            WHERE chunk_signature = ?
            """,
            (chunk_sig,)
        )
        row = cursor.fetchone()
        
        if row:
            # 更新访问计数 (async)
            cursor.execute(
                """
                UPDATE claims_cache 
                SET accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1
                WHERE chunk_signature = ?
                """,
                (chunk_sig,)
            )
            conn.commit()
            
            # 反序列化
            claims_json = json.loads(row['claims_json'])
            return claims_json
        
        conn.close()
        return None
    
    except Exception as e:
        logger.error(f"缓存查询失败: {e}")
        return None
```

**性能**: <5ms (SQLite本地B-tree查询)

---

### 3.3 缓存写入

```python
def save_claims(self, chunk_sig: str, claims: List[Dict], 
               metadata: Optional[Dict] = None):
    """
    保存claims到缓存 (带冲突处理)。
    """
    try:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 提取元数据
        doc_id = metadata.get('doc_id') if metadata else 'unknown'
        llm_model = metadata.get('llm_model') if metadata else None
        
        # 计算平均置信度
        confidences = [c.get('confidence', 0.5) for c in claims]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        # 插入或更新 (IGNORE冲突: 保持最早的缓存)
        cursor.execute(
            """
            INSERT OR IGNORE INTO claims_cache
            (chunk_signature, doc_id, claims_json, llm_model, extraction_confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chunk_sig,
                doc_id,
                json.dumps(claims, ensure_ascii=False),
                llm_model,
                avg_confidence
            )
        )
        conn.commit()
        conn.close()
        
        logger.debug(f"✅ 缓存保存: {chunk_sig[:8]} ({len(claims)} claims)")
    
    except Exception as e:
        logger.error(f"缓存写入失败: {e}")
```

---

### 3.4 缓存失效策略

```python
def invalidate_paper(self, doc_id: str):
    """
    删除整篇论文的所有缓存。
    
    用途: 
    - 论文被更新时
    - 用户手动清理时
    """
    try:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM claims_cache WHERE doc_id = ?", (doc_id,))
        count = cursor.fetchone()[0]
        
        cursor.execute("DELETE FROM claims_cache WHERE doc_id = ?", (doc_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"📌 缓存失效: {doc_id} ({count} entries)")
    
    except Exception as e:
        logger.error(f"缓存失效失败: {e}")

def clear_all(self):
    """清空所有缓存 (危险操作)"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM claims_cache")
    conn.commit()
    conn.close()
    logger.warning("🗑️ 所有缓存已清空")

def cleanup_old_entries(self, days: int = 30):
    """
    清理30天未访问的条目 (可选的定期维护)
    """
    try:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_date = datetime.now() - timedelta(days=days)
        cursor.execute(
            "DELETE FROM claims_cache WHERE accessed_at < ?",
            (cutoff_date,)
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"🧹 清理过期缓存: {deleted} entries")
    
    except Exception as e:
        logger.error(f"清理失败: {e}")
```

---

### 3.5 统计功能

```python
def get_stats(self) -> Dict[str, Any]:
    """获取缓存统计信息"""
    try:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 总条目数
        cursor.execute("SELECT COUNT(*) FROM claims_cache")
        total_entries = cursor.fetchone()[0]
        
        # 缓存大小 (MB)
        cursor.execute("SELECT SUM(LENGTH(claims_json)) FROM claims_cache")
        total_size_bytes = cursor.fetchone()[0] or 0
        cache_size_mb = total_size_bytes / (1024 * 1024)
        
        # 命中率
        cursor.execute("SELECT SUM(access_count) FROM claims_cache")
        total_accesses = cursor.fetchone()[0] or 0
        hit_rate = total_accesses / total_entries if total_entries > 0 else 0
        
        # 论文数
        cursor.execute("SELECT COUNT(DISTINCT doc_id) FROM claims_cache")
        papers_cached = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_entries": total_entries,
            "cache_size_mb": round(cache_size_mb, 2),
            "hit_rate": round(hit_rate, 2),
            "papers_cached": papers_cached,
            "avg_claims_per_chunk": round(total_entries / papers_cached, 1) if papers_cached > 0 else 0
        }
    
    except Exception as e:
        logger.error(f"统计失败: {e}")
        return {}

def log_stats(self):
    """打印统计信息"""
    stats = self.get_stats()
    logger.info(
        f"📊 缓存统计 - 条目: {stats['total_entries']}, "
        f"大小: {stats['cache_size_mb']}MB, "
        f"命中率: {stats['hit_rate']:.1%}, "
        f"论文数: {stats['papers_cached']}"
    )
```

---

## 4. 集成到ClaimExtractor

### 4.1 修改 `layers/p2_claim_extractor.py`

```python
# 导入缓存系统
from layers.claim_cache import ClaimCache

class ClaimExtractor:
    def __init__(self, llm_client: Optional[Callable] = None, enable_cache: bool = True):
        self.llm_client = llm_client
        self.cache = ClaimCache() if enable_cache else None
        self.semaphore = asyncio.Semaphore(5)
        
        # ... 其他初始化 ...
        
        if self.cache:
            logger.info("✅ 缓存系统已启用")
            self.cache.log_stats()
    
    async def extract_from_chunk(self, text: str, source: SourceMeta) -> List[Claim]:
        """
        从文本块中提取声明 (支持缓存)
        
        流程:
        1. 生成签名
        2. 查询缓存 ← 新增
        3. 缓存命中 → 返回
        4. 缓存未命中 → 正常流程
        5. 保存到缓存 ← 新增
        """
        
        # 1. 生成签名
        if self.cache:
            chunk_sig = self.cache.get_chunk_signature(text, source.__dict__)
            
            # 2. 查询缓存
            cached_claims = self.cache.get_claims(chunk_sig)
            if cached_claims is not None:
                logger.debug(f"✅ 缓存命中: {len(cached_claims)} claims")
                return [Claim(**c) for c in cached_claims]
        
        # 3. 缓存未命中，执行正常流程
        rough_claims = self._regex_pre_extract(text, source)
        ner_claims = self._ner_enhance_claims(text, source, rough_claims)
        
        if self.llm_client:
            low_confidence = [c for c in ner_claims if c.confidence < 0.80]
            if low_confidence:
                refined = await self._llm_refine_edge_cases(text, low_confidence, source)
                final_claims = [c for c in ner_claims if c.confidence >= 0.80] + refined
            else:
                final_claims = ner_claims
        else:
            final_claims = ner_claims
        
        # 4. 保存到缓存
        if self.cache:
            self.cache.save_claims(
                chunk_sig,
                [c.__dict__ for c in final_claims],
                metadata={
                    "doc_id": source.doc_id,
                    "llm_model": "gpt-4o-mini"
                }
            )
        
        return final_claims
```

---

## 5. 测试用例

### 5.1 单元测试

```python
# tests/test_claim_cache.py

import pytest
import json
import tempfile
from pathlib import Path
from layers.claim_cache import ClaimCache

class TestClaimCache:
    
    @pytest.fixture
    def cache(self):
        """创建临时缓存用于测试"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ClaimCache(db_path=f"{tmpdir}/test.db")
            yield cache
    
    def test_signature_generation(self, cache):
        """签名生成测试"""
        text = "Hello, this is a test chunk"
        meta = {"doc_id": "paper1"}
        sig = cache.get_chunk_signature(text, meta)
        assert len(sig) == 64  # SHA256 hex
    
    def test_save_and_retrieve(self, cache):
        """保存和查询"""
        sig = "test_sig_001"
        claims = [{"id": 1, "text": "Claim 1"}, {"id": 2, "text": "Claim 2"}]
        
        cache.save_claims(sig, claims)
        retrieved = cache.get_claims(sig)
        
        assert retrieved is not None
        assert len(retrieved) == 2
        assert retrieved[0]["id"] == 1
    
    def test_cache_miss(self, cache):
        """缓存未命中"""
        retrieved = cache.get_claims("nonexistent_sig")
        assert retrieved is None
    
    def test_invalidate_paper(self, cache):
        """论文失效"""
        sig1 = "sig_001"
        sig2 = "sig_002"
        
        cache.save_claims(sig1, [{"id": 1}], metadata={"doc_id": "paper1"})
        cache.save_claims(sig2, [{"id": 2}], metadata={"doc_id": "paper1"})
        
        # 失效整篇论文
        cache.invalidate_paper("paper1")
        
        # 都应该查不到
        assert cache.get_claims(sig1) is None
        assert cache.get_claims(sig2) is None
    
    def test_stats(self, cache):
        """统计功能"""
        cache.save_claims("sig1", [{"id": 1}], metadata={"doc_id": "p1"})
        cache.save_claims("sig2", [{"id": 2}], metadata={"doc_id": "p2"})
        
        stats = cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["papers_cached"] == 2
```

### 5.2 集成测试

```python
# tests/test_claim_extractor_cache.py

@pytest.mark.asyncio
async def test_claim_extraction_with_cache():
    """集成测试: 验证缓存工作流"""
    
    extractor = ClaimExtractor(enable_cache=True)
    text = "Laser power affects pool dynamics"
    source = SourceMeta(doc_id="paper1", chunk_index=0)
    
    # 第一次提取 (应该调用LLM/NER)
    claims_1 = await extractor.extract_from_chunk(text, source)
    
    # 第二次提取 (应该从缓存返回)
    claims_2 = await extractor.extract_from_chunk(text, source)
    
    # 应该相同
    assert len(claims_1) == len(claims_2)
    assert claims_1[0]["id"] == claims_2[0]["id"]
```

---

## 6. 性能基准

### 6.1 预期表现

| 操作 | 无缓存 | 有缓存命中 | 提速比 |
|------|--------|---------|--------|
| 单chunk提取 | 100-200ms | 5-10ms | 15-20x |
| 10chunk处理 | 1-2秒 | 50-100ms | 15-20x |
| 论文完整处理 | 4-6分钟 | 20-30秒 | 12-15x |

### 6.2 监控指标

```python
# main_engine.py 中添加监控
cache_stats = extractor.cache.get_stats()
logger.info(f"缓存统计: {cache_stats}")
# 输出: {'total_entries': 1024, 'cache_size_mb': 256, 'hit_rate': 0.65, ...}
```

---

## 7. 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `layers/claim_cache.py` | 250-300 | 缓存核心 |
| 修改 `layers/p2_claim_extractor.py` | +80 | 集成缓存 |
| `tests/test_claim_cache.py` | 150-200 | 单元测试 |
| `tests/test_claim_extractor_cache.py` | 80-100 | 集成测试 |

**总工作量**: ~500-600 行

---

## 8. 交付清单

- [ ] `layers/claim_cache.py` 实现
- [ ] SQLite schema 与索引
- [ ] 集成到 `ClaimExtractor`
- [ ] 完整的单元测试 (>90%)
- [ ] 集成测试验证
- [ ] 性能基准测试
- [ ] 文档与使用示例
- [ ] 监控系统集成
