# Linter 诊断和下一步

## 🔍 当前问题

1. **修复后仍显示有问题**
   - 可能原因：
     - 这些文献确实还有其他未修复的问题
     - 修复逻辑不完整
     - 某些规则没有正确应用
   
2. **任务中心未集成**
   - 这是预期的，需要额外实现

## 🛠️ 诊断步骤

### 1. 查看浏览器控制台
打开开发者工具（F12），查看：
```javascript
// 点击"检查"后，应该看到
[Linter] 检查结果: {...}

// 点击"修复"后，应该看到
[Linter] 修复成功: {...}
```

### 2. 检查具体问题
在控制台查看这两个文献的 issues：
```javascript
// 应该能看到类似：
issues: [
  { field: "title", severity: "warning", message: "...", current: "...", suggested: "..." },
  ...
]
```

### 3. 后端日志
查看后端终端输出，看是否有错误

## 💡 可能的原因和解决方案

### 原因1：文献标题缺失
如果文献只有 PDF，没有提取标题，Linter 可能无法修复。

**解决方案：**
- 添加规则跳过缺失字段
- 或者先运行 PDF 提取再运行 Linter

### 原因2：某些规则匹配但无法修复
例如：
- 日期格式无法识别
- 作者名格式特殊

**解决方案：**
- 改进规则逻辑
- 添加更多格式支持

### 原因3：前端没有正确更新
修复成功但前端没有刷新。

**解决方案：**
```typescript
// 修复后重新检查
await applyFixes(materialId);
await handleCheck(); // 重新检查整个项目
```

## 🚀 快速修复方案

### 修改前端：修复后自动重新检查

编辑 `MetadataLinterPanel.tsx`：

```typescript
// 在 applyFixes 函数的最后
if (onComplete) onComplete();

// 改为
if (onComplete) onComplete();

// 修复成功后，从结果列表中移除该文献（如果没有问题了）
setResults(prev => prev.filter(r => {
  if (r.material_id === materialId) {
    return data.result.issues.length > 0; // 只保留仍有问题的
  }
  return true;
}));
```

或者更简单：

```typescript
// 修复成功后，重新检查整个项目
if (data.result.issues.length === 0) {
  // 从列表中移除
  setResults(prev => prev.filter(r => r.material_id !== materialId));
}
```

## 📋 下一步行动

1. **立即**：添加诊断日志，找出问题根因
2. **短期**：修复逻辑，确保修复后正确更新
3. **中期**：集成任务中心（2-3小时工作量）

---

## 🎯 任务中心集成（未来）

由于这是一个独立的功能，建议作为下一个独立任务：

**预计工作量：** 2-3 小时

**主要步骤：**
1. 创建 LinterTask 类（30 min）
2. 修改 API 为异步（30 min）
3. 前端集成任务中心（60 min）
4. 测试和优化（30 min）

**收益：**
- 不阻塞 UI
- 批量处理更快
- 可查看历史
- 更好的用户体验

---

建议先解决当前的"修复后仍显示问题"bug，然后再考虑任务中心集成。
