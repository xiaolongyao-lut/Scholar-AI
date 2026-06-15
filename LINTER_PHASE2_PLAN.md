# Linter Phase 2 实施计划

## ✅ Phase 1 已完成
- 规则基类系统
- Sentence Case 转换（保护化学式、专有名词）
- API 集成（使用新引擎）
- 独立测试通过

## 📋 Phase 2 待实现规则（按优先级）

### 高优先级（立即需要）
1. **correct-title-whitespace** - 清理标题中的多余空格
2. **no-doi-prefix** - 去除 DOI 的 https://doi.org/ 前缀
3. **correct-date-format** - 标准化日期格式（June 2024 → 2024-06）
4. **correct-journal-whitespace** - 清理期刊名中的多余空格
5. **correct-title-chemical-formula** - 化学式上下标（CO2 → CO<sub>2</sub>）

### 中优先级
6. **correct-creators-case** - 作者名首字母大写
7. **correct-creators-pinyin** - 中文拼音拆分（Zhang Jianbei → Zhang Jian Bei）
8. **correct-pages-range** - 页码范围标准化
9. **require-language** - 自动检测语言

### 低优先级
10. **no-item-duplication** - 重复项检测
11. **correct-publication-title-alias** - 期刊别名映射
12. **require-university-place** - 大学地址补全

## 🔧 当前状态
- **已实现规则数**: 2/38
  - correct-title-sentence-case ✅
  - correct-short-title-sentence-case ✅

- **测试状态**: 
  - 独立测试: 全部通过 ✅
  - API 测试: 需要更新期望或实现更多规则

## 📝 下次继续时
1. 从高优先级列表开始实现规则 2-5
2. 或者先更新 API 测试以匹配当前实现
3. 然后继续实现剩余规则
