# 删除云端备份反馈机制 实施方案

## 1. 背景与目标
【功能名称】backup-deletion-feedback
【背景】当前系统在前端控制面板点击删除云端备份包时，仅仅触发了后台接口请求，期间按钮没有任何加载或锁定状态。由于 WebDAV/S3 等云端删除操作受网络延迟影响，用户在等待页面刷新前无法感知是否正在删除，且删除成功后没有明确的成功提示，影响了交互体验。
【目标】完善删除云端备份时的前端交互反馈，实现过程有进度、结果有提示。
【核心功能点】
1. **删除进度提示**：点击删除后，被删除项的删除按钮变为 Loading 状态（Spin 动画），并禁用点击，防止重复提交。
2. **结果通知**：接口请求成功并刷新列表后，给予用户明确的成功状态提示（Action Feedback）；若失败则继续抛出错误提示。
【边界】
纯前端交互优化，不涉及后端删除逻辑或接口协议的修改。
【关键假设】
已有的 `api.deleteBackup` 接口能正常返回 Promise 的 resolved / rejected 状态以供前端捕获。

## 2. 需求分析
### 2.1 功能需求
- 交互流：点击垃圾桶 -> 弹出 Confirm -> 用户确认 -> 该条目的垃圾桶变为 Loading 图标 -> 发起 API 请求 -> 请求成功 -> 列表刷新并显示成功 Toast -> Loading 状态解除。
### 2.2 非功能需求
- 代码健壮性：即使网络极度缓慢或请求超时报错，Loading 状态最终也需被正确清除（在 `finally` 块或 `catch` 块中处理）。

## 3. 技术方案
### 3.1 状态管理
在 `frontend/src/components/BackupRestorePanel.tsx` 中新增状态：
```typescript
const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
```

### 3.2 逻辑设计
修改 `handleDeleteBackup`：
```typescript
const handleDeleteBackup = async (filename: string) => {
  if (!confirm(`确定要从远端存储永久删除备份包「${filename}」吗？`)) return;
  
  setDeletingFilename(filename);
  try {
    await api.deleteBackup(filename);
    await refreshBackupsList();
    setActionFeedback({ type: "success", message: `成功删除备份: ${filename}` });
  } catch (err: any) {
    setActionFeedback({ type: "error", message: err.message || "删除备份失败" });
  } finally {
    setDeletingFilename(null);
  }
};
```

### 3.3 UI 渲染
在备份列表的渲染循环中，判断当前遍历的 `bk.name === deletingFilename`，若是，则替换 `Trash2` 图标为 `Loader2 className="animate-spin"`，并禁用 `button`。

## 4. 实施计划
| 任务 | 描述 | 优先级 | 预估复杂度 | 依赖 |
|------|------|--------|-----------|------|
| 1 | 前端新增 `deletingFilename` 状态，并更新删除函数以支持成功反馈及重置状态 | P0 | S | 无 |
| 2 | 更新列表循环中删除按钮的渲染逻辑，增加 Loading 转圈及按钮锁定效果 | P0 | S | 任务1 |

## 5. 风险与应对
| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 连续点击删除多个文件 | 可能会产生并发问题或列表刷新冲突 | 低 | 由于使用了 `deletingFilename` 为单个 string 状态，同时只允许锁定一个删除请求。若需要支持并发删除可改为 `Set<string>`，但对于备份删除这种低频高危操作，锁定为单线程删除已满足需求且更安全。 |

## 6. 验收标准
- [ ] 点击某个备份包的删除按钮并确认后，该按钮立即变成旋转的加载图标，不可再次点击。
- [ ] 删除成功后，页面顶部的 `ActionFeedback` 显示绿色成功提示。
- [ ] 删除失败后，页面顶部的 `ActionFeedback` 显示红色错误提示，加载图标恢复为普通删除图标。
