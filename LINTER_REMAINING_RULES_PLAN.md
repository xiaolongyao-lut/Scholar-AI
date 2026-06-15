# Linter 规则完整实施计划

## 📊 规则清单（38个）

### ✅ 已实现（11个）

#### 标题相关 (5)
1. ✅ correct-title-sentence-case
2. ✅ correct-short-title-sentence-case
3. ✅ correct-title-whitespace
4. ✅ correct-title-en-whitespace
5. ✅ correct-title-chemical-formula

#### 作者相关 (2)
6. ✅ correct-creators-case
7. ✅ correct-creators-pinyin

#### DOI 相关 (2)
8. ✅ no-doi-prefix
9. ✅ validate-doi-format

#### 其他 (2)
10. ✅ correct-date-format
11. ✅ correct-journal-whitespace

---

## 🔧 待实现（27个）

### 高优先级（核心功能，10个）

#### 页码规则 (2)
12. **correct-pages-range** - 页码范围标准化
    - `100-110` → `100–110` (en dash)
    - `100 - 110` → `100–110`

13. **validate-pages-format** - 验证页码格式
    - 确保是数字
    - 确保起始页 < 结束页

#### 语言规则 (2)
14. **require-language** - 自动检测语言
    - 基于标题文本检测
    - 中文/英文/日文/韩文

15. **correct-language-code** - 语言代码标准化
    - `zh` → `zh-CN`
    - `en` → `en-US`

#### 期刊规则 (3)
16. **correct-publication-title-case** - 期刊名大小写
    - Nature → Nature
    - SCIENCE → Science

17. **correct-publication-title-alias** - 期刊别名
    - J. Am. Chem. Soc. → Journal of the American Chemical Society
    - 使用期刊缩写数据库

18. **correct-journal-abbreviation** - 期刊缩写
    - Journal of the American Chemical Society → J. Am. Chem. Soc.
    - 可选功能，默认关闭

#### URL 规则 (2)
19. **no-url-in-title** - 标题中不应有 URL
    - 检测并警告

20. **validate-url-format** - URL 格式验证
    - 检查 URL 字段是否是有效 URL

#### 文献类型规则 (1)
21. **require-item-type** - 要求文献类型
    - journal-article, book, conference-paper 等

---

### 中优先级（质量提升，10个）

#### 作者规则 (3)
22. **correct-creators-order** - 作者顺序
    - 确保第一作者在前

23. **correct-creators-duplicates** - 删除重复作者
    - 同一作者出现多次

24. **require-creators** - 要求至少一个作者
    - 空作者列表警告

#### 标题规则 (2)
25. **no-title-capitalization** - 禁止全大写标题
    - DEEP LEARNING → Deep learning

26. **correct-title-punctuation** - 标题标点
    - 去除末尾句号
    - 统一引号样式

#### 日期规则 (2)
27. **require-publication-date** - 要求发布日期
    - 空日期警告

28. **validate-date-range** - 日期范围验证
    - 不能是未来日期
    - 不能早于 1000 年

#### 字段规则 (3)
29. **no-empty-fields** - 删除空字段
    - 空字符串、空数组

30. **correct-field-whitespace** - 清理所有字段空格
    - 统一处理所有文本字段

31. **normalize-field-names** - 字段名标准化
    - publicationTitle → journal

---

### 低优先级（高级功能，7个）

#### 重复检测 (2)
32. **no-item-duplication** - 重复文献检测
    - 基于 DOI
    - 基于标题相似度

33. **no-duplicate-doi** - 重复 DOI
    - 同一项目内不允许重复

#### 位置信息 (2)
34. **require-university-place** - 大学地址
    - 确保机构信息完整

35. **correct-place-format** - 地址格式
    - 城市, 国家

#### 标签规则 (2)
36. **normalize-tags** - 标签标准化
    - 统一大小写
    - 删除重复

37. **require-tags** - 要求标签
    - 至少一个标签

#### 其他 (1)
38. **validate-issn-isbn** - ISSN/ISBN 验证
    - 校验码验证

---

## 📋 实施策略

### Phase 1：高优先级规则（10个）
**预计时间：** 2-3 小时

1. 创建规则骨架
2. 实现核心逻辑
3. 添加测试
4. 集成到引擎

### Phase 2：中优先级规则（10个）
**预计时间：** 2-3 小时

同上流程

### Phase 3：低优先级规则（7个）
**预计时间：** 2-3 小时

同上流程

---

## 🎯 总计

- **已完成：** 11/38 (29%)
- **待实现：** 27/38 (71%)
- **预计总时间：** 6-9 小时

---

## 🚀 立即开始

从高优先级开始，逐个实现！
