# 2026-04-27 会话执行参考（学习/参考库吸收到 embedding provider 修复）

## 用途

这份文件用于把本次长会话中**对后续实现仍有指导价值**的思考、执行、证据和未完项沉淀到仓库内，供后续继续更新与复用。

目标不是写一份“漂亮总结”，而是写一份**下一次还能接着干**的执行参考。

建议后续维护方式：

- 不重写历史结论，优先追加新的 `Facts / Decisions / Open / Next`。
- 每次继续推进时，在“本轮 live log 回填”里追加新条目。
- 若后续事实推翻旧判断，保留旧判断并显式写明“已被更新/作废”。

## 证据来源与说明

本文件综合以下证据来源整理：

- 会话 transcript：
  `c:\Users\xiao\AppData\Roaming\Code\User\workspaceStorage\a98aeb7104fa06732d96503087c1f036\GitHub.copilot-chat\transcripts\892680ab-5dba-4bce-b88a-5071f3dcd0b1.jsonl`
- 主计划文件：
  `.kilo/plans/2026-04-27-full-project-build-master-plan.md`
- 当前会话压缩摘要（conversation summary）
- 相关 orchestration log / test 结果 / 代码文件本体

说明：

- 用户提到的“从让你学习文件夹项目开始”这一短语，没有在 transcript 文本检索中直接命中。
- 因此本文件的早期时间线，采用 **transcript 可见锚点 + 当前压缩摘要 + master plan 回填** 的方式整理。
- 所有涉及 `.env` 的部分只记录**类型判断、字段语义和行为结论**，不重复暴露 secret。

## 用户关键指令（按影响力整理）

这些指令决定了整场会话的执行方式，应视为本轮最重要的上层约束：

1. **全项目详细规划 + AI 先自决策再集中问用户**
   - 用户意图：不要碎片式确认，要让 AI 先收敛方案。
2. **允许使用 env 中现有 key，但不能泄露 secret**
   - 用户后续进一步说明：重点识别 key 的真实类型，而不是看前缀。
3. **跑完自动下一步，不要等用户确认**
   - 这是本轮最明确的 workflow 偏好之一。
4. **rerank 必须加入**
   - 不是短期默认是否启用的问题，而是架构地位问题：必须保留为一等能力。
5. **把这次的 API 识别写进 `.env` 备注里**
   - 包括把误写成 rerank 的 embedding 段改正。
6. **顺手把那两个仍直连 embedding 的地方改掉**
   - 已锁定为：`layers/semantic_router.py` 与 `layers/r_layer_hybrid_retriever.py`
7. **把本轮对话与执行过程沉淀成可持续更新的参考文件**
   - 本文件即为对该要求的回应。

## 时间线总览

### Phase A（2026-04-22 起始锚点）：Gate B / team / long-run 能力讨论

根据 transcript 开头可见锚点，本轮会话早期集中在：

- Gate B trusted inputs 阻塞判断
- team 是否应该自己解决 blocker
- 多 agent 长跑默认逻辑如何从项目特定 prompt 抽象成团队能力

早期可见转折包括：

1. 先针对 Gate B trusted inputs 做只读核查。
2. 用户不满意“所有 blocker 都回到用户决策”的设计。
3. 会话随后转向：
   - 多 agent 默认自治逻辑
   - blocker 分类与 requirement-pool 职责
   - 团队能力应是团队自己的设定，而不是当前项目 prompt 的副产物

这部分讨论的重要产物不是具体代码，而是**执行哲学**：

- blocker 需要先自治判断，不应默认上抛用户；
- 长跑能力应沉淀为可迁移的团队内核；
- requirement-pool 不是一切不确定项的垃圾桶。

### Phase B：学习/吸收 `github/` 参考库与全项目推进框架建立

会话中段从单点阻塞处理，扩展到“学习文件夹/参考库/下载源码库”的吸收与归档，最终在 master plan 中形成了：

- `github/INDEX.md`
- `github/RAG_TOLF_REFERENCE_MAP.md`
- `github/project-notes/*`

并在 master plan 中明确：

- `github/` 是外部参考源码库，不是当前运行路径；
- `.github/` 是 Copilot/Squad/skills/workflows 配置资产；
- TOLF 是最终方向，但本轮不直接并入默认主链。

