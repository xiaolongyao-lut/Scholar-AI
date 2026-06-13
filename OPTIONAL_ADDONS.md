# 可选扩展 · Optional Addons (源码版)

> **本文档面向源码版用户**。Windows 安装包 (`Scholar-AI-Setup-x.x.x-windows-x64.exe`) 是 API-first 路线，不包含本地推理模块。

Scholar AI 默认使用远端模型服务（如 SiliconFlow、DashScope 或其他 OpenAI 兼容服务）。从源码运行时，可以按需启用本地 GPU/CPU 推理能力，适合离线环境、受限网络或自有算力场景。

## 重要前提 · 适用范围

| 部署方式 | 本地推理能力 |
|---|---|
| Windows 安装包 | 不可用。默认安装包不包含本地推理模块 |
| 源码运行 | 可用。安装 `marker-pdf` 或 `sentence-transformers torch` 后启用 |
| 自构建完整版安装包 | 可用。构建前设置 `LITASSIST_BUNDLE_RAG=1`，产物约 3GB，本仓库不预构建发布 |

---

## 一、PDF 结构化解析 · marker-pdf

**作用**: 替代默认 PyMuPDF 解析新上传的 PDF,能识别标题层级、表格、公式、图片,RAG 检索质量更好。

**默认安装包不包含的原因**：marker-pdf 依赖较大的模型文件，首次解析单篇 PDF 可能需要数分钟。它适合需要保留标题层级、表格、公式和图片结构的精读场景，不适合作为所有用户的默认依赖。

**装法** (在已经 `pip install -e .` 的源码 venv 内):

```powershell
pip install marker-pdf
```

启用方式: 改 `workspace_artifacts/runtime_state/feature_flags_override.json` 把 `pdf_parser_marker` 设为 `true`,或者设环境变量 `LITASSIST_PDF_PARSER=marker` 启动。

**关掉**: 把开关关掉,新上传的 PDF 走回 PyMuPDF 默认链路;已经入库的 marker 结构化数据保留。

**完全卸载**:

```powershell
pip uninstall marker-pdf
```

---

## 二、本地推理回退 · rerank + embedding

**作用**: 远端 rerank / embedding API 不可达时(DNS 屏蔽 / 403 / 限流 / 完全离线),自动回退到本地模型。设备默认自动选择:有可用 CUDA 就走 GPU,否则降级到 CPU。链路: 远端 API → 本地模型 → hybrid_score 兜底。

**默认安装包不包含的原因**：本地 rerank / embedding 需要 PyTorch、sentence-transformers 和模型权重，完整版体积约 3GB。默认安装包保持 API-first，便于普通用户快速安装和更新。

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

**验证装好了**: 设置 → Rerank 卡片 / Embedding 卡片头部会显示本地回退状态。装上后状态应该是绿色「本地回退: 可用 · CUDA」；无可用 GPU 时会显示「CPU」。

**强制指定设备**: 默认不需要设置。只有想绕开自动检测时,才在启动前设环境变量。

```powershell
# 例如:强制 CPU,避免占用独立显卡
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

## 分发策略

- **默认安装包**：API-first，体积约 466MB，适合大多数用户直接安装使用。
- **源码可选扩展**：面向需要离线运行、自有 GPU 或精细结构化解析的用户，通过额外依赖按需启用。
- **自构建完整版**：面向私有部署或实验环境，可以通过 `LITASSIST_BUNDLE_RAG=1` 将本地推理模块打包进安装目录。
