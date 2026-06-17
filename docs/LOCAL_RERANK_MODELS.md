# 本地 Rerank 回退模型

文献助手主路径走后端配置的 rerank API。外部智能体通过 MCP 使用检索能力，不直接接收 rerank provider key。

当远端 rerank API 失败、被限流或网络断开时，系统可以回退到一个本地 cross-encoder 模型对候选文献重新排序；如果连本地模型也不可用，最终退到 `hybrid_score` 静态排序兜底。

默认本地模型是 **`BAAI/bge-reranker-v2-m3`**(约 1.5GB,中英双语,4 层 cross-encoder)。如果你想换成其他开源模型,本文是操作手册。

## 切换模型 — 三步

### 1. 选模型

需要满足三个条件:

| 条件 | 原因 |
|---|---|
| **HuggingFace cross-encoder** | 适配器调用的是 `AutoModelForSequenceClassification`,要 (query, candidate) → score 接口 |
| **`num_labels=1` 输出标量** | 排序分,不能是分类 logits |
| **`max_length ≥ 512`** | 否则常见学术段落会被截断 |

| 模型 | 大小 | 语言 | 备注 |
|---|---|---|---|
| `BAAI/bge-reranker-v2-m3` | 1.5GB | 中英多语 | **默认**。质量与速度均衡 |
| `BAAI/bge-reranker-large` | 1.3GB | 英文为主 | 学术英文检索表现稍好 |
| `BAAI/bge-reranker-base` | 280MB | 英文 | 显存/磁盘紧张时换它 |
| `BAAI/bge-reranker-v2-gemma` | 5.5GB | 中英 | 质量更高但需 GPU 才实用 |
| `jinaai/jina-reranker-v2-base-multilingual` | 280MB | 多语 | 体积小且新 |
| `mixedbread-ai/mxbai-rerank-large-v1` | 1.6GB | 英文 | 最近 SOTA 候选 |

不推荐:
- **任意 BERT classifier** — 输出 logits 而非排序分,适配器会拒绝加载
- **任何 generative LLM(LLaMA / Qwen 等)** — 不是 cross-encoder,跑不出来

### 2. 准备权重

两条路:

**A. 离线下载(推荐,内网/隔离环境)**

```bash
# 在能联网的机器上拉权重
pip install huggingface_hub
huggingface-cli download <model_name> --local-dir ~/hf_models/<model_name>

# 然后整目录拷到目标机器的 HF 缓存
# Windows: C:\Users\<you>\.cache\huggingface\hub\models--<org>--<name>\
# Linux/Mac: ~/.cache/huggingface/hub/models--<org>--<name>/
```

**B. 允许联网下载**

在目标机器设置:

```
LOCAL_RERANK_ALLOW_DOWNLOAD=1
```

文献助手第一次回退时会自动 `from_pretrained()` 下载到 HF 缓存。**这会消耗运行时延** — 首次回退可能要等 30 秒以上,不推荐生产环境用这条路径。

### 3. 告诉文献助手

设置环境变量(项目根 `.env` 或系统级,推荐前者):

```
LOCAL_RERANK_MODEL_NAME=BAAI/bge-reranker-large
```

可选调参:

```
LOCAL_RERANK_DEVICE=cuda         # 默认 auto:有 GPU 用 cuda,没 GPU 用 cpu
LOCAL_RERANK_MAX_LENGTH=512      # 默认 512,clamp [16, 8192]
LOCAL_RERANK_BATCH_SIZE=8        # 默认 8,clamp [1, 128]
LOCAL_RERANK_DISABLED=0          # 设 1 完全关闭本地回退
```

重启后端(`uvicorn ...`)后,在 **Settings → Rerank 模型配置 → 本地回退 chip** 里看状态:

- 🟢 **本地回退: 可用 · CUDA** — 一切就绪
- 🟡 **本地回退: 需下载** — 权重不在,但允许联网拉
- 🔴 **本地回退: 不可用** — 权重不在且没允许下载
- ⚫ **本地回退: 已禁用** — 运维显式关掉了

## 团队使用建议

本机模型有 GPU 加速、其他用户机器没有 GPU 的情况怎么办?

**不用做什么。** 设计就是 fail-safe:

1. 其他用户主路径走 **同一个云端 rerank API**(从 Settings → Rerank 模型配置 配的),跟你完全一样
2. 当云端 rerank API 抖动时:
   - 他们机器**没装权重 / 没 GPU** → 本地回退报"不可用" → 用 hybrid_score 静态兜底排序(P1 已实测,质量退化但不崩溃)
   - 他们装了权重 → 本地回退在 CPU 跑(慢但可用,3 秒一批)
3. 任何时候都不会**因为 rerank 失败而让 chat 失败**

| 场景 | 建议 |
|---|---|
| **生产环境云端 API 稳定** | 不强制其他用户装本地模型,接受 P1 兜底排序 |
| **网络不稳/内网** | 使用私有 HF mirror 或提前同步 HF 缓存目录 |
| **追求质量一致** | 团队统一一个 rerank 云端账号 + 同款本地权重作冗余 |

## 排错

**Q: chip 一直说"本地回退: 不可用",但我已经下载了权重**
- 检查 HF 缓存目录是否对:`C:\Users\<you>\.cache\huggingface\hub\models--<org>--<name>\snapshots\<commit>\`
- 该 snapshot 里要有 `config.json` + `model.safetensors` (或 `pytorch_model.bin`)
- chip 显示的 `hf_cache_dir` 字段就是助手实际查的地方

**Q: chip 说"可用"但回退时报错**
- 跑 `python -c "from local_rerank_adapter import score_pairs; print(score_pairs('test', ['a','b']))"` 在终端复现
- 后端日志找 `local_rerank_adapter:` 前缀的 ERROR 行

**Q: 我想完全关掉本地回退**
- 设 `LOCAL_RERANK_DISABLED=1`,chip 会变⚫,云端 API 失败时直接退 hybrid_score 排序

**Q: 我想强制用 CPU(GPU 已被别的服务占了)**
- 设 `LOCAL_RERANK_DEVICE=cpu`,chip 会显示 `device_source: env_override`

## 接口契约

| 文件 | 作用 |
|---|---|
| `literature_assistant/core/local_rerank_adapter.py` | 适配器主体。`is_available()` / `get_status()` / `score_pairs()` / `rerank_dicts()` 公共 API |
| `literature_assistant/core/local_rerank_server.py` | (可选)把适配器包成 127.0.0.1:7997 HTTP server,让其他进程也能用 |
| `literature_assistant/core/routers/rerank_config_router.py` | `/api/rerank/local-status` endpoint 给前端 chip 用 |
| `frontend/src/pages/Settings.tsx` `LocalRerankFallbackChip` | UI 状态指示 |

换模型只需要改 env 变量,**不需要改代码**。如果要支持非 HuggingFace 的 rerank 引擎(比如 Vespa rerank、Pinecone 等),那是适配器层改动,不在本文档范围。
