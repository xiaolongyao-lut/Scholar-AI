import type { ManuscriptSection } from '@/types/resources';

export function getLocalizedSectionTitle(sec: ManuscriptSection, lang: string, t: (key: string) => string): string {
  if (lang === 'zh') return sec.titleZh || t('writing.section');
  return sec.titleEn || t('writing.section');
}
