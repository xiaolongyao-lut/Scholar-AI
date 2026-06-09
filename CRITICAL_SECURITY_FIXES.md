# 关键安全修复清单

基于 2026-06-09 代码审查报告

## 🚨 高优先级（立即修复）

### ✅ 1. Release Smoke 的 Capability Header 修复
**问题**: `scripts/smoke_windows_release.ps1` 请求 `/api/wiki/status` 缺少 `X-LitAssist-Capability` header
**影响**: 发布门禁不可信，测试与真实鉴权模型不一致
**修复**: 从 runtime capability 文件读取 header
**文件**: `scripts/smoke_windows_release.ps1:39`

### ✅ 2. OpenAPI/Docs 生产环境关闭
**问题**: `/openapi.json`, `/docs`, `/redoc` 明确免鉴权，生产环境仍暴露
**影响**: 完整 API 面暴露
**修复**: FastAPI 添加 `docs_url=None, openapi_url=None`，或仅在 `LITASSIST_ENABLE_DOCS=1` 时启用
**文件**: `literature_assistant/core/python_adapter_server.py:518`

### ✅ 3. 技能导入 API 移除 managed_root
**问题**: `ImportUserSkillRequest` 允许客户端控制安装根目录
**影响**: 安全边界破坏，可写入任意路径
**修复**: 移除 `managed_root` 字段，服务端固定目录
**文件**: `literature_assistant/core/models/skills.py:124`, `literature_assistant/core/skills/service.py:469`

### 🔶 4. MCP Stdio 隔离声明
**问题**: MCP stdio 子进程无 OS 沙箱，仅软约束
**影响**: 高风险 MCP 可执行任意操作
**修复选项**:
- 选项 A: 文档明确标注为高危，需用户二次确认
- 选项 B: 移入 Windows Job/AppContainer 或低权限用户
**文件**: `literature_assistant/core/mcp_runtime/security_policy.py:5`

### 🧹 5. 清理源码树运行时残留
**问题**: `skills/imported/user/.approval`, `post_processors/__pycache__` 等混入源码
**影响**: 本机数据泄露到版本控制/发布包
**修复**: 
- 迁移到 `runtime_state` 或用户数据目录
- `.gitignore` 排除
- 发布扫描拦截
**文件**: `skills/imported/user`, `post_processors`, `thesis_renderer`

---

## 🔍 需要验证的事项

1. **测试覆盖实际情况**
   - 运行 `pytest --cov=literature_assistant --cov-report=html tests/`
   - 验证 80% 覆盖率门槛是否真实
   - 审查 coverage omit 是否过度豁免

2. **PyInstaller 产物检查**
   - 构建后检查 onedir 是否包含本地状态
   - 验证 forbidden-path scan 和 secret scan 有效性

3. **跨平台支持**
   - 非 Windows 平台降级路径测试
   - macOS/Linux 启动器验证

---

## 📋 修复优先级总结

| 序号 | 问题 | 严重性 | 预计工时 | 状态 |
|------|------|--------|----------|------|
| 1 | Release smoke capability | P0 | 30分钟 | ⏳ 待修复 |
| 2 | OpenAPI 生产关闭 | P0 | 15分钟 | ⏳ 待修复 |
| 3 | 技能导入安全 | P0 | 1小时 | ⏳ 待修复 |
| 4 | MCP 隔离声明 | P1 | 2小时 | ⏳ 待修复 |
| 5 | 运行时残留清理 | P1 | 1小时 | ⏳ 待修复 |

**预计总工时**: 4.5-5 小时
**建议完成时间**: 1 个工作日内

---

**创建时间**: 2026-06-09
**基于审查**: 独立代码审查报告