这一步的重要意义：

- 把“先看外部仓库学什么”从临时行为，升格为可追溯参考地图；
- 为后续 TOLF / GraphRAG / representative rerank / academic workflow 提供外部机制来源。

### Phase C：全项目 master plan 固化

主计划文件 `.kilo/plans/2026-04-27-full-project-build-master-plan.md` 成为本轮后半段的 authoritative plan。

它固化了：

- 预决策矩阵
- 可回填执行矩阵
- Wave 路线图
- Reranker 必须是一等能力的纠偏声明
- 当前已完成 / 受阻 / 待执行任务

其中与当前仍直接相关的状态有：

- `TASK-010` 已完成：eval manifest 模板与输出隔离
- `TASK-011` 受阻：`--no-rerank` control 因 embedding 余额/凭证问题阻塞
- `TASK-040` 已完成：前端 retrieval / scan / OpenAPI / build 闭环
- `TASK-150` 已完成：TOLF text-only pilot 输入输出
- `TASK-151` 进行中：TOLF ablation 仍待扩 richer mask variants
- `TASK-130` 受阻：reranker matrix 执行前置问题未完全清空

### Phase D：runtime / frontend / eval / TOLF 多路收口

在 master plan 落地后，会话已完成一大段 focused implementation：

1. **Session runtime / persistence / contract 闭环**
   - `routers/runtime_router.py`
   - `writing_runtime.py`
   - `repositories/writing_runtime_repository.py`
   - 对应 focused tests 通过

2. **Frontend retrievalTopK / scan / OpenAPI / build 闭环**
   - `frontend/src/pages/Workbench.tsx`
   - `frontend/src/pages/Settings.tsx`
   - `frontend/src/pages/KnowledgeBase.tsx`
   - `frontend/src/services/settingsStore.ts`
   - `npm run generate:openapi`
   - `npm run build`

3. **Eval manifest 与 artifact audit**
   - `artifacts/eval_audit/run_manifest_template.json`
   - `artifacts/eval_audit/RUN_MANIFEST_GUIDE.md`

4. **TOLF text-only pilot 与 2×2 ablation 基础**
   - `eval_tolf_text_pilot.py`
   - `artifacts/tolf/text_pilot_sample_report.json`
   - `tests/test_tolf_text_pilot.py`

### Phase E：embedding / provider 根因分析与主链修复

这是本轮后半段最重要的技术问题之一。

#### 现象

- `.env` 中同类变量大量重复，标准 dotenv 只保留最后一项。
- 某些 credential 变量名写成 `RERANK_*`，但语义实际上是 embedding。
- 多个公益站 / 中转站不是官方独占端点，而是 New API 风格统一网关。
- 某些 provider（例如 DashScope multimodal embedding）并不等价于当前 text-only embedding 链。

#### 根因

真正的问题不是“key 长什么样”，而是：

- **credential 类型必须按 `base URL + model 语义` 判断**；
- 不能靠 key 前缀、变量名前缀、域名名义来猜；
- grouped credential（三元组 key/base/model）比 flat env 更接近用户真实意图；
- import-time side effects 会污染测试与运行时。

#### 已完成修复（本轮之前已落地）

- `key_pool.py`
  - 新增/强化：`infer_credential_category()`、`_classify_var()`、`parse_env_pools()`
  - `KeyPool.try_call_async()` 支持异步 cooldown / failover
- `runtime_env.py`
  - grouped credential 优先
  - candidate-specific probe
  - explicit base/model 尊重调用方输入
- `chunk_vector_store.py`
  - dense build/query 已走 embedding failover pool
- `eval_retrieval_runtime.py`
  - 删除 import-time env mutation，避免测试串跑污染

#### 已完成验证（本轮之前已通过）

- `pytest tests/test_key_pool.py tests/test_embedding_provider_resolution.py tests/test_embedding_batch_chunking.py -q`
- `pytest tests/test_embedding_key_probe.py tests/test_dense_rrf_retrieval.py -q`
- `pytest tests/test_eval_runtime.py -q`

### Phase F（当前轮新增）：修 `.env`、补齐两个直连 embedding 消费者、写执行参考

这是本文件创建时所在的当前阶段。

