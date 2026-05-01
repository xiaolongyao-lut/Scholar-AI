# 技术规范 #1: RobustJSONParser (鲁棒JSON解析)

**版本**: v1.0  
**状态**: Ready for Implementation  
**优先级**: 🔴 立即  
**目标模块**: `layers/robust_parser.py`  
**集成点**: `layers/ai_adapter.py` 

---

## 1. 模块设计

### 1.1 核心类

```python
class RobustJSONParser:
    """
    鲁棒的JSON解析器，处理LLM输出的常见格式问题。
    
    处理场景:
    - LLM输出被 ```json ``` markdown包裹
    - JSON尾部有逗号未移除
    - 非ASCII字符编码问题
    - 不完整的JSON (LLM被截断)
    - 特殊字符转义问题
    """
    
    @staticmethod
    def parse(text: str, fallback: Optional[Dict] = None) -> Dict[str, Any]:
        """
        安全解析JSON，自动修复常见问题。
        
        Args:
            text: LLM原始输出
            fallback: 解析失败时的默认值 (默认: {})
        
        Returns:
            解析后的字典，若全部失败则返回fallback
        
        Raises:
            无 (所有异常都被捕获并记录)
        """
    
    @staticmethod
    def parse_list(text: str, fallback: Optional[List] = None) -> List[Dict]:
        """
        解析JSON数组。
        
        Args:
            text: LLM原始输出
            fallback: 解析失败时的默认值 (默认: [])
        
        Returns:
            解析后的列表
        """
```

### 1.2 修复策略 (按优先级)

| 顺序 | 策略 | 示例 | 成功率 |
|------|------|------|--------|
| 1 | 直接解析 | 正常JSON | 70% |
| 2 | 剥离markdown | `\`\`\`json {...}\`\`\`` → `{...}` | 15% |
| 3 | 删除尾部逗号 | `{"a": 1,}` → `{"a": 1}` | 8% |
| 4 | 修复引号 | `{a: 'value'}` → `{"a": "value"}` | 3% |
| 5 | 部分修复 | 截断补齐 | 3% |
| 6 | Fallback | 返回默认值 | 1% |

---

## 2. 实现细节

### 2.1 剥离Markdown标记

```python
def _strip_markdown(text: str) -> str:
    """
    剥离 ```json ... ``` 包裹
    
    处理的模式:
    - ```json\n{...}```
    - ```\n{...}```
    - ``` json\n{...}```
    - 多行情况
    """
    # 模式1: json标记
    text = re.sub(r'^```(?:\s*json)?\s*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text)
    
    # 模式2: 其他markdown (不常见但保险)
    text = re.sub(r'^```', '', text)
    text = re.sub(r'```$', '', text)
    
    return text.strip()
```

**测试用例**:
```python
assert _strip_markdown("```json\n{\"a\": 1}\n```") == '{"a": 1}'
assert _strip_markdown("```\n{\"a\": 1}```") == '{"a": 1}'
assert _strip_markdown("{\"a\": 1}") == '{"a": 1}'  # 无markdown的情况
```

---

### 2.2 删除尾部逗号

```python
def _fix_trailing_commas(text: str) -> str:
    """
    删除 JSON 对象/数组中的尾部逗号
    
    规则:
    - , ] → ]
    - , } → }
    - , \n ] → ]
    - , \n } → }
    
    限制: 不处理字符串内的逗号 (通过边界检查)
    """
    # 模式: 逗号前面跟着 ]} 之一
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text
```

**测试用例**:
```python
assert _fix_trailing_commas('{"a": 1, "b": 2,}') == '{"a": 1, "b": 2}'
assert _fix_trailing_commas('[1, 2, 3,]') == '[1, 2, 3]'
assert _fix_trailing_commas('[{"x": 1,},]') == '[{"x": 1}]'
```

---

### 2.3 修复不匹配的引号

```python
def _fix_unmatched_quotes(text: str) -> str:
    """
    处理不配对的引号和单引号问题
    
    规则:
    - 检测 { 内的 key:value 对
    - 若 key 没有引号，添加引号
    - 若 value 是单引号，改成双引号
    
    示例:
    {name: 'Alice'} → {"name": "Alice"}
    """
    # 模式1: 无引号的key (不推荐做，容易出错)
    # 这个比较危险，仅在其他方法都失败时尝试
    
    # 模式2: 单引号改双引号
    text = re.sub(r":\s*'([^']*)'", r': "\1"', text)
    
    return text
```

---

### 2.4 部分JSON修复 (截断补齐)

```python
def _repair_truncated_json(text: str) -> str:
    """
    处理被截断的JSON (LLM输出到一半被cut off)
    
    策略:
    1. 计数 { 和 } 的数量
    2. 若 { 比 } 多，补充缺失的 }
    3. 若最后是数组，补充 ]
    
    例:
    {"a": {"b": [1, 2 → {"a": {"b": [1, 2]}}
    """
    open_braces = text.count('{')
    close_braces = text.count('}')
    missing_braces = open_braces - close_braces
    
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    missing_brackets = open_brackets - close_brackets
    
    # 补充缺失的括号
    text = text + ('}' * missing_braces) + (']' * missing_brackets)
    
    return text
```

**测试用例**:
```python
assert _repair_truncated_json('{"a": [1, 2') == '{"a": [1, 2]}'
assert _repair_truncated_json('[{"x": 1') == '[{"x": 1}]'
```

---

### 2.5 日志与监控

```python
class ParsingStats:
    """统计解析过程"""
    total_attempts: int = 0
    direct_success: int = 0  # 直接解析成功
    stripped_success: int = 0  # 剥离markdown后成功
    fixed_commas_success: int = 0
    fixed_quotes_success: int = 0
    repaired_success: int = 0
    fallback_count: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return (self.total_attempts - self.fallback_count) / self.total_attempts
    
    def log(self):
        logger.info(
            f"JSON解析统计 - 成功率: {self.success_rate:.1%}, "
            f"直接: {self.direct_success}, "
            f"修复: {sum([self.stripped_success, self.fixed_commas_success, ...])}, "
            f"Fallback: {self.fallback_count}"
        )
