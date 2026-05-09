# LLM-Wiki 集成切片 Runbook

> LMWR-466 · Wiki Workbench minimal Playwright E2E

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-466 |
| 简短描述 | 复用现有 Playwright E2E 框架，为 `/wiki` 工作台补最小关键工作流验收；浏览器仅作为独立窗口终态前的开发期预览和 smoke gate。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T23:55:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| 初始 scaffold checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-230454-lmwr-466-wiki-playwright-e2e` |
| 路由修复 checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-232246-lmwr-466-wiki-e2e-route-fallback-fix` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-232246-lmwr-466-wiki-e2e-route-fallback-fix" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| Playwright Mock APIs | `https://playwright.dev/docs/mock` | 优先复用现有 `page.route()` mock 机制，不引入第二套 E2E 栈。 |
| Playwright Route API | `https://playwright.dev/docs/api/class-route` | 多个 route 命中同一请求时，用 `route.fallback()` 把请求交回更早注册的专用 mock，而不是 `continue()` 直接放到真实网络。 |
| Playwright `webServer` | `https://playwright.dev/docs/test-webserver` | 继续沿用仓库现有 Vite + Playwright webServer 配置，避免为测试新开脚手架。 |
| 本地前端 E2E harness | `frontend/playwright.config.ts`、`frontend/tests/e2e/a-smoke.spec.ts`、`frontend/tests/e2e/skill-manager.spec.ts` | 继承现有 baseURL、worker、mock 安装方式和断言风格。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `frontend/tests/e2e/wiki-workbench.spec.ts` | 新增 Wiki Workbench 最小 E2E，覆盖 sidebar route、deep-link preview、page list select、compile dry-run、doctor/review/graph 只读治理面。 |
| `frontend/tests/e2e/mockApi.ts` | 新增 Wiki `/api/wiki/*` fixtures；修复 `**/api/**` catch-all，用 `route.fallback()` 让专用 Wiki mocks 生效，避免 500 错误态误伤测试。 |

---

## 4. 关键问题与修复

### 首轮失败归因

- `/api/wiki/status`、`/api/wiki/pages`、`/api/wiki/doctor` 等请求在浏览器里显示 500 错误态。
- 根因不是页面实现，而是 E2E mock 顺序：最后注册的 `**/api/**` catch-all 抢先命中了 Wiki 请求。
- 原 catch-all 对非 budget/chat 请求直接返回 `{}`，触发前端 strict parser 报 500。

### 修复方式

- catch-all 改为对 `/api/wiki/`、`/api/budget`、`/api/chat` 调用 `route.fallback()`。
- 保留其他未知 `/api/**` 请求的兜底 `{}`，继续防止测试期真实网络错误。
- 收紧断言，避免把页面说明文案中的 `enabled`、`node_count` 误判为状态数据。

---

## 5. Verification

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend
npm run test:e2e -- tests/e2e/wiki-workbench.spec.ts --reporter=line
npm run test -- --run src/services/wikiApi.test.ts
npm run build
```

| 检查项 | 结果 |
| ------ | ---- |
| Wiki Workbench focused Playwright E2E | PASS（5 passed） |
| `wikiApi` focused Vitest | PASS（11 passed） |
| frontend build | PASS |

---

## 6. 交付边界

- 本轮只补“开发期最小浏览器验收面”，不把浏览器 UI 当最终独立窗口产品形态。
- 不引入 Cypress，不扩张到视觉回归、全站 E2E 或完整响应式矩阵。
- 现有用例只验证关键工作流是否可打开、可读取、可 dry-run、可显示治理态。

---

## 7. Open / 后续

- LMWR-470 可在备份和对照评测前提下继续做 chunk 参数 200/8 复核。
- LMWR-472 可继续补本地轻量安全门禁。
- LMWR-473 可补 Wiki observability，把 query/compile/doctor 的日志和指标面统一起来。