本轮新增工作分三块：

#### F1. `.env` 备注与字段语义回填

已完成：

- 在 `.env` 顶部写入 API 识别备注：
  - 类型按 `base URL + model` 识别
  - New API 风格统一网关不按域名推断类别
  - 失败自动冷却并切换 credential
- DashScope embedding 段明确标注为：
  - **multimodal embedding**
  - 当前 text-only embedding 链不能直接替换
- 回答模型段补充备注：
  - 这些公益站多为统一网关
  - 当前段只登记已验证可用的回答模型
- 将 SiliconFlow 那段误写成 `RERANK_*` 的 embedding 配置修正为：
  - `SILICONFLOW_EMBEDDING_API_KEY`
  - `SILICONFLOW_EMBEDDING_BASE_URL`
  - `SILICONFLOW_EMBEDDING_MODEL`
  - `EMBED_CONCURRENCY`

#### F2. 两个仍直连 embedding 的模块接入 failover

已完成：

1. `layers/semantic_router.py`
   - 引入 `resolve_embedding_config()` 统一解析
   - 引入 `build_embedding_failover_pool()` 构建 embedding credential pool
   - 将单凭证 HTTP 调用拆分为：
     - `_call_embedding_api_once()`
     - `_call_embedding_api()`（负责 credential failover）
   - 失败时走 `KeyPool.try_call_async()` 轮换，并对失败凭证冷却

2. `layers/r_layer_hybrid_retriever.py`
   - `ContextAwareRetriever` 新增 embedding failover pool
   - 将 `_embed_query()` 拆分为：
     - `_embed_query_once()`
     - `_embed_query()`（负责 provider-aware failover）
   - 失败时同样冷却并切换下一凭证

3. `runtime_env.py`
   - 新增 `build_embedding_failover_pool()` 作为复用 helper

4. `chunk_vector_store.py`
   - 保持既有行为不变，同时保留对旧测试 monkeypatch 入口的兼容

#### F3. 新增 focused regression tests

已完成：

- 新增 `tests/test_embedding_consumer_failover.py`
  - 验证 `ContextAwareRetriever` 在首个 embedding credential 失败后切换到下一个
  - 验证 `SemanticRouter` 在首个 embedding credential 失败后切换到下一个
  - 验证失败 credential 在冷却期内不会被重复尝试

#### F4. 本轮验证结果

本轮 focused pytest 已通过：

- `pytest tests/test_embedding_consumer_failover.py tests/test_llm_provider_routing.py tests/test_key_pool.py tests/test_embedding_provider_resolution.py tests/test_embedding_batch_chunking.py tests/test_embedding_key_probe.py tests/test_dense_rrf_retrieval.py tests/test_eval_runtime.py -q`
- 结果：`87 passed in 27.96s`

## 当前代码事实（截至本文件本轮更新）

### 已经不再直连单 provider 的 embedding 消费者

- `chunk_vector_store.py`
- `layers/semantic_router.py`
- `layers/r_layer_hybrid_retriever.py`

### 仍需持续注意的 provider 约束

1. **DashScope multimodal embedding**
   - 不是当前 text-only chain 的直接替代
   - 若要真正接入，需要 provider-specific adapter

2. **New API 风格统一网关**
   - 域名本身不代表用途
   - 需要按 endpoint + model 识别

3. **rerank 架构地位**
   - 必须保留为一等能力
   - 即使短期默认 `--no-rerank`，也不能等同于移除 reranker

## 本轮修改文件清单

### 已修改

- `.env`
- `runtime_env.py`
- `chunk_vector_store.py`
- `layers/semantic_router.py`
- `layers/r_layer_hybrid_retriever.py`

### 已新增

- `tests/test_embedding_consumer_failover.py`
- `.kilo/plans/2026-04-27-conversation-execution-reference.md`（本文件）

## Facts / Decisions / Open / Next

### Facts

- embedding credential 类型判断必须按 `base URL + model`，不是按 key 前缀或域名。
- `semantic_router` 和 `hybrid_retriever` 之前都仍是单 provider 直连，现在已接入 failover。
- `.env` 中存在用户人为误写的“embedding 写成 rerank”的段，已修正为 embedding 变量名。
- consumer-side failover focused tests 已通过。
- `TASK-011` 的 no-rerank control rerun 已成功产出完整 sidecar：30 queries，`Recall@5 = 0.6667`，`MRR = 0.6667`，`p95 = 844.1ms`。

