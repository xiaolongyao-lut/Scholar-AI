import zhMessages from '../locales/zh.json';

const dict = zhMessages as unknown as Record<string, string>;

/** Marker rendered when a translation key is missing in production. R5
 *  forbids leaking the raw English-shaped key (e.g. "nav.help_docs")
 *  to end users; dev-mode falls back to the key with a warning prefix
 *  so the gap is easy to spot locally. */
const MISSING_FALLBACK = '[未翻译]';

const warnedMissing = new Set<string>();

/**
 * 纯中文文案查找，无语言切换。
 *
 * 不允许把英文 key 直接渲染到 UI。如果字典缺少 key，开发环境会在
 * console 打一次 warn 并退化为 `key (未翻译)`，便于补齐；生产环境
 * 退化为 `[未翻译]` 保证 R5/R5.1 — 用户永远看不到点号分隔的英文
 * 键名（看起来像源码标识符）。
 */
export function t(key: string, params?: Record<string, string | number>): string {
  let text: string;
  if (Object.prototype.hasOwnProperty.call(dict, key)) {
    text = dict[key];
  } else {
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV && !warnedMissing.has(key)) {
      warnedMissing.add(key);
      console.warn(`[i18n] missing zh key: ${key}`);
      text = `${MISSING_FALLBACK} ${key}`;
    } else {
      text = MISSING_FALLBACK;
    }
  }
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), String(v));
    });
  }
  return text;
}

/** @deprecated 兼容旧代码，后续可逐步替换为直接 import { t } */
export function useI18n() {
  return { t } as const;
}
