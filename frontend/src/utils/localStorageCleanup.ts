// localStorage 数据清理工具
// 用于隐私保护：一键清除研究内容、聊天记录、查询历史

/**
 * localStorage 使用清单（从代码审计）：
 *
 * - SmartReadContext.tsx:600-635 — 智能阅读状态
 * - Workbench.tsx:217-370 — 工作台状态
 * - Inspiration.tsx:296-364 — 灵感记录
 * - DiscussionContext.tsx:137-164 — 讨论上下文
 * - Dialog.tsx:1732-1752 — 对话历史
 * - settingsStore.ts:107-158 — 设置（相对谨慎）
 * - CredentialsSection.tsx:396-420 — 凭证绑定（相对谨慎）
 *
 * 风险：
 * - XSS 可读取所有 localStorage
 * - 浏览器缓存/历史可能泄露
 * - 多用户共享设备风险
 *
 * 建议：
 * 1. 提供一键清除功能（设置页面）
 * 2. 隐私模式（不持久化敏感数据）
 * 3. 保留期限（7/30/90 天自动清理）
 * 4. 容量上限（警告 + 自动清理最旧数据）
 */

export interface LocalStorageClearOptions {
  /** 清除研究内容（工作台、灵感、智能阅读） */
  clearResearchContent?: boolean;
  /** 清除聊天历史 */
  clearChatHistory?: boolean;
  /** 清除设置 */
  clearSettings?: boolean;
  /** 清除凭证 */
  clearCredentials?: boolean;
}

/**
 * 清除 localStorage 中的敏感数据
 *
 * @example
 * // 清除所有研究内容和聊天历史，保留设置
 * clearLocalStorage({ clearResearchContent: true, clearChatHistory: true });
 */
export function clearLocalStorage(options: LocalStorageClearOptions): void {
  const keysToRemove: string[] = [];

  if (options.clearResearchContent) {
    // 研究内容相关 keys（需要根据实际代码确认 key 名称）
    const researchKeys = [
      'smart-read-state',
      'workbench-state',
      'inspiration-state',
      'discussion-state',
      // 添加其他研究内容相关 keys
    ];
    keysToRemove.push(...researchKeys);
  }

  if (options.clearChatHistory) {
    const chatKeys = [
      'chat-history',
      'dialog-history',
      // 添加其他聊天历史相关 keys
    ];
    keysToRemove.push(...chatKeys);
  }

  if (options.clearSettings) {
    const settingsKeys = [
      'app-settings',
      // 添加其他设置相关 keys
    ];
    keysToRemove.push(...settingsKeys);
  }

  if (options.clearCredentials) {
    const credentialKeys = [
      'credential-bindings',
      // 添加其他凭证相关 keys
    ];
    keysToRemove.push(...credentialKeys);
  }

  // 执行清除
  for (const key of keysToRemove) {
    try {
      localStorage.removeItem(key);
    } catch (err) {
      console.error(`Failed to remove localStorage key: ${key}`, err);
    }
  }

  console.log(`Cleared ${keysToRemove.length} localStorage keys`);
}

/**
 * 获取 localStorage 使用情况统计
 */
export function getLocalStorageStats(): {
  totalKeys: number;
  totalSizeBytes: number;
  keysBySize: Array<{ key: string; sizeBytes: number }>;
} {
  const keys = Object.keys(localStorage);
  const keysBySize: Array<{ key: string; sizeBytes: number }> = [];
  let totalSize = 0;

  for (const key of keys) {
    try {
      const value = localStorage.getItem(key) || '';
      const sizeBytes = new Blob([value]).size;
      keysBySize.push({ key, sizeBytes });
      totalSize += sizeBytes;
    } catch (err) {
      console.error(`Failed to measure localStorage key: ${key}`, err);
    }
  }

  keysBySize.sort((a, b) => b.sizeBytes - a.sizeBytes);

  return {
    totalKeys: keys.length,
    totalSizeBytes: totalSize,
    keysBySize,
  };
}

/**
 * 检查 localStorage 是否接近容量限制（通常 5-10 MB）
 * 返回 true 表示应该清理旧数据
 */
export function isLocalStorageNearLimit(): boolean {
  const stats = getLocalStorageStats();
  const WARN_THRESHOLD = 8 * 1024 * 1024; // 8 MB
  return stats.totalSizeBytes > WARN_THRESHOLD;
}

/**
 * 自动清理最旧的数据（保留最近的 N 条记录）
 *
 * 注意：需要实现时间戳追踪逻辑
 */
export function autoCleanOldData(retentionDays: number = 30): void {
  const _cutoffTime = Date.now() - retentionDays * 24 * 60 * 60 * 1000;

  // TODO: 实现基于时间戳的清理逻辑
  // 需要在写入 localStorage 时同时存储时间戳

  console.warn('Auto-clean not implemented yet. Retention days:', retentionDays);
}