### Decisions

- `.env` 只记录识别备注与字段语义，不在文档或回复中复制 secret。
- `runtime_env.py` 增加可复用 helper，消费者侧采用同一套 embedding pool 语义。
- `chunk_vector_store.py` 保留兼容入口，避免破坏已有测试和 monkeypatch 习惯。
- 本文件放在 `.kilo/plans/`，因为该目录已是本仓当前 active planning / execution reference 主位置。

### Open

1. `TASK-012`：env 现货 reranker control matrix 仍待真正跑进同一 trusted slice（当前只有 explicit mini-canary / inventory 证据）。
2. `TASK-013`：默认并发 vs `50` 并发 smoke 仍待执行。
3. `TASK-014`：其余 DashScope 可用模型（`qwen3-vl-rerank`、`gte-rerank-v2`）的同 slice 对照仍待执行。
4. `TASK-151`：TOLF richer mask variants 仍待扩展。
5. DashScope multimodal embedding 若未来要进入主链，需要单独 provider adapter，不应偷懒复用 text-only path。

### Next

1. 以同一 query/qrels slice + unique output path 推进 `TASK-012` 的 env 现货 reranker matrix，优先 `qwen3-rerank`。
2. 在 pinned model 条件下比较默认并发与 `50` 并发，然后按同一 discipline 扩到 `qwen3-vl-rerank` 与 `gte-rerank-v2`。
3. 每次 reranker run 结束后，把 command、output path、metrics / progress / per-query / trace 结果回填到：
   - 本文件
   - master plan
   - 对应 orchestration log

## 本轮 live log 回填

- [已完成] 读取并确认两处仍直连 embedding 的模块：`layers/semantic_router.py`、`layers/r_layer_hybrid_retriever.py`
- [已完成] 读取 `.env`、`runtime_env.py`、`chunk_vector_store.py`、`tests/test_llm_provider_routing.py`，确认当前主链与遗留直连点的差异
- [已完成] 新增 `runtime_env.build_embedding_failover_pool()`
- [已完成] 为 `SemanticRouter` 接入 embedding failover + cooldown
- [已完成] 为 `ContextAwareRetriever` 接入 embedding failover + cooldown
- [已完成] 新增 focused test：`tests/test_embedding_consumer_failover.py`
- [已完成] 跑 embedding / runtime 相关 focused pytest，结果 `87 passed`
- [已完成] 将 API 识别备注和误写变量修正回填到 `.env`
- [已完成] 以 fresh manifest `artifacts/eval_audit/manifests/20260427-canary30-aligned-no_rerank-rerun1.json` 重跑 `TASK-011`
- [已完成] 产出完整 control sidecar：metrics / progress / per_query / rerank_trace / resume_guard
- [已完成] control 结果：30 queries，`Recall@5 = 0.6667`，`MRR = 0.6667`，`avg_latency_ms = 781.61`，`p95 = 844.1ms`
- [已完成] 审核 `20260428-canary30-aligned-rerank8b-control1`，确认其不是 decision-grade evidence：`rerank_api_* = 0`，trace 仍写出 `rerank_fallback = false`，且 `rerank_score` 逐项镜像 `rrf_score`
- [已完成] 修复 rerank fallback observability：`reranker_client._apply_fallback()` 现显式打 `rerank_fallback`，`eval_retrieval_runtime._record_rerank_trace()` 现会把内部 fallback 提升到顶层 trace 并序列化 warning
- [已完成] 跑 targeted pytest：`tests/test_rerank_short_circuit_and_budget.py tests/test_eval_runtime.py -q`，结果 `40 passed in 16.74s`
- [已完成] 修复 rerank credential resolution / request-time failover：`reranker_client` 现先读取 `key_pool` grouped `(key, base_url, model)` candidates，再在真实请求失败时自动冷却当前 credential 并切到下一个
- [已完成] 跑 focused pytest：`tests/test_reranker.py tests/test_rerank_short_circuit_and_budget.py tests/test_eval_runtime.py -q`，结果 `64 passed in 24.01s`
- [已完成] 跑 consumer-side 回归：`tests/test_llm_provider_routing.py tests/test_embedding_consumer_failover.py -q`，结果 `5 passed in 35.56s`
- [已完成] 做 rerank live credential preflight：当前根 `.env` 识别出 5 个 unique rerank `(base_url, model)` pair / 8 条 credential，`Qwen/Qwen3-Reranker-8B` 不在其中；现有 rerank pool probe 全失败，且显式 8B probe 也失败
- [阻塞中] `TASK-012` fresh 8B rerun：代码路径已修通，但 live credential 仍不可用，暂不能生成有效 8B control evidence

