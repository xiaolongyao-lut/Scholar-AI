# 本地单用户优化规划 (调整后)

**用户需求**: 纯本地单用户，不涉及服务器/多用户  
**核心目标**: 改进程序能力，减少手动操作，提升本地工作体验

---

## 🎯 优先级重新调整

这改变了一切。对于本地单用户场景：

### 优先级: 🔴 立即做 (本周内)

#### #1 **鲁棒性 - JSON解析修复** 
```
原因: 生产级必需 (无论单/多用户都要做)
工作量: 150行
收益: ✅ 防止pipeline崩溃
方案: RobustJSONParser (详见GEMINI_SUGGESTIONS_EVALUATION.md)

这是0号必做项，不讨论。
```

**时间: 1-2 天**

---

### 优先级: 🟠 本周末 (高价值)

#### #2 **缓存系统 - 本地文献重复处理加速** ⬆️ 从"可选"升为"必做"

**为什么在本地单用户下这变得最重要?**

```
场景: 用户反复处理同一批论文

第一次运行 (4篇论文):
  Paper_A → extract → NER → [LLM精化10%] → claims → score
  Paper_B → extract → NER → [LLM精化10%] → claims → score
  Paper_C → extract → NER → [LLM精化10%] → claims → score
  Paper_D → extract → NER → [LLM精化10%] → claims → score
  总时间: ~4分钟 (等待LLM调用)

第二次运行 (改了goal，重新处理相同4篇论文):
  Paper_A → extract → NER → [LLM精化10%] → claims → score  ← 重复!
  Paper_B → extract → NER → [LLM精化10%] → claims → score  ← 重复!
  ...
  总时间: ~4分钟 (完全浪费)

如果有缓存:
  缓存命中 → 直接用之前的 claims
  总时间: ~20秒 (跳过LLM调用)
  提速比: 12倍
```

**本地单用户的实际工作流**:
- 需要反复尝试不同的 goal / scoring_rules
- 不想每次都等LLM重新提取
- 想快速迭代和对比结果

**缓存系统的实现**:

```python
# layers/claim_cache.py (新建)

import sqlite3
import hashlib
from pathlib import Path

class ClaimCache:
    def __init__(self, db_path: str = ".cache/claims.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
    
    def get_chunk_hash(self, text: str, source_meta: dict) -> str:
        """生成chunk的唯一签名"""
        combined = f"{text}|{source_meta['doc_id']}"
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def get_claims(self, chunk_hash: str) -> Optional[List[dict]]:
        """查询缓存的claims"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT claims_json FROM claims_cache WHERE chunk_hash = ?",
            (chunk_hash,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None
    
    def save_claims(self, chunk_hash: str, claims: List[dict]):
        """保存claims到缓存"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO claims_cache (chunk_hash, claims_json, cached_at) "
            "VALUES (?, ?, datetime('now'))",
            (chunk_hash, json.dumps(claims, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    
    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims_cache (
                chunk_hash TEXT PRIMARY KEY,
                claims_json TEXT NOT NULL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
```

**集成到 ClaimExtractor**:

```python
# layers/p2_claim_extractor.py 改动

class ClaimExtractor:
    def __init__(self, llm_client=None, enable_cache=True):
        self.llm_client = llm_client
        self.cache = ClaimCache() if enable_cache else None
    
    async def extract_from_chunk(self, text: str, source: SourceMeta):
        # 1. 检查缓存
        if self.cache:
            chunk_hash = self.cache.get_chunk_hash(text, source.__dict__)
            cached_claims = self.cache.get_claims(chunk_hash)
            if cached_claims:
                logger.info(f"✅ 缓存命中: {chunk_hash[:8]}")
                return [Claim(**c) for c in cached_claims]
        
        # 2. 正常流程 (regex → NER → LLM)
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
        
        # 3. 保存到缓存
        if self.cache:
            self.cache.save_claims(chunk_hash, [c.__dict__ for c in final_claims])
        
        return final_claims
```

**工作量**: 
- ClaimCache: 120行
- 集成到ClaimExtractor: 50行
- 测试: 80行
- **总计: 250行**

**收益**: 
- 重复处理速度: 10-12倍
- Token节省: 90%+ (同一文献不再调用LLM)
- 本地迭代反馈时间: 从 4分钟 → 20秒

**时间: 2-3 天**

---

### 优先级: 🟡 下周 (体验优化)

#### #3 **本地小工具集优化**

对本地单用户，这些比"统一入口"更值得做：

##### 3a. **快速预览工具** (新增)
```bash
# 用法
python tools/preview_analysis.py output/paper_001/03_academic_scoring.json
# 输出: 论文评分、关键claims、知识图谱预览
```

**工作量**: 100行  
**收益**: 快速查看结果，不用每次都打开HTML

---

##### 3b. **批量对比工具** (新增)
```bash
# 比较两个goal的分析结果差异
python tools/compare_analyses.py \
  --goal1 "焊接参数优化" \
  --goal2 "材料性能评估" \
  --output_dir output/
```

**工作量**: 150行  
**收益**: 快速对比不同分析角度的差异

---

