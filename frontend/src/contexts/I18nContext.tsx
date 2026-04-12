import React, { createContext, useContext, useState, ReactNode } from 'react';

type Language = 'zh' | 'en';

interface I18nContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

const translations: Record<Language, Record<string, string>> = {
  zh: {
    'writing.outline': '论文大纲',
    'writing.notes': '单元备注',
    'writing.no_notes': '暂无备注',
    'writing.save': '同步云端',
    'writing.unsaved': '未同步',
    'writing.pending_apply': '待应用',
    'writing.original': '原始文稿',
    'writing.preview_rewrite': '重构预览',
    'writing.apply_and_close': '应用并合并',
    'writing.cancel': '放弃变更',
    'writing.ai_processing': 'AI 深度重构中...',
    'writing.manual_edit_tip': '手动编辑可实时保存预览',
    'writing.real_time_saved': '编辑已实时暂存',
    'writing.placeholder': '在此开始您的创作...',
    'writing.materials_library': '素材智库',
    'writing.no_materials': '尚未通过 RAG 挂载素材',
    'writing.actions.processing_actions': '辅助行动',
    'writing.actions.revision_history': '历史快照',
    'writing.no_revisions': '暂无历史快照',
    'writing.mode': '输出格式',
    'writing.section': '当前章节',
    'writing.words': '字数统计',
    'writing.translate': '翻译辅助',
    'writing.rewrite': '精雕细琢',
    'writing.check': '质量核查',
    'writing.generate': '内容辅助',
    'writing.auto_save': '自动保存',
    'writing.before_rewrite': '执行动作前',
    'writing.references': '参考素材',
    'writing.comparison': '双窗对比',
  },
  en: {
    'writing.outline': 'Outline',
    'writing.notes': 'Section Notes',
    'writing.no_notes': 'No notes',
    'writing.save': 'Sync Cloud',
    'writing.unsaved': 'Unsynced',
    'writing.pending_apply': 'Pending',
    'writing.original': 'Original',
    'writing.preview_rewrite': 'Optimized',
    'writing.apply_and_close': 'Apply & Merge',
    'writing.cancel': 'Discard',
    'writing.ai_processing': 'AI Reimagining...',
    'writing.manual_edit_tip': 'Manual edits are autosaved',
    'writing.real_time_saved': 'Edits saved locally',
    'writing.placeholder': 'Start creating here...',
    'writing.materials_library': 'Intel Library',
    'writing.no_materials': 'No materials attached',
    'writing.actions.processing_actions': 'Core Actions',
    'writing.actions.revision_history': 'Snapshots',
    'writing.no_revisions': 'No snapshots available',
    'writing.mode': 'Format',
    'writing.section': 'Section',
    'writing.words': 'Word Count',
    'writing.translate': 'Translate',
    'writing.rewrite': 'Creative Polish',
    'writing.check': 'Validation',
    'writing.generate': 'Assistance',
    'writing.auto_save': 'Auto Save',
    'writing.before_rewrite': 'Pre-transform',
    'writing.references': 'References',
    'writing.comparison': 'Compare',
  }
};

const I18nContext = createContext<I18nContextType | undefined>(undefined);

export const I18nProvider = ({ children }: { children: ReactNode }) => {
  const [language, setLanguage] = useState<Language>('zh');

  const t = (key: string) => {
    return translations[language][key] || key;
  };

  return (
    <I18nContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </I18nContext.Provider>
  );
};

export const useI18n = () => {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used within I18nProvider');
  return context;
};