### 更新：2026-04-28 8B invalidation + rerank fallback observability fix

- Facts:
  - `output/20260428-canary30-aligned-rerank8b-control1.metrics.json` 显示 `Recall@5 = 0.6667`、`MRR = 0.6667`，但 `rerank_api_avg_ms = 0.0`、`rerank_api_p95_ms = 0.0`。
  - `output/20260428-canary30-aligned-rerank8b-control1.rerank_trace.jsonl` 中已审阅行显示 `requested_use_rerank = true`、`use_rerank = true`、`rerank_fallback = false`，但 `returned_hits[*].rerank_score` 镜像 `rrf_score`，符合静默 fallback 而非真实 rerank。
  - 根因之一已确定：`reranker_client._apply_fallback()` 之前不写 `rerank_fallback`，导致内部 fallback 会被 trace 误记成正常 rerank。
  - 当前 `eval_retrieval_runtime.py` 仍保留 guarded `load_dotenv()` 路径，因此“import-time env handling 是否仍参与这次失效”目前仍是 open，而不是已被彻底排除。
- Decisions:
  - `20260428-canary30-aligned-rerank8b-control1` 被正式判为 invalid，不用于默认链路或模型优选结论。
  - 保留 invalid artifacts 作为审计证据，不删除。
  - 先修 trace/fallback observability，再做 fresh rerun；不在 silent-fallback 状态下继续 4B/BGE。
- Open:
  - 仍需在将要真正启动 rerun 的同一环境里做 embedding + rerank credential preflight，确认不是“有配置、运行时却没打到 provider”。
  - `TASK-011` 的 control baseline 已可作为控制组使用，但 dense/embedding availability 是否完全符合预期，仍值得在下一个 preflight 一并复核。
- Next:
  - 更新 manifest / master plan / orchestration log 为 invalidated state。
  - 用 fresh output paths 重新跑 8B control，要求真实 rerank timing 或显式 fallback=true + reviewed reason。
- Evidence:
  - `.squad/orchestration-log/copilot-2026-04-28-rerank8b-control1-invalid.md`
  - `output/20260428-canary30-aligned-rerank8b-control1.metrics.json`
  - `output/20260428-canary30-aligned-rerank8b-control1.rerank_trace.jsonl`
  - `reranker_client.py`
  - `eval_retrieval_runtime.py`
  - `tests/test_rerank_short_circuit_and_budget.py`
  - `tests/test_eval_runtime.py`

### 更新：2026-04-28 rerank key-pool fix + live credential blocker confirmed

- Facts:
  - `reranker_client.py` 现新增 grouped rerank candidate 解析：优先读取 `key_pool` 中按 `(api_key, base_url, model)` 成组保留的 rerank credentials，而不是只看被压扁后的 flat env 默认值。
  - `reranker_client.rerank_async()` 现支持 request-time failover：首个 rerank credential 请求失败时，会冷却当前 credential 并尝试下一个，而不是直接静默 fallback 到原始 RRF 顺序。
  - 新增回归测试：`tests/test_reranker.py::test_resolve_rerank_config_uses_key_pool_pairs_from_dotenv` 与 `tests/test_reranker.py::test_rerank_async_fails_over_to_next_key_pool_credential`。
  - focused pytest 已通过：
    - `tests/test_reranker.py tests/test_rerank_short_circuit_and_budget.py tests/test_eval_runtime.py -q` → `64 passed in 24.01s`
    - `tests/test_llm_provider_routing.py tests/test_embedding_consumer_failover.py -q` → `5 passed in 35.56s`
  - 最新 live preflight（脱敏）显示：当前根 `.env` 共有 5 个 unique rerank `(base_url, model)` pair：`BAAI/bge-reranker-v2-m3`、`netease-youdao/bce-reranker-base_v1`、`qwen3-rerank`、`qwen3-vl-rerank`、`gte-rerank-v2`；没有 `Qwen/Qwen3-Reranker-8B`。
  - 对当前根 `.env` 中所有 rerank credential 做 probe，成功数为 `0`；进一步对现有 SiliconFlow rerank key 显式指定 `Qwen/Qwen3-Reranker-8B` 再 probe，结果仍为 `false`。
