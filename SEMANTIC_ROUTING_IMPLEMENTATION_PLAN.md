# 语义路由升级方案 (方向 A) - Sprint 实施计划

**目标**：将硬编码的 `GOAL_MAP` 升级为自动扩充 + 向量语义路由的系统  
**工具链**：硅基流动 BAAI/bge-m3 向量 API + 大模型 API  
**预期周期**：3 个 Sprint（1.5-2 周）  

---

## 📋 Sprint 架构总览

```
现状（v40.0）
├── 07_analysis_scoring_improved_v9.py
│   └── GOAL_MAP (硬编码 14 个词)
│       └── token_score() → 规则匹配
└── layers/ (RAG 框架骨架)

升级目标（v40.4）
├── Sprint 1: 离线关注点库自动提取
│   └── focus_extractor.py （新增）
│       ├── 读取所有 PDF/Markdown 文献
│       ├── 用大模型自动提取专业标签 (5-10/篇)
│       └── 输出 focus_points.json (几千个标签)
│
├── Sprint 2: 向量语义路由核心层
│   └── semantic_router.py （新增）
│       ├── 读取 focus_points.json
│       ├── 调用硅基流动 bge-m3 向量化所有标签
│       ├── 缓存在内存中
│       └── route_query() 毫秒级匹配
│
├── Sprint 3: 系统集成与优化
│   ├── main_rag_workflow.py （新增） 
│   │   ├── 导入 SemanticRouter
│   │   ├── 用户输入 → 语义收束 → RAG-Anything 混合检索
│   │   └── 返回精准的写作点
│   ├── app.py （新增 Streamlit UI）
│   │   └── 可视化整个收束和检索过程
│   └── 集成到 00_Integrated_Pipeline_v40.0.py
│       └── 使用新的语义路由作为前置拦截器
```

---

## 🔄 Sprint 1：离线关注点库自动提取 (2-3 天)

### 文件：`layers/focus_extractor.py`

**核心职责**：
- 遍历本地所有文献（PDF/Markdown）
- 用大模型批量提取关键概念（去重后几千个）
- 保存为 `focus_points.json`（只需运行一次）

**实现要点**：
1. **防卡死网络**：使用屏蔽代理的 `httpx.Client`
2. **批处理**：减少 API 调用（5-10 篇/批）
3. **去重合并**：关注点 + 同义词收敛
4. **重试机制**：处理 API 失败

**伪代码结构**：
```python
class FocusExtractor:
    def __init__(self, api_key, base_url):
        self.client = httpx.Client(proxies=None, timeout=60.0)
        self.api_key = api_key
        
    async def extract_from_document(self, doc_path: str) -> List[str]:
        """提取单篇文献的 5-10 个核心标签"""
        # 读取文件 → 截断至前 3000 tokens
        # 调用大模型提示词：
        #   "列出这篇文献的 5 到 10 个核心研究标签（名词短语）"
        # 返回 ["参数优化", "热输入控制", "晶粒细化", ...]
    
    async def batch_extract(self, doc_folder: str) -> Set[str]:
        """批量提取所有文献并去重"""
        all_tags = set()
        for doc in os.listdir(doc_folder):
            tags = await self.extract_from_document(doc)
            all_tags.update(tags)
        return all_tags
    
    def save_focus_points(self, tags: Set[str], output_path: str):
        """保存为 JSON 供后续模块使用"""
        with open(output_path, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'count': len(tags),
                'points': sorted(list(tags))
            }, f, ensure_ascii=False, indent=2)
```

**运行方式**：
```bash
python -m layers.focus_extractor \
  --doc-folder "./papers" \
  --output "focus_points.json" \
  --batch-size 5
```

**输出文件**（`focus_points.json`）：
```json
{
  "timestamp": "2026-04-01T10:30:00",
  "count": 2847,
  "points": [
    "参数优化",
    "热输入控制",
    "晶粒细化",
    "激光功率调制",
    "熔池流动动力学",
    ...
  ]
}
```

---

## 🧭 Sprint 2：向量语义路由核心层 (2-3 天)

### 文件：`layers/semantic_router.py`

**核心职责**：
- 将 `focus_points.json` 中的所有标签向量化
- 在内存中维护向量缓存
- 用户提问时，毫秒级匹配最相关的 3-5 个关注点

**实现要点**：
1. **向量模型**：硅基流动 `BAAI/bge-m3`（中文优化）
2. **批量向量化**：一次调用多个标签，减少 API 次数
3. **缓存策略**：启动时加载，内存驻留
4. **相似度计算**：余弦相似度（纯 numpy，毫秒级）

