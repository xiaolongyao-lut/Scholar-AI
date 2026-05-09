# Squad 长跑硬化 — 执行报告

> 日期：2026-04-26
> 执行者：Claude（用户授权 "你改你自己的squad就行。开始改"）
> 范围：仅改 Claude 自己的 squad（`.claude_squad/`、`.squad/tools/`、`CLAUDE.md`、`docs/Claude/`）。`my-project/`、`.copilot/` 未触碰。
> 关联：v4 §11.5 事故索引第 1–4 起（pool 截断、dup-storm、blackout-saga、dispatch-volume）。

---

## Facts（已落盘改动）

### 代码层 — `.squad/tools/pool_append.py`

锚点：原文件已具备锁（msvcrt/fcntl）+ 原子 replace + SHA-256 last-50 dedup。本次只补缺口，不重写。

新增不变量：

| 守卫 | 实现 | 触发动作 |
|---|---|---|
| **G1 size-must-grow** | 在锁内比较 `cur_size` vs `new_size`；append-only 路径 `new_size > cur_size` 必成立 | 违反 → `rc=49` + diag dump（拒绝 `os.replace`） |
| **G3 safe-floor (100KB)** | `cur_size >= 100KB` 时，`new_size` 也必须 ≥ 100KB | 违反 → `rc=49` + diag dump |
| **post-replace verify** | `os.replace` 后 `POOL.stat().st_size` 必等于 `new_size` | 违反 → `rc=49` + diag dump（暴露绕锁的并发写者） |
| **diag dump 包** | `diag_dump(reason, **extra)` 输出 pool/lock 路径、大小、pid、python、cwd 等 | 任何 hard-stop 路径触发 |

`DIAG_FAIL_RC = 49` 显式锚定历史 "rc=49 mystery"。

未动：
- 现有 SHA-256 last-50 dedup 逻辑（已工作）
- 锁原语（已工作）
- 命令行参数

### 测试层

新增 `.squad/tools/test_pool_append_dup_noop.py`：覆盖 spec Test 2 — 同 payload 写两次，第二次 rc=0、stdout 含 `duplicate`、anchor 数不变、size 不变、无 `.tmp` 残留。

回归测试：

```
test_pool_append_dup_noop.py        Ran 1 test  OK  (0.609s)
test_pool_append_n_writer_stress.py Ran 1 test  OK  (1.357s)
test_audit_pool_near_duplicates.py  19 passed       (0.23s)
```

真实 repo 对 `pool_append.py` 的 smoke 写入 `rc=0`，pool tail 已含两条 `## [smoke-test-2026-04-26]` block。

### 治理层

| 文件 | 改动 |
|---|---|
| `.claude_squad/charter.md` | 在 §Patrol 12 与 §Model 之间插入完整 §Long-run hard rules，含 HR1–HR6 全文 |
| `.claude_squad/agents/morpheus/charter.md` | §SQUAD MODE 进场清单从 3 份增到 4 份（追加 charter §Long-run hard rules）；新增 "直接对你（Morpheus）的硬约束" 段 |
| `CLAUDE.md` | §Squad 模式新增 "4. Long-run hard rules（强制）" 子节，含 HR1–HR6 关键词锚点供 grep |

HR1–HR6 关键词覆盖（spec Test 5 静态检查）：

```
charter.md       命中 12 次：pool_append.py / rc=49 / hard stop / Dispatch pre-flight /
                            Observation-loop breaker / Round authority / forbidden …
CLAUDE.md        命中  8 次：HR1–HR6 + pool_append.py
```

---

## Decisions

| 决策 | WHY |
|---|---|
| 在 `pool_append.py` 内部加 G1/G3，而不是另写 wrapper | 单一真源；wrapper 会被绕过，内嵌守卫不会 |
| 用 `rc=49` 作为所有不变量违反的统一退出码 | 直接锚定历史 "rc=49 mystery"，让未来 grep 一搜即中；`diag_dump` 同时提供为什么 |
| 不清理 pool 里的两条 smoke-test 条目 | 清理只能走 pool_append（无删除接口）或绕过守卫直写（违反 HR1）；保留它们作为本次修复的落盘证据，反而是诚实的 |
| 不改 `.copilot/` 下的 SKILL.md | v4 §5.0 默认不可改；属另一个权限范畴 |
| HR4 的 "2 轮" 由 external signal 判定（artifact mtime / git diff / task transition / eval delta） | v4 §11.3 原则；agent 自报 round 已被 §11.5 事故证据多次打脸，HR5 直接禁止 |
| 不新增 `tools/squad/check-eval-cadence.ps1` 等 spec 提到的额外脚本 | spec 第三节明确说"必改 vs 不建议改"；`check_eval_cadence.py` 已存在，不重复造 |

---

## Open

- **HR4 / HR5 是规则文，不是强制器**：观察循环 / round 编号需要在 morpheus prompt 实际激活时被 agent 自律遵守；后续可考虑加 lint 脚本扫描 orchestration-log（出现 `Round \d+` 即报警）。本次未做。
- **HR3 dispatch pre-flight** 同样是规则文。如要硬化，需在 squad CLI 层做 task-create 前的重复检查，不在本次范围。
- **pool 历史 269 个 queued task** 与本次修复无关，未触碰。

---

## Next（最小下一步）

- 用户验收本次 6 处改动。
- 若验收通过，下一步候选（按优先序）：
  1. 给 HR3/HR4/HR5 加自动化 lint 守卫（扫描 orchestration-log + audits）。
  2. v4 §1.3 列的 P0 评测可信度（qrels / canary / full 口径分清）。
  3. v4 §1.3 列的 P1 rerank 降压 / budget guard 收尾。

---

## 落盘验证（grep / 命令）

下面命令用户可直接复跑核验：

```powershell
Set-Location 'C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script'
$py='C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe'

# 1. 守卫已落代码
Select-String -Path .squad/tools/pool_append.py -Pattern "G1 size-must-grow|G3 safe-floor|DIAG_FAIL_RC|diag_dump"

# 2. 两个测试通过
& $py .squad/tools/test_pool_append_dup_noop.py
& $py .squad/tools/test_pool_append_n_writer_stress.py

# 3. 治理规则在 charter 与 CLAUDE.md 落定
Select-String -Path .claude_squad/charter.md -Pattern "HR1|HR2|HR3|HR4|HR5|HR6|pool_append.py|rc=49"
Select-String -Path CLAUDE.md -Pattern "HR1|HR2|HR3|HR4|HR5|HR6"

# 4. Morpheus charter 已锚定 §Long-run hard rules
Select-String -Path .claude_squad/agents/morpheus/charter.md -Pattern "Long-run hard rules|pool_append.py|checkpoint <UTC>"
```

预期：每条命令至少各命中 1 次；测试均 `OK`。