- Decisions:
  - 将 `TASK-012` 与 `TASK-130` 从“代码修复进行中”切换为“live credential blocker”。
  - 不在当前 credential 状态下继续 4B / BGE reranker matrix；先解决 working rerank credential，避免再次生产“命令跑完但证据无效”的假阳性。
  - 保留此次代码修复与 credential preflight 结论，作为后续恢复 8B control 的前置条件记录。
- Open:
  - 需要一个可工作的 rerank credential / model 组合；如果仍坚持 8B control，则至少需要恢复或提供能够通过 `Qwen/Qwen3-Reranker-8B` probe 的 SiliconFlow 配置。
  - 若用户决定放弃 8B control，仍需要新的授权/决策来改写 Wave 4 的 control 定义，而不是默认把 4B/BGE 提前顶上去。
- Next:
  - 等待用户恢复 / 提供 working rerank credential，或明确改写 reranker matrix 的 control 目标。
  - credential 恢复后，先重做 live preflight，再创建 fresh manifest + fresh outputs 重跑 `TASK-012`。
- Evidence:
  - `.squad/orchestration-log/copilot-2026-04-28-rerank-keypool-fix-credential-block.md`
  - `reranker_client.py`
  - `tests/test_reranker.py`
  - `tests/test_rerank_short_circuit_and_budget.py`
  - `tests/test_eval_runtime.py`
  - `tests/test_llm_provider_routing.py`
  - `tests/test_embedding_consumer_failover.py`

### 更新：2026-04-28 DashScope probe payload 修复 + env 现货 rerank inventory

- Facts:
  - `_probe_rerank_key()` 已修复为 provider-aware：DashScope 现在发送 `input.query` / `input.documents` / `parameters.top_n` / `parameters.return_documents=false`，不再误发 SiliconFlow 风格 flat payload。
  - 新增回归测试：`tests/test_reranker.py::test_probe_rerank_key_uses_dashscope_payload`。
  - focused regression 已通过：`c:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/.venv-1/Scripts/python.exe -m pytest tests/test_reranker.py -q` → `25 passed`。
  - 用显式 `(api_key, base_url, model)` 做 live inventory 后，当前 root `.env` 中可直接成功请求的 rerank 现货为：DashScope `qwen3-vl-rerank`、`qwen3-rerank`、`gte-rerank-v2`；三者均 `probe_ok=true` 且 `request_ok=true`。
  - 同轮 explicit inventory 也确认：SiliconFlow `BAAI/bge-reranker-v2-m3` 与 `netease-youdao/bce-reranker-base_v1` 仍是 `403 insufficient balance`，因此当前不应混入 active matrix。
  - 并发现状：`eval_retrieval_runtime.py` 默认 `DEFAULT_QUERY_CONCURRENCY = 8`、`DEFAULT_RERANK_CONCURRENCY = 3`；root `.env` 仅显式设置 `EMBED_CONCURRENCY=16`；用户明确提到可测试 `50` 并发。
  - 新增 direct API `50` 并发 smoke：对 DashScope `qwen3-rerank` 进行显式 pin、无重试并发 fanout，结果 `50/50` 成功，`latency_ms_p50=1276.48`、`latency_ms_p95=1318.93`、`total_wall_ms=1352.07`。
  - 与之相对，runtime-level `reranker_client.rerank_async()` 的 `50` 并发显式 pin smoke 出现重复 `503` 并拖长，说明问题更像是当前 client lifecycle / connection churn / retry path，而不是 provider 本身在 `50` 并发下不可用。
  - 新增 `16 / 32 / 48` 分级 smoke：provider-direct 在 fresh process 下 `16/16`、`32/32`、`48/48` 全部成功；其中 isolated `48` 为 `latency_ms_p95=1232.93`、`total_wall_ms=1369.66`。
  - 对应 runtime-level `rerank_async()`：`16/16` 成功，但 `latency_ms_p95=6487.59`、`total_wall_ms=19629.09`；isolated `32` 与 `48` 在每请求 `20s` 外层限时下均整批超时（分别 `32/32`、`48/48` timeout）。
  - 先前组合脚本里出现的 `direct 48 -> ConnectTimeout` 已被 fresh-process isolated rerun 推翻，应视为前序 runtime timeout/cancellation 后的污染证据，而非 provider 容量结论。