**伪代码结构**：
```python
class SemanticRouter:
    def __init__(self, api_key, focus_points_path):
        """初始化时一次性向量化所有关注点"""
        self.api_key = api_key
        self.client = httpx.Client(proxies=None, timeout=60.0)
        
        # 1. 加载关注点库
        with open(focus_points_path) as f:
            data = json.load(f)
            self.focus_points = data['points']  # List[str]
        
        # 2. 批量向量化（调用硅基流动 bge-m3）
        self.focus_vectors = self._batch_vectorize(self.focus_points)
        # shape: (len(focus_points), 1024)  # bge-m3 输出 1024 维
        
    def _batch_vectorize(self, texts: List[str], batch_size=50):
        """批量调用向量 API（减少 API 次数）"""
        vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            # 调用硅基流动 API：/v1/embeddings
            embeddings = call_siliconflow_embedding_api(batch)
            vectors.extend(embeddings)
        return np.array(vectors)
    
    def route_query(self, user_query: str, top_k: int = 3) -> List[str]:
        """
        用户提问 → 收束到关注点
        
        例：
        user_query = "这个实验里的温度参数是怎样影响的？"
        返回 ["热输入控制", "冷却速率", "温度梯度"]
        """
        # 1. 向量化用户查询（一次 API 调用）
        query_vector = call_siliconflow_embedding_api([user_query])[0]
        
        # 2. 余弦相似度计算（纯 numpy，<1ms）
        similarities = cosine_similarity([query_vector], self.focus_vectors)[0]
        
        # 3. 取 top-k
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        top_points = [self.focus_points[i] for i in top_indices]
        
        return top_points
    
    def get_point_hierarchy(self) -> Dict[str, List[str]]:
        """可选：按关键词聚类形成层级（用于 Coarse-to-Fine）"""
        # 对所有关注点向量进行聚类（如 KMeans k=50）
        # 返回层级结构供后续优化使用
        pass
```

**运行方式**：
```bash
# 初始化时（启动系统）
router = SemanticRouter(
    api_key=os.environ['SILICONFLOW_API_KEY'],
    focus_points_path='focus_points.json'
)

# 查询时
top_points = router.route_query("温度如何影响晶粒形态？")
# → ["温度梯度", "冷却速率", "参数优化"]
```

**关键优势**：
- ✅ 毫秒级响应（向量已缓存）
- ✅ 无需本地 GPU（调用云 API）
- ✅ 自动适应新增的关注点（只需重新运行 `focus_extractor.py`）
- ✅ 支持同义词和口语表达（向量语义）

---

## 🔗 Sprint 3：系统集成与优化 (3-4 天)

### 3.1 文件：`main_rag_workflow.py`（核心集成点）

**职责**：
1. 初始化 SemanticRouter
2. 接收用户问题 → 调用路由器 → 获得精准关注点
3. 拼接成增强查询词，发送给 RAG-Anything
4. 返回最终的写作点集合

**伪代码**：
```python
class RAGWorkflow:
    def __init__(self, rag_instance, semantic_router):
        self.rag = rag_instance  # RAG-Anything 实例
        self.router = semantic_router
    
    async def ask_my_literature(self, user_query: str):
        """完整的查询流程"""
        
        # 第 1 步：语义收束
        focused_points = self.router.route_query(user_query, top_k=3)
        
        # 第 2 步：构建增强查询词
        enhanced_query = (
            f"基于关注点 {focused_points}，"
            f"请从文献中检索并回答：{user_query}"
        )
        
        # 第 3 步：调用 RAG-Anything 混合检索
        rag_results = await self.rag.aquery(
            enhanced_query,
            param=QueryParam(mode="hybrid", top_k=10)
        )
        
        # 第 4 步：用大模型生成最终答案
        final_answer = await self.generate_synthesis(
            user_query,
            focused_points,
            rag_results
        )
        
        return {
            'focused_points': focused_points,
            'rag_results': rag_results,
            'final_answer': final_answer,
            'trace': {  # 可视化追踪
                'user_query': user_query,
                'enhanced_query': enhanced_query,
                'routing_confidence': self.router.get_confidence(focused_points)
            }
        }
    
    async def generate_synthesis(self, query, points, rag_results):
        """利用大模型进行最终合成"""
        prompt = f"""
        用户问题：{query}
        系统识别的关注点：{', '.join(points)}
        检索到的相关文献段落：{rag_results[:500]}
        
        请基于上述信息，生成一个学术性的回答。
        """
        # 调用大模型 API
        response = await call_llm(prompt)
        return response
```

**使用示例**：
```python
# 在 00_Integrated_Pipeline_v40.0.py 中集成
workflow = RAGWorkflow(rag_instance, semantic_router)

# 用户提问
result = await workflow.ask_my_literature(
    "激光功率如何影响熔池中的氮传输？"
)

print(f"识别的关注点: {result['focused_points']}")
print(f"最终答案: {result['final_answer']}")
```

---

### 3.2 文件：`app.py`（Streamlit UI）

**职责**：
- 可视化整个流程
- 展示语义收束的中间步骤
- 提供交互式查询界面