##### 3c. **可视化自动导出** (改进 #4)
```bash
# 自动生成交互式可视化
python tools/export_visualization.py output/paper_001/
# 生成: paper_001_graph.html (可本地打开)
```

**改进原有的 p3_exporter.py**:
```python
# layers/p3_exporter.py 新增方法

def export_interactive_html(self, dag_data: Dict, output_path: str):
    """生成交互式HTML可视化"""
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <style>
            body { font-family: Arial; margin: 20px; }
            svg { border: 1px solid #ccc; }
            .node { stroke: #fff; stroke-width: 1.5px; }
            .link { stroke: #999; stroke-opacity: 0.6; }
        </style>
    </head>
    <body>
        <h1>Knowledge Graph - {title}</h1>
        <svg width="1200" height="800"></svg>
        <script>
            const data = {data_json};
            // d3.js 渲染逻辑
        </script>
    </body>
    </html>
    """
    Path(output_path).write_text(html_template)
```

**工作量**: 200行 (包括D3.js集成)  
**收益**: 生成可本地打开的交互式图谱，无需HTML服务器

**时间: 2-3 天**

---

#### #4 **本地配置管理** (轻量版统一入口)

不做完整的YAML配置系统，做本地配置文件：

```ini
# config/local_settings.ini (新建)

[paths]
pdf_folder = ./input_pdfs
output_folder = ./output
cache_folder = .cache

[processing]
enable_cache = true
max_workers = 4
timeout_seconds = 600

[llm]
model = gpt-4o-mini
use_llm_refinement = true
confidence_threshold = 0.80

[visualization]
auto_export_html = true
export_format = html,cypher,ttl
```

```python
# config/settings.py (新建)

from configparser import ConfigParser
from pathlib import Path

class LocalSettings:
    def __init__(self, config_file: str = "config/local_settings.ini"):
        self.config = ConfigParser()
        self.config.read(config_file)
    
    @property
    def pdf_folder(self) -> Path:
        return Path(self.config.get("paths", "pdf_folder", fallback="./input_pdfs"))
    
    @property
    def enable_cache(self) -> bool:
        return self.config.getboolean("processing", "enable_cache", fallback=True)
    
    # ... 更多属性
```

**工作量**: 80行  
**收益**: 不改代码，改配置文件即可调整参数

**时间: 1 天**

---

## 📊 新的优先级表 (本地单用户版)

| # | 项目 | 优先级 | 时间 | 工作量 | 收益 | 必要性 |
|----|------|--------|------|--------|------|--------|
| **1** | 鲁棒JSON修复 | 🔴 立即 | 1-2d | 150行 | 高(防崩溃) | ✅ 必做 |
| **2** | 缓存系统 | 🟠 本周末 | 2-3d | 250行 | ✅ 高(12倍加速) | ✅ 必做 |
| **3a** | 快速预览工具 | 🟡 下周 | 1d | 100行 | 中 | 🔄 可选 |
| **3b** | 批量对比工具 | 🟡 下周 | 1d | 150行 | 中 | 🔄 推荐 |
| **3c** | 可视化自动导出 | 🟡 下周 | 2-3d | 200行 | 中 | 🔄 可选 |
| **4** | 本地配置管理 | 🟡 下周 | 1d | 80行 | 低-中 | 🔄 可选 |
| ~~#1 统一入口~~ | ~~架构~~ | ~~⚪ 后续~~ | ~~5-7d~~ | ~~400行~~ | ~~中~~ | ~~可延迟~~ |

---

## 🚀 建议的执行计划

### Week 1 (这周)
```
Day 1-2: RobustJSONParser 
  □ layers/robust_parser.py (120行)
  □ 修改 AIAdapter 集成 (30行)
  □ 单元测试 (80行)
  □ 测试: 处理各种畸形JSON

Day 3-4: 缓存系统核心
  □ layers/claim_cache.py (120行)
  □ 修改 ClaimExtractor 集成 (50行)
  
Day 5: 测试和集成验证
  □ 缓存队列测试
  □ 重复处理性能对比
```

**成果**: 本地脚本运行稳定性 + 性能提升10倍

---

### Week 2
```
Day 1: 本地配置管理
  □ config/local_settings.ini + settings.py
  □ 修改主流程读取配置

Day 2-3: 预览和对比工具
  □ tools/preview_analysis.py
  □ tools/compare_analyses.py

Day 4-5: 可视化自动导出
  □ 改进 p3_exporter.py
  □ 生成交互式HTML
```

**成果**: 本地工具链完整，快速迭代能力

---

## 💡 本地单用户的关键痛点

基于上述分析，你的本地工作流痛点应该是：

1. **第一次处理很慢** (等LLM) → RobustJSONParser防crash
2. **第二次处理还很慢** (重复计算) → 缓存系统解决
3. **结果查看不方便** → 预览/对比工具
4. **改goal要改代码** → 配置管理

我的方案就是针对这四个痛点的。

---

## ❓ 下一步确认

1. **同意这个时间表吗？** (Week 1 + Week 2)
2. **要立即启动Week 1吗？**
3. **对Tools (预览/对比)有其他需求吗？**

建议现在就开始 Week 1 Day 1 (RobustJSONParser)，这对系统稳定性最关键。
