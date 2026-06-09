# OpenAPI/Docs 安全配置说明

## 默认行为（生产环境）

**默认关闭** - 除非显式启用，否则以下端点返回 404：
- `/openapi.json`
- `/docs` (Swagger UI)
- `/redoc` (ReDoc)

## 开发/调试启用

设置环境变量：
```bash
# Windows
set LITASSIST_ENABLE_DOCS=1

# Linux/macOS
export LITASSIST_ENABLE_DOCS=1
```

## 安全原因

1. **信息泄露**: OpenAPI schema 暴露完整 API 面，包括端点、参数、模型
2. **攻击面扩大**: 攻击者可利用 schema 自动化探测
3. **鉴权绕过**: 这些文档端点明确免 capability token 验证

## 实现位置

`literature_assistant/core/python_adapter_server.py:532-534`

```python
app = FastAPI(
    ...
    docs_url="/docs" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
    redoc_url="/redoc" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
    openapi_url="/openapi.json" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
)
```

## 验证

**生产环境（默认）**:
```bash
curl http://127.0.0.1:8000/docs
# 预期: 404 Not Found
```

**开发环境（显式启用）**:
```bash
set LITASSIST_ENABLE_DOCS=1
# 启动后
curl http://127.0.0.1:8000/docs
# 预期: 200 OK (Swagger UI HTML)
```

## 相关文件

- 实现: `literature_assistant/core/python_adapter_server.py`
- 测试: `tests/test_local_api_capability.py`
- 文档: 本文件

---

**创建时间**: 2026-06-09
**基于审查**: 独立代码审查报告 - 高风险问题 #2
