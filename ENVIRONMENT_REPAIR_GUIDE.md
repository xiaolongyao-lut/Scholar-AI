# Python 环境修复指南

## 问题诊断

**症状**: 
- `python --version` 无输出且exit code = 1
- 导入失败无错误信息提示
- 虚拟环境 `.venv` 可能损坏

---

## 解决方案 (选一个执行)

### 方案 A: 重建虚拟环境 (推荐)

**Windows**:
```powershell
# 1. 删除旧环境
Remove-Item -Recurse -Force .venv

# 2. 创建新环境
python -m venv .venv

# 3. 激活环境
.venv\Scripts\Activate.ps1

# 4. 升级pip
python -m pip install --upgrade pip

# 5. 安装依赖
pip install -r requirements.txt
```

**Linux/Mac**:
```bash
# 1. 删除旧环境
rm -rf .venv

# 2. 创建新环境
python3 -m venv .venv

# 3. 激活环境
source .venv/bin/activate

# 4. 升级pip
python -m pip install --upgrade pip

# 5. 安装依赖
pip install -r requirements.txt
```

---

### 方案 B: 使用系统 Python (快速应急)

*如果虚拟环境无法修复，直接用系统Python*

```bash
# 安装当前项目依赖
python -m pip install --user -r requirements.txt

# 运行测试
python tests/test_robust_cache_integration.py
```

---

### 方案 C: 使用 Poetry (长期推荐)

*如果项目存在 pyproject.toml*

```bash
pip install poetry
poetry install
poetry run python tests/test_robust_cache_integration.py
```

---

## 验证修复步骤

### 步骤1: 检查Python版本
```bash
python --version
# 预期输出: Python 3.8+ (3.9/3.10/3.11都可以)
```

### 步骤 2: 验证核心模块导入
```bash
python -c "from layers.robust_parser import RobustJSONParser; print('✅ RobustJSONParser导入成功')"

python -c "from layers.claim_cache import ClaimCache; print('✅ ClaimCache导入成功')"

python -c "from layers.ai_adapter import AIAdapter; print('✅ AIAdapter导入成功')"
```

### 步骤 3: 运行集成测试
```bash
python tests/test_robust_cache_integration.py
```

**预期输出**:
```
--- Testing RobustJSONParser ---
Markdown Strip: {'id': 1, 'status': 'ok'} (Expected id:1)
Trailing Comma: {'data': [1, 2, 3]} (Expected [1,2,3])
Truncated Repair: {'claims': [{'id': 10, 'text': 'Partial'}]} (Expected structure closed)

--- Testing ClaimCache ---
Cache Hit: True
Cached Subject: Laser
```

---

## 常见问题排查

### Q1: `ModuleNotFoundError: No module named 'layers'`

**原因**: Python path不对，不在项目根目录

**解决**:
```bash
cd /path/to/Modular-Pipeline-Script  # 必须在项目根目录
python -c "..."
```

### Q2: `FileNotFoundError: [Errno 2] No such file or directory: '.venv/...'`

**原因**: .venv路径不对或权限问题

**解决**:
```bash
# Windows
.venv\Scripts\python.exe --version  # 使用完整路径

# Linux/Mac
./.venv/bin/python --version
```

### Q3: `sqlite3.OperationalError: database is locked`

**原因**: 多进程访问缓存数据库

**解决**:
```bash
# 清除缓存
rm -rf .cache/claims.db
# 或重启Python进程
```

### Q4: `ImportError: cannot import name 'RobustJSONParser'`

**原因**: 模块中有语法错误

**解决**:
```bash
python -m py_compile layers/robust_parser.py
# 如果显示SyntaxError，查看错误信息修复
```

---

## 依赖检查清单

### 必需模块

```
✅ json         (内置)
✅ logging      (内置)
✅ sqlite3      (内置)
✅ hashlib      (内置)
✅ re           (内置)
✅ pathlib      (内置, Python 3.4+)
✅ asyncio      (内置, Python 3.5+)
✅ typing       (内置, Python 3.5+)
```

### 可选模块

```
⚠️  openai       (用于LLM功能)
⚠️  transformers (用于NER功能)
⚠️  dotenv       (用于.env加载)
```

---

## 快速修复命令 (一键执行)

**Windows PowerShell**:
```powershell
# 删除旧环境 + 创建新环境 + 安装依赖
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -c "from layers.robust_parser import RobustJSONParser; from layers.claim_cache import ClaimCache; print('✅ 环境修复完成')"
```

**Bash (Linux/Mac)**:
```bash
# 删除旧环境 + 创建新环境 + 安装依赖
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -c "from layers.robust_parser import RobustJSONParser; from layers.claim_cache import ClaimCache; print('✅ 环境修复完成')"
```

---

## 环境配置验证 

修复完成后，验证以下输出：

```
✅ RobustJSONParser导入成功
✅ ClaimCache导入成功
✅ AIAdapter导入成功
✅ test_robust_cache_integration.py 通过
✅ 缓存数据库创建成功 (.cache/claims.db)
```

如果全部显示 ✅，则环境修复成功，可以继续进行功能测试。

---

## 后续步骤

修复环境后，请执行:

1. **验证实现**:
   ```bash
   python tests/test_robust_cache_integration.py
   ```

2. **集成测试**:
   ```bash
   python -m pytest tests/ -v
   ```

3. **性能测试** (可选):
   ```bash
   python tests/test_performance_benchmark.py
   ```

4. **全流程测试** (可选):
   ```bash
   python integrated_pipeline.py --mini  # 仅处理少量文件
   ```

---

## 寻求帮助

如果问题仍未解决，请提供:

1. Python版本: `python --version`
2. 完整错误输出: 在命令后添加 `2>&1 | tee error.log`
3. 系统信息: Windows/Linux/Mac + 版本
4. 已执行的修复步骤

---

**修复指南完成** ✅
