# Linter 任务中心集成方案

## 问题分析

当前问题：
1. Linter 检查时会阻塞 UI（同步操作）
2. 用户无法看到进度
3. 用户无法取消正在运行的检查
4. 多个文献检查时体验不好

## 解决方案：集成到任务中心

### 1. 后端改造

#### 创建 Linter 任务类型
```python
# literature_assistant/core/task_types.py (新增)
class LinterTask:
    task_type = "linter"
    
    async def execute(self, project_id: str, material_ids: list[str] | None):
        # 批量检查文献
        # 更新进度
        # 返回结果
```

#### API 端点改造
```python
# POST /api/linter/lint/batch (修改)
# 不再同步返回结果，而是创建任务
@router.post("/lint/batch")
async def lint_batch_async(request: BatchLintRequest):
    task = create_task(
        task_type="linter",
        params={"project_id": request.project_id, "material_ids": request.material_ids}
    )
    return {"task_id": task.task_id}

# GET /api/linter/tasks/{task_id}/result
# 获取任务结果
```

### 2. 前端改造

#### MetadataLinterPanel 改造
```typescript
// 点击"检查"按钮后
const handleCheck = async () => {
  const { task_id } = await api.post('/api/linter/lint/batch', {...});
  
  // 跳转到任务中心
  router.push(`/tasks?task_id=${task_id}`);
  
  // 或者显示通知
  toast.info('已开始检查，请到任务中心查看进度');
};
```

#### 任务中心显示
- 任务类型：元数据检查
- 进度：已检查 5/10 条文献
- 状态：运行中 / 完成 / 失败
- 结果：点击查看详情

### 3. 实现优先级

#### Phase 1（立即）- 最小改动
1. 保持当前 UI 不变
2. 只修复"修复失败"的 bug
3. 添加 loading 状态

#### Phase 2（下次）- 任务中心集成
1. 后端创建 Linter 任务类型
2. API 改为异步
3. 前端集成任务中心
4. 添加进度显示

## 建议

**当前阶段**：先修复 bug，保持简单
**下一阶段**：完整集成任务中心（需要 2-3 小时）

这样用户体验会更好：
- 不阻塞 UI
- 可以后台运行
- 可以查看历史记录
- 可以取消任务

---

## 快速修复方案（当前）

只需要修改前端，添加更好的状态提示：

```typescript
// 添加 loading 状态
{checking && (
  <div className="text-xs text-muted-foreground">
    正在检查... ({checkedCount}/{totalCount})
  </div>
)}

// 修复失败时提供更多信息
{error && (
  <div className="text-xs text-destructive">
    {error.includes('没有可应用') 
      ? '文献已经是清洁状态' 
      : `修复失败: ${error}`
    }
  </div>
)}
```
