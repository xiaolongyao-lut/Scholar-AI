# 异步数据库迁移评估与隔离验证报告

**执行时间**: 2026-04-12
**状态**: 🟢 **已完成 (Deferred & Assessed)**
**操作结论**: 暂不融合全局异步（No-Go），但成功建立局部 PoC 探索潜力。

---

## 1. 当前环境结构与使用面分析

### 1.1 同步状态依赖点
目前核心的数据驱动架构为两块依赖 SQLite 持久化的模块：
*   **`canonical_event_store.py` (CanonicalEventStore)**
*   **`memory_fact_store.py` (MemoryFactStore)**

在整个恢复执行引擎 (Recovery Execution Engine) 和自动驾驶机制 (Autopilot) 中，这两个基础仓库正被频繁、同步式（Synchronous）地跨层调用。
经过 `grep` 分析，直接产生依赖关系的调用文件高达十余个，包括：
- `recovery_recommendation_engine.py` （被触发20余次）
- `recovery_autopilot_control_plane.py` （每个状态流转事件全部写库）
- `recovery_api.py` / `recovery_cli.py` / `recovery_console.py` （全部作为客户端接口同步获取状态）

### 1.2 阻塞情况与瓶颈评估
- **SQLite的自身特性**：当前底层 Python 原生驱动库 `sqlite3` 为同步。即使采用 `aiosqlite` 异步演进，它也仅仅是在内存中基于内部连接对象利用基于后端的线程池（threadpool）把堵塞从主要 `event loop` 中搬迁至次级线程处理。SQLite 最底层的数据库本身仍然需要独占式文件锁机制 (File locking) ，并不能享受类似于 Postgres / Redis 级别的真正的 I/O 并发福利。
- **系统时间延迟开销**：当下的引擎时间主要损耗发生在复杂的 R-Layer 知识树索引与 G-Layer LLM 大模型推理环节（通常约 10~15秒左右），相比较而言，SQLite 单文件层面的几毫秒耗时所占据的时间池接近于误差范围。

---

## 2. 转换成本收益核算 (ROI)

| 指标维度 | 改版预期后果 (Cost & Impact) | 预期获得收益 (Benefit) |
|---|---|---|
| **代码传染率** | 极高风险。一旦底层使用 `await aiosqlite`，那么上方所有如 `generate_recommendations` , `AutopilotControlPlane.enable()` 等原定义为 `def` 的函数必须全体被动强制传染升级为 `async def`。 | 可以释放出当前执行主线程事件循环以服务更高并发连接数（针对长连接）。 |
| **测试套件损害** | 目前拥有 `634 Passed` 的极其健壮的全量测试。全局迁移必须全面改写原有 Pytest 中涉及的所有 Mocking 处理（引入 `pytest.mark.asyncio` 等大量的重构适配）。 | 对本地开发有少量性能改善，但很容易带回不可期的资源竞争或事件竞态异常。 |
| **性能瓶颈** | 现有的性能天花板卡在了下游 API（大语言模型分析响应等外部瓶颈）。 | 在没有完全从 SQLite 升级至专门的高速缓冲引擎前无明显 I/O IOPS 释放感。 |

**结论**：迁移引发的代价远大于理论优势。

---

## 3. 最终判定与架构建议

**强制拒绝引入底层破坏 (STRONG REFUSAL)**。
鉴于该 `Modular-Pipeline-Script` 已步入生产级验证后期并形成了不可打破的同步数据契约，在此刻通过“只为了全套基于 `async` 流畅而引入异步”不符合工程的防御性迭代原则。
因此我们保持现有的**可靠且快速的同步实现** (`sync CanonicalEventStore / HarnessStore`)。

同时，出于技术预研目的，我们已经在不污染任何项目前提下，将一个基于 `aiosqlite` 的隔离 PoC 代码验证（`poc_async_event_store.py`）落地于项目中，后续如果更换驱动级关系型数据库，则可按照该沙盒版本继续进化。
