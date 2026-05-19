const readProcessEnv = (key: string): string => {
  if (typeof process === 'undefined' || !process.env) {
    return '';
  }

  const value = process.env[key];
  return typeof value === 'string' ? value.trim() : '';
};

export const readEnv = (key: keyof ImportMetaEnv): string => {
  const viteEnv = import.meta.env?.[key];
  if (typeof viteEnv === 'string') {
    return viteEnv.trim();
  }

  return readProcessEnv(String(key));
};
