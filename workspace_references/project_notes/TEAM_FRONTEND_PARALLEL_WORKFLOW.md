# 前后端并行协作路径说明（防止路径写错）

## 目标

当后端改代码（新增函数/接口）时，前端并行补齐现有基础上的接口适配，避免只靠一个前端队员导致滞后。

## 参与角色（Squad）

- `Trinity`：后端实现
- `Dozer`：前端接口实现（并行）
- `Switch`：前端状态/交互表达审查
- `Tank`：并行变更后的回归验证

## 必须使用的准确路径

- 队伍配置：`.squad/team.md`
- 路由规则：`.squad/routing.md`
- 模型覆盖：`.squad/config.json`
- 第二前端 charter：`.squad/agents/dozer/charter.md`
- 第二前端历史：`.squad/agents/history-Dozer.md`

### 前端环境文件路径（不要写错）

- 团队共享模板（仓库根目录）：`.env.frontend.example`
- 前端本地模板：`frontend/.env.example`
- 前端成员实际填写文件：`frontend/.env.local`

## 并行执行规则（落地）

1. 后端新增/修改接口时，`Trinity` 与 `Dozer` 同时启动。
2. `Dozer` 必须在现有前端服务层上“增量添加”函数/接口，不做无关重构。
3. `Switch` 并行检查状态流转（loading/partial/ready/error）是否体现后端真实能力。
4. `Tank` 在合并前进行最小回归，确认接口联通和退化风险。

## 变更最小化原则

- 只改任务相关文件。
- 路径必须与 `team.md` 的 charter 路径一一对应且真实存在。
- 若新增成员，必须同步新增目录与 `charter.md`，避免悬空路径。