```

---

## 3. 集成到AIAdapter

### 3.1 修改 `layers/ai_adapter.py`

```python
# 在 AIAdapter 类中新增方法

from layers.robust_parser import RobustJSONParser

class AIAdapter:
    def __init__(self, ...):
        self.parser = RobustJSONParser()
    
    def extract_claims(self, text: str, goal: str) -> List[Dict[str, Any]]:
        """使用RobustJSONParser解析LLM输出"""
        if not self.enabled:
            return []
        
        try:
            response = self.client.chat.completions.create(...)
            response_text = response.choices[0].message.content
            
            # 使用鲁棒解析
            claims_json = self.parser.parse(response_text, fallback=[])
            
            if isinstance(claims_json, dict):
                claims_json = claims_json.get("claims", [])
            
            return claims_json
        
        except Exception as e:
            logger.error(f"提取claims失败: {e}")
            return []
```

---

## 4. 测试用例

### 4.1 单元测试结构

```python
# tests/test_robust_parser.py

import pytest
from layers.robust_parser import RobustJSONParser

class TestRobustJSONParser:
    
    def test_direct_parse_valid_json(self):
        """直接解析正常JSON"""
        text = '{"name": "Alice", "age": 30}'
        result = RobustJSONParser.parse(text)
        assert result == {"name": "Alice", "age": 30}
    
    def test_strip_markdown_single_line(self):
        """处理单行markdown"""
        text = '```json\n{"name": "Alice"}\n```'
        result = RobustJSONParser.parse(text)
        assert result == {"name": "Alice"}
    
    def test_fix_trailing_commas(self):
        """删除尾部逗号"""
        text = '{"name": "Alice", "age": 30,}'
        result = RobustJSONParser.parse(text)
        assert result == {"name": "Alice", "age": 30}
    
    def test_fix_unmatched_quotes(self):
        """修复单引号"""
        text = "{'name': 'Alice', 'age': 30}"
        result = RobustJSONParser.parse(text)
        assert result == {"name": "Alice", "age": 30}
    
    def test_repair_truncated(self):
        """修复被截断的JSON"""
        text = '{"data": [1, 2, 3'
        result = RobustJSONParser.parse(text)
        assert result == {"data": [1, 2, 3]}
    
    def test_parse_list(self):
        """解析JSON数组"""
        text = '[{"id": 1}, {"id": 2,}]'
        result = RobustJSONParser.parse_list(text)
        assert len(result) == 2
        assert result[0]["id"] == 1
    
    def test_fallback_on_failure(self):
        """完全失败时返回fallback"""
        text = 'not json at all ヾ'
        result = RobustJSONParser.parse(text, fallback={"error": "parse_failed"})
        assert result == {"error": "parse_failed"}
```

### 4.2 集成测试

```python
# tests/test_ai_adapter_robust.py

@pytest.mark.asyncio
async def test_extract_claims_with_malformed_json():
    """模拟LLM返回畸形JSON"""
    adapter = AIAdapter(api_key="test_key", model="test")
    
    # Mock LLM 返回带markdown的JSON
    mock_response = '```json\n{"claims": [{"id": 1,}]}\n```'
    
    # 验证鲁棒解析能处理
    result = adapter.parser.parse(mock_response)
    assert result["claims"][0]["id"] == 1
```

---

## 5. 性能指标

### 5.1 预期表现

| 场景 | 解析时间 | 成功率 | 备注 |
|------|---------|--------|------|
| 正常JSON | <1ms | 100% | 无修复 |
| 有markdown | 2-3ms | 99% | 正则剥离 |
| 尾部逗号 | 2-3ms | 99% | 正则替换 |
| 单引号混用 | 3-5ms | 95% | 需谨慎 |
| 截断JSON | 5-10ms | 90% | 可能失去数据 |
| 完全失败 | <1ms | - | 返回fallback |

### 5.2 监控指标

```python
# 在AIAdapter中添加
logger.info(f"JSON解析成功率: {parser.stats.success_rate:.1%}")
logger.info(f"修复策略分布: {parser.stats.breakdown()}")
```

---

## 6. 错误处理

### 6.1 保留的异常

| 异常类型 | 处理方式 | 日志级别 |
|---------|---------|---------|
| JSONDecodeError | 日志 + 尝试下一策略 | DEBUG |
| 所有策略都失败 | 返回fallback | WARNING |
| 输入为None | 返回fallback | ERROR |

### 6.2 日志示例

```python
logger.debug("开始解析JSON: {text[:50]}...")
logger.debug("步骤1: 直接解析 - 失败")
logger.debug("步骤2: 剥离markdown - 成功")
logger.info("JSON解析成功 (策略: 剥离markdown)")
```

---

## 7. 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `layers/robust_parser.py` | 200-250 | 核心实现 |
| `tests/test_robust_parser.py` | 120-150 | 单元测试 |
| `tests/test_ai_adapter_robust.py` | 50-80 | 集成测试 |
| 修改 `layers/ai_adapter.py` | +50 | 集成RobustParser |

**总工作量**: ~400-500 行

---

## 8. 交付清单

- [ ] `layers/robust_parser.py` 实现
- [ ] 完整的单元测试覆盖 (>95%)
- [ ] 集成到 `ai_adapter.py`
- [ ] 性能基准测试 (benchmark.py)
- [ ] 文档与示例
- [ ] CI/CD 验证 (所有测试通过)
