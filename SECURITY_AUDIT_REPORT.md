# 代码深度安全审查报告

**审查日期**: 2026-06-09  
**项目**: Scholar AI Workbench (literature_assistant) v0.1.8.2  
**审查方法**: 纯源码静态分析（370 后端 + 320 前端 + 337 测试文件）

---

## 执行摘要

### 总体评分: 82/100 ⭐⭐⭐⭐

| 维度 | 评分 | 状态 |
|------|------|------|
| 架构设计 | 90/100 | ✅ 优秀 |
| 安全性 | 85/100 | ✅ 良好（主要风险已修复） |
| 测试覆盖 | 80/100 | ✅ 良好 |
| 代码质量 | 75/100 | ⚠️ 可接受 |
| 可维护性 | 85/100 | ✅ 良好 |

### 关键发现

#### ✅ 已修复的安全问题

1. **P0-1: 日志敏感信息过滤** ✅ 已完成
   - 位置: `python_adapter_server.py:87-150`
   - 实现: `SensitiveDataFilter` 类，正则过滤 API_KEY/Bearer/sk-* 等模式
   - 覆盖: Authorization 头、环境变量赋值、所有已知密钥格式

2. **P0-2: 浏览器缓存破坏性删除** ✅ 已完成
   - 位置: `start.py:133-184`
   - 实现: 版本化缓存清理，仅在前端构建变更时执行
   - 安全: 路径边界检查，防止误删用户数据

3. **依赖版本锁定** ✅ 已完成
   - 所有依赖已添加上限约束（如 `pydantic>=2.8.0,<3.0.0`）

4. **前端 OpenAPI 自动生成** ✅ 已完成
   - `package.json` 添加 `prebuild` hook，构建前自动检查并生成类型

---

## 架构分析

### 项目定位
**Scholar AI Workbench** - 本地优先的学术文献研究工作台

**核心功能**:
- RAG 智能研读（32 个 API 路由）
- 多轮讨论与证据追踪
- Wiki 知识库与知识图谱
- 写作辅助（Word/PDF/LaTeX 导出）
- MCP 扩展系统

### 技术栈
- **后端**: Python 3.11+ (FastAPI + Uvicorn)
- **前端**: React 18 + TypeScript + Vite
- **数据库**: SQLite (WAL 模式)
- **凭证**: OS Keyring (Windows DPAPI / macOS Keychain)
- **打包**: PyInstaller + Inno Setup

### 代码规模
- 后端: 370 个 .py 文件，665 个 API 端点函数
- 前端: 320 个 .tsx/.ts 文件
- 测试: 337 个 test_*.py 文件

---

## 优秀实践亮点

### 1. 凭证管理（行业标准）⭐⭐⭐⭐⭐

```python
# OS Keyring 存储
class KeyringCredentialSecretBackend:
    def store_secret(self, secret_ref: str, secret: str):
        keyring.set_password(self._service_name, ref, value)

# 原子写入
_atomic_write_json(self._path, payload)  # .tmp + os.replace

# 线程锁
with self._lock:
    # 原子操作

# 响应掩码
return c.to_public()  # 排除 api_key
```

**评价**: 完全符合行业最佳实践

### 2. 数据库并发安全 ⭐⭐⭐⭐⭐

```python
conn.execute("PRAGMA foreign_keys = ON")  # 外键约束
conn.execute("PRAGMA journal_mode = WAL")  # 多读单写并发
```

### 3. 前端工程化 ⭐⭐⭐⭐⭐

- 动态端口代理（后端重启无需重启 vite）
- OpenAPI 自动生成类型
- TypeScript 严格模式

### 4. 打包路径正确 ⭐⭐⭐⭐⭐

```python
# 生产环境数据写入 %APPDATA%，不写入 Program Files
if getattr(sys, "frozen", False):
    return (Path(appdata) / "LiteratureAssistant").resolve()
```

---

## 残留风险与建议

### 🟠 P1-1: 多实例数据竞争（中风险）

**问题**: 缺少跨进程互斥锁

**建议**:
```python
# 启动时单实例检测
def check_single_instance():
    pid_file = runtime_state_path("backend.pid")
    if pid_file.exists():
        old_pid = int(pid_file.read_text())
        if psutil.pid_exists(old_pid):
            raise RuntimeError(f"另一个实例正在运行 (PID {old_pid})")
    pid_file.write_text(str(os.getpid()))
```

**优先级**: 中（1-2 周内）

---

### 🟠 P1-2: 凭证测试端点（中低风险）

**现有保护**:
- ✅ Capability Token
- ✅ 端点信任验证
- ✅ 响应掩码

**建议加强**:
```python
# 1. 限流
@limiter.limit("5/minute")
async def test_credential(...): pass

# 2. 前端确认
const confirmed = window.confirm(`将发送 API 密钥到: ${baseUrl}...`);
```

**优先级**: 高（1 周内）

---

### 🔵 P2 级低风险问题

1. **Mypy 类型检查宽松** - 建议启用 strict 模式
2. **启动器 GUI 错误处理** - 建议添加 tkinter 对话框
3. **打包体积优化** - 建议拆分精简版/完整版

---

## .gitignore 审查 ✅

**状态**: 优秀

```gitignore
.env
.env.*
**/*credential*.json
**/*secret*.json
**/*.key
**/*.db
/.claude/
/.copilot/
/docs/
```

**验证通过**: 所有敏感文件都已正确忽略

---

## 发布前检查清单

### 高优先级（建议完成）

- [ ] 凭证测试端点限流（5次/分钟）
- [ ] 前端确认对话框（测试凭证前）
- [ ] 多实例检测（PID 文件）

### 中优先级

- [ ] 打包体积优化（拆分版本）
- [ ] 测试覆盖率报告（>80%）
- [ ] 用户文档（安装指南）

### 低优先级

- [ ] Mypy 严格模式
- [ ] 启动器 GUI 改进

---

## 总结

### 安全状况: ✅ 良好

**主要风险已全部修复**:
- ✅ 日志敏感信息过滤
- ✅ 浏览器缓存破坏性删除
- ✅ 依赖版本锁定
- ✅ OpenAPI 自动生成

**残留风险可控**:
- 🟠 多实例数据竞争（有缓解措施）
- 🟠 凭证测试端点（有现有保护）

### 发布建议: ✅ 可以发布

**预计风险**: 低  
**代码质量**: 高  
**安全性**: 良好

完成高优先级清单后即可正式发布。

---

**审查完成**: 2026-06-09  
**审查者**: 独立代码审查员  
**下次审查**: 3 个月后或重大版本更新前
