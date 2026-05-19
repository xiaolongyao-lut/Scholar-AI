import React from 'react';
import { motion } from 'framer-motion';
import { Layers, CheckCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { ManuscriptSection } from '@/types/writing';

interface OutlineNavigatorProps {
  sections: ManuscriptSection[];
}

export function OutlineNavigator({ sections }: OutlineNavigatorProps) {
  const { t } = useI18n();
  const { activeSectionId, setActiveSectionId, zenMode } = useWriting();

  return (
    <motion.div 
      initial={{ x: -20, opacity: 0 }}
      animate={{ 
        x: 0, 
        opacity: zenMode ? 0.1 : 1,
        pointerEvents: zenMode ? 'none' : 'auto'
      }}
      className="w-64 border-r border-outline-variant bg-surface-low flex flex-col transition-opacity duration-500"
    >
      <div className="p-5 border-b border-outline-variant flex items-center gap-2">
        <Layers size={14} className="text-primary" />
        <span className="font-label text-[10px] font-medium uppercase tracking-wider text-foreground/50">
          {t('writing.outline')}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {sections.map(sec => (
          <button
            key={sec.id}
            onClick={() => setActiveSectionId(sec.id)}
            aria-label={sec.titleZh}
            className={cn(
              "w-full px-5 py-4 flex items-center gap-3 transition-all border-l-2",
              activeSectionId === sec.id 
                ? "bg-surface-lowest border-primary text-primary" 
                : "border-transparent text-foreground/60 hover:bg-surface-lowest/50"
            )}
          >
            <CheckCircle 
              size={14} 
              className={activeSectionId === sec.id ? "text-primary" : "text-foreground/20"} 
            />
            <span className="font-label text-xs font-medium truncate flex-1 text-left">
              {sec.titleZh}
            </span>
          </button>
        ))}
      </div>
    </motion.div>
  );
}
