# 前端队员 API 接入说明（简版）

## 你要发给前端队员的内容

- `VITE_API_BASE_URL=`（你的后端地址）
- `VITE_FRONTEND_APP_TOKEN=`（前端专用低权限 token）
- 主路第三方（按 `BASE_URL / API_KEY / MODEL` 读取）：
  - `VITE_BASE_URL=`
  - `VITE_API_KEY=`
  - `VITE_MODEL=`
- Copilot 回退（可选；不知道 key 可以不发）：
  - `VITE_COPILOT_PROVIDER=Copilot`
  - `VITE_COPILOT_BASE_URL=`
  - `VITE_COPILOT_API_KEY=`
  - `VITE_COPILOT_MODEL=`

## 队员本地怎么填

1. 你在仓库根目录维护团队模板：`.env.frontend.example`（用于分发字段说明）。
2. 队员进入 `frontend/`。
3. 复制 `frontend/.env.example` 为 `frontend/.env.local`。
4. 把你发的值填进去，保存。
5. 启动前端，验证接口是否通。

## 联不通回退规则（已固定）

- 默认：当前主路第三方联不通（网络/超时/5xx/模型不存在）时，前端直接重试你们现有后端路数。
- 仅当 Copilot 的 `BASE_URL + MODEL + API_KEY` 都已填写时，前端才会先自动重试 Copilot。
- 若 Copilot 重试失败，前端再自动重试后端默认路数。
- 最后一跳回退时不再附带前端 `llm` 覆盖参数，由后端当前默认配置处理。

## 分发方式（推荐）

- 用密码管理器发（1Password / Bitwarden）。
- 不在群里明文发真实 key。

## 这几个不要给前端

- `OPENAI_API_KEY`
- `RERANK_API_KEY`
- `EMBEDDING_API_KEY`

## 维护规则

- 前端同学离组：立刻吊销该前端 token。
- 建议 30-90 天轮换一次前端 token。
