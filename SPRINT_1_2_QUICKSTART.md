# 🚀 Sprint 1-2 快速启动指南

## 前置检查

```bash
# 1. 确保已安装必要的包
pip install httpx scipy numpy

# 2. 设置环境变量（硅基流动 API Key）
export SILICONFLOW_API_KEY="your_api_key_here"
# 或在 .env 文件中
# SILICONFLOW_API_KEY=your_api_key_here
```

---

## Sprint 1：离线关注点提取（2-3 天）

### 准备阶段
确保您有一个包含文献的文件夹，例如：
```
papers/
├── paper1.md
├── paper2.md
├── paper3.md
└── ...
```

如果没有现成的文献文件，您可以：
- 从现有的 PDF 转换为 Markdown（使用 Marker、Docling 等）
- 或者创建一个包含文献摘要的 Markdown 文件夹

### 执行提取
```bash
cd 写作材料包/代码/00_模块化流水线脚本/

python -m layers.focus_extractor \
  --doc-folder "./papers" \
  --output "focus_points.json" \
  --batch-size 5 \
  --delay 2.0
```

**参数说明**：
- `--doc-folder`: 文献文件夹路径
- `--output`: 输出 JSON 文件路径
- `--batch-size`: 每批处理的文件数（根据 API 限制调整）
- `--delay`: 批次间延迟秒数（避免限流）

### 预期输出
```
2026-04-01 10:30:00 - focus_extractor - INFO - 发现 15 个文献文件

[批次 1/3]
✓ 从 paper1.md 提取到 8 个标签
✓ 从 paper2.md 提取到 7 个标签
累计收集: 23 个关注点
等待 2.0s 后继续...

[批次 2/3]
...

✓ 提取完成！共 287 个去重关注点
✓ 关注点库已保存: focus_points.json
  - 总数: 287
  - 文件大小: 45.3 KB
```

### 验证输出
```bash
# 查看生成的 focus_points.json
cat focus_points.json | python -m json.tool | head -30

# 应该看到类似：
{
  "timestamp": "2026-04-01T10:30:00.123456",
  "total_points": 287,
  "points": [
    "参数优化",
    "热输入控制",
    "晶粒细化",
    "激光功率调制",
    "熔池流动动力学",
    ...
  ],
  "stats": {
    "failed_documents": 0,
    "failed_documents_list": []
  }
}
```

---

## Sprint 2：向量语义路由（2-3 天）

### 前置条件
- ✅ `focus_points.json` 已生成

### 初始化路由器
```python
import os
from layers.semantic_router import SemanticRouter

# 获取 API Key
api_key = os.environ['SILICONFLOW_API_KEY']

# 初始化（这一步会自动向量化所有关注点）
router = SemanticRouter(
    api_key=api_key,
    focus_points_path='focus_points.json'
)

# 初始化过程中会看到：
# INFO - 加载关注点库: 287 个标签
# INFO - 正在向量化 287 个关注点...
# INFO - 进度: 50/287
# INFO - 进度: 100/287
# INFO - 进度: 150/287
# ...
# INFO - ✓ 向量化完成！维度: (287, 1024)
```

### 使用路由器
```python
import asyncio

async def test_routing():
    # 查询示例
    query = "激光功率如何影响熔池中的氮传输？"
    
    # 异步调用
    results = await router.route_query(query, top_k=3)
    
    print(f"查询: {query}")
    print(f"路由结果:")
    for i, point in enumerate(results, 1):
        print(f"  {i}. {point}")

asyncio.run(test_routing())

# 输出示例：
# 查询: 激光功率如何影响熔池中的氮传输？
# 路由结果:
#   1. 热输入控制
#   2. 熔池流动动力学
#   3. 氮化过程
```

### 查看统计信息
```python
# 获取路由器状态
stats = router.get_statistics()

print(f"关注点数: {stats['total_points']}")
print(f"向量维度: {stats['vector_dimension']}")
print(f"模型: {stats['embedding_model']}")
print(f"最后查询: {stats['last_query']}")
```

---

## 性能基准

### Sprint 1 (focus_extractor)
- 提取速度：约 **2 分钟/篇文献**（取决于文献长度和网络）
- 50 篇文献：约 **1.5-2 小时**
- API 调用：**N 次**（N = 文献数，可批量减少）

### Sprint 2 (semantic_router)
- 初始化时间：约 **20-30 秒**（向量化 287 个点）
- 查询响应：**< 100ms**（包括向量化 + 相似度计算）
- 内存占用：约 **300MB**（287 个 1024 维向量）

---

## 常见问题

### Q1: 如何测试没有真实文献的情况？

创建测试文献 `test_papers/sample.md`：
```markdown
# 激光焊接中的熔池动力学研究

本文研究激光焊接过程中的熔池流动、温度分布和组织演变。

## 关键发现
- 激光功率显著影响热输入和冷却速率
- 熔池流动导致晶粒细化
- 残余应力与焊接参数密切相关
```

然后运行：
```bash
python -m layers.focus_extractor \
  --doc-folder "./test_papers" \
  --output "focus_points.json"
```

### Q2: API 调用被限制怎么办？

调整参数：
```bash
python -m layers.focus_extractor \
  --doc-folder "./papers" \
  --batch-size 2 \
  --delay 5.0  # 增加延迟
```

或者分多次运行，使用不同的输出文件。

### Q3: 如何更新关注点库？

重新运行 `focus_extractor.py`，它会：
1. 读取所有最新的文献
2. 重新提取标签
3. 生成新的 `focus_points.json`

然后重新初始化 `SemanticRouter`，它会自动重新向量化。

### Q4: 可以离线使用吗？

目前不行（需要调用硅基流动 API）。但您可以：
1. 预先缓存所有向量到本地
2. 或者使用本地的轻量模型（如 Sentence Transformers）

---

## 下一步（Sprint 3）

一旦 Sprint 1-2 完成，您可以：

1. **集成到主流程**
   ```python
   # 在 00_Integrated_Pipeline_v40.0.py 中
   from layers.semantic_router import SemanticRouter
   
   router = SemanticRouter(api_key, 'focus_points.json')
   ```

2. **构建 Streamlit UI**（见 `main_rag_workflow.py`）

3. **与 RAG-Anything 打通**

---

## 📞 调试技巧

### 启用详细日志
```python
import logging

logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 检查向量质量
```python
# 查看特定点的相似点
router.get_point_info("热输入控制")

# 输出：
# {
#     'point': '热输入控制',
#     'index': 5,
#     'vector_shape': (1024,),
#     'related_points': [
#         ('冷却速率', 0.87),
#         ('激光功率', 0.84),
#         ('温度梯度', 0.81)
#     ]
# }
```

### 验证 API 连接
```python
import httpx

client = httpx.AsyncClient(proxies=None)
response = await client.post(
    "https://api.siliconflow.cn/v1/embeddings",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "model": "BAAI/bge-m3",
        "input": ["测试"]
    }
)

print(response.json())
```

---

**准备好了吗？从 Sprint 1 开始吧！** 🚀