- Decisions:
  - “当前 live rerank credential 全部不可用”这一旧判断已被更新：应改写为“DashScope 三个模型可用，SiliconFlow 两个模型余额阻塞”。
  - Wave 4 的 active goal 从“恢复 8B control”改为“env 现货模型 + 并发矩阵”；8B invalid 保留为历史审计，不再作为当前推进前置阻塞。
  - 后续 rerank eval 必须显式 pin `(api_key, base_url, model)`，避免 request-time failover 把一个模型的 run 污染成另一个模型的结果。
  - `50` 并发结论要区分两层：provider-direct 已验证健康；runtime-level 还需通过连接复用或更接近正式 eval 路径的方式复核，不能把一次 stalled smoke 直接当作 provider cap 结论。
  - 当前 runtime safe zone 暂定为 `<=16`；`32` 与 `48` 在现有 `reranker_client` 路径下不应进入正式 canary/eval，除非先处理连接复用 / client lifecycle。
- Open:
  - 还没有把 `qwen3-rerank` / `qwen3-vl-rerank` / `gte-rerank-v2` 真正跑进 canary eval matrix；当前只有 explicit mini-canary / inventory 证据。
  - 若 `eval_retrieval_runtime.py` 仍缺少 CLI 级 model pinning，则需要通过隔离进程环境或补 CLI/runtime pinning 支持，避免 matrix run 被 fallback 污染。
  - `reranker_client.py` 当前 remote invoke 每次都新建 `httpx.AsyncClient(timeout=45.0)`；若要把 `50` 并发作为正式 runtime claim，需要确认这一路径是否需要 client reuse / pooling。
  - 若后续要把并发从 `16` 再往上抬，建议先做 runtime-level 连接复用实验，再重新跑 `32 / 48 / 50`，否则会继续被当前 client lifecycle 卡住。
- Next:
  - 先对 `qwen3-rerank` 跑 pinned canary，但 runtime 并发先收敛到 `16`，不要直接上 `32+`。
  - 稳定后把同一 discipline 扩到 `qwen3-vl-rerank` 与 `gte-rerank-v2`。
  - SiliconFlow 模型在余额/credential preflight 通过前，不进入 active matrix。
  - 若后续仍要把 `32+` 或 `50` 并发写入正式 runtime 结论，优先检查 `reranker_client` 的连接复用策略，再决定是否需要小型实现修补。
- Evidence:
  - `.squad/orchestration-log/copilot-2026-04-28-rerank-probe-fix-env-matrix.md`
  - `.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-concurrency50-smoke.md`
  - `.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-concurrency16-32-48-matrix.md`
  - `reranker_client.py`
  - `tests/test_reranker.py`
  - `eval_retrieval_runtime.py`

## 后续更新规范（给未来会话）

后续若继续使用本文件，建议每轮追加以下模板：

```text
### 更新：YYYY-MM-DD HH:MM（简要标题）
- Facts:
- Decisions:
- Open:
- Next:
- Evidence:
```

同时同步更新：

- `.kilo/plans/2026-04-27-full-project-build-master-plan.md`
- 对应 `.squad/orchestration-log/*.md`

避免出现“代码已经变了，但参考文件还停在旧世界线”的情况。

### 更新：2026-04-28 03:20（qwen3-rerank c16 rerun + embedding live fix）

