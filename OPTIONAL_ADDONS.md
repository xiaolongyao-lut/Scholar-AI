# 可选扩展 · Optional Addons

Scholar AI 默认走 API-first 路线 — 接 SiliconFlow / DashScope 等远端服务,主安装包 ~466MB,绝大多数用户不需要任何额外配置。

下面这些"可选扩展"针对**离线 / 防火墙 / 想用本地 GPU 推理**的用户。**主安装包不含它们的运行时依赖**,需要按下面步骤自己装。装完到 `设置 → 实验性功能` 把对应开关打开即可。

---

## 一、PDF 结构化解析 · marker-pdf

**作用**: 替代默认 PyMuPDF 解析新上传的 PDF,能识别标题层级、表格、公式、图片,RAG 检索质量更好。

**主包不含原因**: marker-pdf 含 2GB+ 模型权重,而且首次解析每篇 5-15 分钟(GPU 也要 18 分钟/篇),对绝大多数用户来说"鸡肋"。只有需要从论文里精确提取表/公式的研究场景才值得装。

**装法** (Windows PowerShell / cmd):

```powershell
# 进 Scholar AI 用的同一个 Python 环境 (开发版用 .venv-1)
pip install marker-pdf
```

如果你跑的是 Inno Setup 装的安装版,marker 默认装不进 onedir 内嵌的 PyInstaller bundle — 那种情况需要 dev 环境跑(`run_literature_assistant.py` 启动)才能开启 marker。

**验证装好了**: 设置 → 实验性功能,把「PDF 结构化解析(marker)」开关打开 — 顶部会出现绿色「marker 后端可用」chip。打不开就是没装上。

**关掉**: 把开关关掉,新上传的 PDF 走回 PyMuPDF 默认链路;已经入库的 marker 结构化数据保留。

**完全卸载**:

```powershell
pip uninstall marker-pdf
```

---

## 二、本地推理回退 · rerank + embedding

**作用**: 远端 rerank / embedding API 不可达时(DNS 屏蔽 / 403 / 限流 / 完全离线),自动回退到本地 BAAI/bge-reranker-v2-m3 / BAAI/bge-m3 模型,在 GPU 或 CPU 上跑。链路: 远端 API → 本地模型 → hybrid_score 兜底。

**主包不含原因**: CUDA 版 torch + sentence-transformers + cuDNN runtime 加起来约 3GB,装进主包会让安装包从 466MB 涨到 3.3GB。绝大多数用户用得到 API,装上反而拖累首次安装。

**装法** (Windows + RTX 系列 GPU,例如 4060):

```powershell
# 1) 装 GPU 版 PyTorch (例:cu126;无 GPU 装 cpu 版)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126

# 2) 装 sentence-transformers (会顺带装 transformers / tokenizers)
pip install sentence-transformers

# 3) 预下载默认模型权重 (首次回退会自动拉,提前下避免回退时阻塞)
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
python -c "from transformers import AutoModelForSequenceClassification, AutoTokenizer; AutoModelForSequenceClassification.from_pretrained('BAAI/bge-reranker-v2-m3'); AutoTokenizer.from_pretrained('BAAI/bge-reranker-v2-m3')"
```

CPU 版 (无 GPU 也能跑,只是慢一些):

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install sentence-transformers
```

**验证装好了**: 设置 → Rerank 卡片 / Embedding 卡片头部各有一个回退状态 chip:

| 颜色 | 含义 |
|---|---|
| 绿色「本地回退: 可用 · CUDA」 | 装好了,GPU 模式,API 失败时自动回退 |
| 绿色「本地回退: 可用 · CPU」 | 装好了,CPU 模式 (慢但能跑) |
| 琥珀「本地回退: 需下载」 | torch 装了,但模型权重没在 HF 缓存,且允许联网下载 |
| 灰色「本地回退: 已禁用」 | 你设了 `LOCAL_RERANK_DISABLED=1` 或 `LOCAL_EMBEDDING_DISABLED=1` |
| 红色「本地回退: 不可用」 | torch / sentence-transformers 没装 — 走这里 |

**强制 CPU 模式** (即使有 GPU,某些情况想让 4060 不被占): 启动前设环境变量

```powershell
$env:LOCAL_RERANK_DEVICE = "cpu"
$env:LOCAL_EMBEDDING_DEVICE = "cpu"
```

**完全禁用本地回退** (装了但不想用):

```powershell
$env:LOCAL_RERANK_DISABLED = "1"
$env:LOCAL_EMBEDDING_DISABLED = "1"
```

**完全卸载**:

```powershell
pip uninstall torch torchvision sentence-transformers transformers tokenizers
```

---

## 三、独立本地推理服务

如果你想在另一台机器 (例如 GPU 服务器) 跑独立的 rerank / embedding 服务,App 通过 OpenAI / Cohere 兼容协议消费:

- Rerank: `python local_rerank_server.py --model BAAI/bge-reranker-v2-m3 --port 7997`
- Embedding: `python local_embedding_server.py --model BAAI/bge-m3 --port 7998`

然后在 `设置 → API` 把 Rerank / Embedding 的 `base_url` 改成 `http://<服务器IP>:7997` / `http://<服务器IP>:7998`。换模型操作手册见 [LOCAL_RERANK_MODELS.md](LOCAL_RERANK_MODELS.md)。

---

## 设计哲学 · 为什么"主线 + 可选扩展"两条线

- **主安装包 (~466MB)** = API-first,给所有人。首次安装快,默认开箱即用,RAG 主链 5 项 (chunk 加权 + hybrid + TOLF + RRF + sibling) 直接是默认行为。
- **可选扩展** = 给离线场景 / 自有 GPU / 想精读表格的少数用户。pip install 是最自然的"按需推送",装包 = 启用,卸包 = 禁用,零额外维护。

如果哪天 marker 的速度从 5-15 min/篇 降到 1 min 以内,或 GPU 推理变成所有人都需要,我们再讨论是否进主包。