**关键组件**：
```python
import streamlit as st

st.set_page_config(page_title="文献语义检索系统", layout="wide")

col1, col2 = st.columns([2, 1])

with col1:
    st.title("📚 文献语义智能检索")
    user_query = st.text_area("输入您的问题", height=100)
    
    if st.button("🔍 检索"):
        with st.spinner("系统正在识别关注点..."):
            # 调用语义路由器
            focused_points = router.route_query(user_query)
            
            # 展示中间步骤
            st.info(f"**✨ 系统已将您的提问语义收束为:**\n{', '.join(focused_points)}")
            
            # 调用 RAG
            with st.spinner("正在从文献库中检索证据..."):
                rag_results = await workflow.ask_my_literature(user_query)
            
            # 流式输出答案
            st.markdown("### 📖 文献综合分析结果")
            with st.spinner("大模型正在生成回答..."):
                for chunk in stream_llm_response(rag_results):
                    st.write(chunk)

with col2:
    st.sidebar.markdown("### ⚙️ 系统状态")
    st.sidebar.metric("关注点库规模", len(router.focus_points))
    st.sidebar.metric("向量维度", 1024)
    st.sidebar.markdown("### 📊 路由信息")
    for point in focused_points:
        st.sidebar.write(f"✓ {point}")
```

---

### 3.3 集成到 `00_Integrated_Pipeline_v40.0.py`

**改动点**：

```python
# 在文件开头添加
from layers.semantic_router import SemanticRouter
from main_rag_workflow import RAGWorkflow

# 在初始化函数中
async def init_system():
    # 现有初始化...
    rag = LightRAG(...)
    
    # 新增：初始化语义路由器
    semantic_router = SemanticRouter(
        api_key=os.environ['SILICONFLOW_API_KEY'],
        focus_points_path='focus_points.json'
    )
    
    # 新增：初始化 RAG 工作流
    workflow = RAGWorkflow(rag, semantic_router)
    
    return workflow

# 在主查询函数中
async def process_goal(user_input: str):
    # 原有逻辑保留，但前置添加语义路由
    focused_points = workflow.router.route_query(user_input)
    
    # 注入到原有的分析流程
    goal_profile = infer_goal_profile(user_input)
    goal_profile['focused_points'] = focused_points  # 额外信息
    
    # 后续调用 analyze_bound() 等函数时，可以利用这个信息
    ...
```

---

## 📊 Sprint 实施时间表

| Sprint | 任务 | 工作量 | 交付物 |
|--------|------|--------|--------|
| **1** | 离线关注点提取 | 2-3 天 | `focus_extractor.py` + `focus_points.json` |
| **2** | 向量语义路由 | 2-3 天 | `semantic_router.py` + 缓存机制 |
| **3a** | 系统集成 | 1-2 天 | `main_rag_workflow.py` + 改造主流程 |
| **3b** | UI 与优化 | 1-2 天 | `app.py` + 性能调优 |

**总预期**：1.5-2 周内完成整个升级

---

## 🔧 硅基流动 API 集成细节

### 向量 API 调用示例

```python
import httpx
import json

async def call_siliconflow_embedding(texts: List[str], api_key: str):
    """调用硅基流动 bge-m3 向量化接口"""
    
    client = httpx.AsyncClient(proxies=None, timeout=60.0)
    
    response = await client.post(
        "https://api.siliconflow.cn/v1/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "BAAI/bge-m3",
            "input": texts,
            "encoding_format": "float"
        }
    )
    
    result = response.json()
    embeddings = [item['embedding'] for item in result['data']]
    return embeddings
```

### 大模型 API 调用示例（保留防卡死机制）

```python
async def call_siliconflow_llm(prompt: str, api_key: str):
    """调用硅基流动大模型（已整合防卡死机制）"""
    
    client = httpx.AsyncClient(proxies=None, timeout=60.0)
    
    response = await client.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-ai/DeepSeek-V3",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
    )
    
    result = response.json()
    return result['choices'][0]['message']['content']
```

---

## ✅ 验证清单

在启动 Sprint 1 前，请确认：

- [ ] 硅基流动账户已开通，有 API key
- [ ] `focus_points.json` 所在文件夹已准备
- [ ] `.env` 中设置了 `SILICONFLOW_API_KEY`
- [ ] 理解三个新文件的职责边界
- [ ] 现有的 `07_analysis_scoring_improved_v9.py` 暂时保留（作为 Fallback）

---

## 🎯 关键里程碑

- **Sprint 1 完成**：系统可以自动扩充关注点库（不再手工维护）
- **Sprint 2 完成**：系统可以毫秒级语义匹配用户问题（替代规则匹配）
- **Sprint 3 完成**：系统完全集成，用户无感知升级，质量显著提升

---

**准备好开始 Sprint 1 了吗？我可以直接给您 `focus_extractor.py` 的完整代码。**
