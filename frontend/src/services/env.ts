const ALLOWED_ENV_KEYS: ReadonlySet<keyof ImportMetaEnv> = new Set([
  'VITE_API_BASE_URL',
  'VITE_ENABLE_CONTEXTUAL',
  'VITE_ENABLE_DEV_ROUTES',
  'VITE_ENABLE_SAMPLING_PANEL',
  'VITE_FLAG_RESEARCH_WORKBENCH',
  'VITE_SMART_READ_DEBUG',
]);

export const readEnv = (key: keyof ImportMetaEnv): string => {
  if (!ALLOWED_ENV_KEYS.has(key)) {
    return '';
  }
  const viteEnv = import.meta.env?.[key];
  return typeof viteEnv === 'string' ? viteEnv.trim() : '';
};
