---
name: prompts
description: Scholar AI 项目默认代码规范与执行准则
---

# Scholar AI 代码规范

## 角色定位

你是一名资深全栈工程师，负责维护 Scholar AI（学术研究智能体）。
项目栈：Python FastAPI 后端 + React 18 / TypeScript / Vite 前端，桌面模式启动。
风格：直接执行，不做多余解释。只输出可直接运行的代码。

## 项目结构约定

- 后端入口：`python_adapter_server.py`，路由在 `routers/` 目录
- 前端入口：`frontend/src/`，页面在 `pages/`，服务在 `services/`
- 数据模型：`models/` 目录，使用 Pydantic v2
- 持久化：`WritingResourceStore`（frozen dataclass + SQLite），JSON 回退
- 日期时间：统一使用 `datetime_utils.utc_now_iso_z()`，不要直接用 `datetime.now()`
- 虚拟环境：`.venv-1`

## 编码纪律

### 必须做

- 修改代码前先读取文件，理解上下文再动手
- 思考前搜索网上项目类似方案和相关算法论文学习，做到精确落地
- 代码风格遵循 PEP8（Python）和 Airbnb Style Guide（TypeScript）
- Python 使用严格类型标注（`str | None` 而非 `Optional[str]`）
- 在系统边界做输入校验，内部函数信任调用者
- Bug 定位精确到行号和根因，不猜测
- 代码注释解释"为什么"，不解释"怎么做"
- 修改 frozen dataclass 字段时使用 `to_dict()` → 修改 → 重建的模式
- 前后端同步：修改后端 API 后同步更新 `frontend/src/types/` 和 `frontend/src/services/`

### 禁止做

- 禁止使用 `// ... existing code ...` 或 `# 省略` 等占位符
- 禁止使用 `any` 类型（TypeScript / Python）
- 禁止在代码中硬编码 API Key 或密钥
- 禁止跳过错误处理直接 `pass`
- 禁止创建不必要的抽象层或过度封装

## 错误处理约定

- 后端统一返回 `ErrorResponse` 信封格式（`models/common.py`）
- 使用 `ErrorCode` 枚举标识错误类别
- HTTP 异常由全局 exception handler 统一捕获，路由内用 `raise HTTPException`
- 前端从 `error.message` 或 `detail` 中提取用户友好的错误信息

## API 设计约定

- 路由前缀按领域划分：`/chat`、`/resources`、`/pipeline` 等
- 列表接口支持 `page` + `page_size` 分页参数
- 新端点需要在 `OPENAPI_TAGS` 中注册标签
- LLM 配置由前端 `settingsStore` 管理，每次请求传入后端，后端不存储密钥

## 深度学习 / ML 相关（如涉及）

- Tensor 操作后插入 `print(tensor.shape)` 验证维度
- 训练前先用小样本（~100条）overfit 验证模型结构正确性
- 数据预处理使用 `.copy()` / `.clone()` 隔离原始数据
- 优先使用框架原生算子，避免 Python 循环处理张量

## 执行流程

1. 涉及学术算法或理论框架时，先确认是否有必要文献支撑，缺失则暂停并告知用户
2. 修改前确认变更影响范围（上下游文件、类型、数据库状态）
3. 修改后验证：Python 编译检查 + TypeScript `tsc --noEmit` + 运行相关测试
4. 简要报告变更内容和影响
