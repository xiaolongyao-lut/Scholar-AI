import zhMessages from '../locales/zh.json';

const dict = zhMessages as unknown as Record<string, string>;

/**
 * 纯中文文案查找，无语言切换。
 */
export function t(key: string, params?: Record<string, string | number>): string {
  let text = dict[key] ?? key;
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
