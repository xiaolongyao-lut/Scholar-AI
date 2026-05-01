# Squad ↔ v4 用户画像同步执行报告

> 日期：2026-04-26
> 执行者：Claude (post-context-compaction 续作)
> 任务：把 squad 的用户画像引用同步到 v4，做 squad 适配，修复 v4 残留 2 项小问题。
> 用户偏好路径：`或者把squad的画像弄成跟你一样的路径，这样以后你改他就改` → 采用统一路径方案（single source of truth）。

---

## Facts（实际落盘改动）

### 1. `.claude_squad/config.json`
- 改：`user_profile_ref` 从 v1 改为 v4 路径。
- 增：`user_profile_legacy_refs` 数组，列入 v1 / v2 / v3 archival 路径，供历史追溯。

### 2. `.claude_squad/team.md` §Owner Decision Profile (Autopilot)
- **Primary** 改为 v4（canonical）。
- **Operational reference** 显式指向 v2。
- **Evidence** 显式指向 v1，并标注 “for original-quote forensics only”。
- **Superseded** 显式声明 v3 archival、v4 overrides。
- **Skill index** 旧 `my-project/.copilot/skills/user-profile/SKILL.md` 降级为 Copilot-side index，不再做 Squad primary。

### 3. `.claude_squad/identity/requirement-scoring.md`
- Profile source 列表从 2 条扩为 4 条，标注 canonical → archival 顺序。

### 4. `.claude_squad/agents/morpheus/charter.md` 第 4 步“自探索”
- 主参考从 v3 改为 v4。
- 追加约束：每条新需求必须满足 v4 §11 的 envelope 字段（objective / scope / disallowed / budget / checkpoint / stop / artifacts / rollback / evidence），落实事故 §11.5 的整改。

### 5. `CLAUDE.md` §Squad 模式 §1 “激活 Squad” 决策依据行
- 主参考从 v1 改为 v4，并明确点名 v4 §5 / §8 / §11 / §11.5。
- 标注 v1 / v2 / v3 各自定位（证据 / 操作手册 / archival）。

### 6. v4 自身两项小修
- §1.3 缺口索引：P0 / P1 / P2 全部加 “2026-04-26 快照” 时间戳，并提示接手者先核验日期。
- §5.4 不可替代决策清单：补“泛化授权语不覆盖此清单；分不清就按红线请示”的硬约束。

---

## Decisions

| 决策 | WHY |
|---|---|
| 采用统一路径方案而不是内容拷贝 | 用户原话 “以后你改他就改”；single source of truth 避免双份内容漂移 |
| `.squad/` 维持现状（已是 v4） | 之前会话已同步过；本次只补齐 `.claude_squad/` 一边 |
| `user_profile_legacy_refs` 列入 v1/v2/v3 而不是删除 | v4 §16 明确保留分工：v1 证据档案、v2 操作手册、v3 archival；squad 仍可在“追溯证据”场景按需读取 |
| 在 morpheus charter 第 4 步追加 envelope 强约束 | 直接对接 §11.2/11.3/11.5 的事故整改，把 v4 协议物理钉到 squad 自探索入口 |
| §1.3 加“2026-04-26 快照”而不是直接删 | 不破坏 v4 当前内容；只让未来 AI 知道这是冻结快照、需先核仓库现状 |
| §5.4 加“即使用户说过全部授权” | 防 L3 授权语义滑坡（已被 §11.5 事故证据反复打脸） |

---

## Open

- 是否需要把 `my-project/squad-run.ps1` L73-74、L106-107、L232-238 以及 `my-project/.copilot/skills/user-profile/SKILL.md` L12-13 也升级到 v4？  
  当前判断：`my-project/` 是另一目录的子项目，且其中 `.copilot/skills/` 属画像中 §5.0 默认不可改的 Copilot 私有配置范围；不在本次默认权限内。如需升级请用户单独点名。
- v4 §11.5 事故索引列了 4 起 2026-04-25 的事故；本次只更新引用，未触碰 `pool_append.py` 的 G1/G2/G3 守卫加固（仍是 P0 待办，留给后续单独 surgical 修复）。

---

## Next（最小下一步）

- 用户验收本次 6 处改动是否符合预期。
- 若验收通过，下一步进入 `pool_append.py` G1（size-must-grow）/ G2（SHA-256 dedup, 已实现 50 条窗口）/ G3（safe-floor 100KB）守卫补强；这是 §11.5 事故索引第 1 条的实际整改入口。
- 如需把 `my-project/` 一并同步，请明确点名授权（因涉及 Copilot 私有配置目录）。

---

## 落盘验证（grep）

下面命令用于复核本次同步无遗漏：

```powershell
# 1. 确认 .claude_squad 内已无对 v1/v3 的 primary 引用
Select-String -Path .claude_squad\**\*.md,.claude_squad\config.json -Pattern "用户画像_(AI协作工程画像|v3)" -SimpleMatch

# 2. 确认 v4 路径在四处都已落定
Select-String -Path .claude_squad\config.json,.claude_squad\team.md,.claude_squad\identity\requirement-scoring.md,.claude_squad\agents\morpheus\charter.md,CLAUDE.md -Pattern "用户画像_v4_AI协作治理型工程主理人"

# 3. 确认 v4 自身两项小修已落地
Select-String -Path "C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md" -Pattern "2026-04-26 快照","泛化授权语不覆盖此清单"
```

预期结果：
- 命令 1 仍会命中 `user_profile_legacy_refs` 与 §Evidence profile source（v1）— 这是设计行为，不是遗漏。
- 命令 2 应在 5 个文件里都命中至少 1 次。
- 命令 3 应同时命中 P0 / P1 / P2 三行的 “2026-04-26 快照” 与 §5.4 的硬约束句。