- Facts:
  - `chunk_vector_store.py` 已补齐两处 live 兼容修复：所有 embedding 路径统一把超长向量归一到固定 `1024` 维；DashScope multimodal embedding batch 自动 cap 到 `20`，避免 provider 400 `contents count` 错误。
  - 新增/扩充回归测试后，embedding/rerank/runtime wider suite 现为 `97 passed in 53.58s`。
  - 以 `artifacts/eval_audit/manifests/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.json` 重跑 pinned `qwen3-rerank` canary 成功；输出 `metrics/progress/per_query/rerank_trace/resume_guard/run.log` 全部产出。
  - 运行结果：`Recall@5=0.0667`、`MRR=0.0517`、`avg_latency_ms=20801.14`、`p95_latency_ms=30691.44`、`rerank_api_avg_ms=2958.75`。
  - `rerank_trace.jsonl` 共 `30` 条，无 `rerank_fallback=true`，无 `rerank_warning`；`resume_guard` 中 `rerank_model=qwen3-rerank`。
- Decisions:
  - 原始 manifest `20260428-canary30-aligned-qwen3-rerank-c16-canary1.json` 标记为 `blocked`，原因是当时 runtime 尚未支持 DashScope multimodal embedding 契约。
  - rerun manifest 标记为 `completed`，但只作为 **provisional** 证据，不据此切换默认链路；当前质量明显低于 `no-rerank` control。
  - rerank pinning 采用“只收窄 rerank candidate resolution”的 wrapper，不再对 embedding key-pool 做全局抑制。
- Open:
  - 当前 run 的 embedding 实际由 DashScope multimodal failover 产出，但 provenance / cache model 名仍沿用默认 `Qwen/Qwen3-Embedding-8B` 语义；比较 `qwen3-rerank` 与旧 `no-rerank` baseline 时，需要额外注意可比性。
  - 若继续 Wave 4 matrix，最好先补一个“当前 embedding 语义下”的 no-rerank 对照，或显式把 embedding 也 pin 住并写入 provenance。
  - `qwen3-vl-rerank` 与 `gte-rerank-v2` 仍未进入同 slice 正式矩阵。
- Next:
  - 先决定/实现 embedding 可比性方案（补 control 或补 provenance/pin），再继续 DashScope 其余 reranker 候选。
  - 若继续并发抬升到 `32+`，仍需先处理 runtime-level client reuse / pooling。
- Evidence:
  - `.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-c16-canary-rerun-success.md`
  - `artifacts/eval_audit/manifests/20260428-canary30-aligned-qwen3-rerank-c16-canary1.json`
  - `artifacts/eval_audit/manifests/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.json`
  - `output/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.metrics.json`
  - `output/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.run.log`

### 更新：2026-04-28 03:30（current-embed no-rerank control）

- Facts:
  - 新建 fresh control manifest：`artifacts/eval_audit/manifests/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.json`。
  - 该 control 在当前代码与当前 embedding failover 语义下成功完成，输出 `metrics/progress/per_query/rerank_trace/resume_guard/run.log` 全产出。
  - 结果为：`Recall@5=0.6667`、`MRR=0.6667`、`avg_latency_ms=1148.37`、`p95_latency_ms=1264.32`。
  - 与同条件 `qwen3-rerank` rerun 相比，当前 control 明显更优：`Recall@5 +0.6000`、`MRR +0.6150`，且平均延迟约快 `18x`。
- Decisions:
  - 当前证据下，`qwen3-rerank` 不再作为短期默认候选；`no-rerank` 继续保留为当前基线。
  - `qwen3-rerank` 结果保留为有效但负向的 provisional matrix evidence，不再需要额外补同 embedding 语义 control。
- Open:
  - 若继续 Wave 4，下一批更值得跑的是 `qwen3-vl-rerank` 与 `gte-rerank-v2`，看是否有比 no-rerank 更好的 env 现货候选。
  - embedding provenance 仍未显式记录实际 failover provider/model，这个可观察性缺口依旧存在。
- Next:
  - 保持 `no-rerank` 为当前短期默认基线。
  - 若继续 matrix，直接推进 `qwen3-vl-rerank` / `gte-rerank-v2`。
- Evidence:
  - `.squad/orchestration-log/copilot-2026-04-28-no-rerank-current-embed-control.md`
  - `artifacts/eval_audit/manifests/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.json`
  - `output/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.metrics.json`
  - `output/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.run.log`
