import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, X, ExternalLink, ArrowRight, Link2, Target } from 'lucide-react';
import { useI18n } from '@/contexts/I18nContext';
import { WritingMaterial, CitationAnchor } from '@/types/writing';
import { cn } from '@/lib/utils';

interface ReferenceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  materials: WritingMaterial[];
  citationAnchors: CitationAnchor[];
  citationCountByMaterial: Record<string, number>;
  activeMaterialId: string | null;
  activeCitationAnchorId: string | null;
  onRequestCitationInsertion: (materialId: string | null) => void;
  onRequestAnchorFocus: (anchorId: string, materialId: string | null) => void;
  onSelectMaterial: (materialId: string | null) => void;
}

export function ReferenceDrawer({
  isOpen,
  onClose,
  materials,
  citationAnchors,
  citationCountByMaterial,
  activeMaterialId,
  activeCitationAnchorId,
  onRequestCitationInsertion,
  onRequestAnchorFocus,
  onSelectMaterial,
}: ReferenceDrawerProps) {
  const { t } = useI18n();

  const anchorsByMaterial = React.useMemo(() => {
    return citationAnchors.reduce<Record<string, CitationAnchor[]>>((acc, anchor) => {
      const key = anchor.materialId || '__unbound__';
      acc[key] = acc[key] || [];
      acc[key].push(anchor);
      return acc;
    }, {});
  }, [citationAnchors]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div 
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          id="reference-drawer"
          role="complementary"
          aria-labelledby="reference-drawer-title"
          className="absolute right-0 top-0 bottom-0 w-[400px] bg-surface-lowest border-l border-outline-variant z-50 shadow-[-8px_0_24px_rgba(0,0,0,0.06)] flex flex-col"
        >
          <div className="p-6 border-b border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-3">
               <div className="p-2 bg-primary/10 text-primary rounded-sm">
                 <BookOpen size={20} />
               </div>
               <h3 id="reference-drawer-title" className="font-headline font-semibold text-base text-foreground">
                 {t('writing.materials_library')}
               </h3>
            </div>
            <button 
              onClick={onClose} 
              aria-label={t('writing.materials.close_aria')}
              className="p-2 hover:bg-surface-container rounded-sm transition-colors"
            >
              <X size={20} />
            </button>
          </div>
          
          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-4">
            {materials.length === 0 && (
              <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low px-5 py-6 text-center">
                <p className="font-headline text-sm font-semibold text-foreground">{t('writing.no_materials')}</p>
                <p className="mt-2 font-body text-[11px] leading-5 text-foreground/50">
                  {t('writing.materials.empty_description')}
                </p>
              </div>
            )}
            {materials.map(mat => (
              (() => {
                const anchorsForMaterial = anchorsByMaterial[mat.id] || [];
                const citationCount = citationCountByMaterial[mat.id] || 0;
                const isActive = activeMaterialId === mat.id || anchorsForMaterial.some((anchor) => anchor.id === activeCitationAnchorId);

                return (
              <div 
                key={mat.id} 
                className={cn(
                  'glass-card p-5 rounded-sm group border transition-all hover:shadow-md',
                  isActive ? 'border-primary/30 shadow-md bg-primary/5' : 'border-transparent hover:border-primary/20'
                )}
              >
                 <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <span className="font-label text-[8px] font-medium uppercase px-2 py-0.5 bg-primary/10 text-primary rounded-sm tracking-wider">
                        {mat.type}
                      </span>
                      {citationCount > 0 && (
                        <span className="font-label text-[8px] font-medium uppercase px-2 py-0.5 rounded-sm tracking-wider bg-emerald-100 text-emerald-700">
                          {t('writing.ref.cited_count', { count: citationCount })}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => onSelectMaterial(mat.id)}
                      className="p-1.5 rounded-sm text-foreground/30 hover:text-primary hover:bg-surface-container transition-colors"
                      aria-label={t('writing.ref.focus_material_aria', { title: mat.titleZh })}
                      title={t('writing.ref.focus_material')}
                    >
                      <Target size={12} />
                    </button>
                 </div>
                 <h5 className="font-headline text-[13px] font-semibold mb-2 group-hover:text-primary transition-colors leading-snug text-foreground">
                   {mat.titleZh}
                 </h5>
                 <p className="font-body text-[11px] text-foreground/60 leading-relaxed line-clamp-3 mb-4">
                   {mat.summaryZh}
                 </p>
                 {anchorsForMaterial.length > 0 && (
                   <div className="mb-4 flex flex-wrap gap-2">
                     {anchorsForMaterial.slice(0, 3).map((anchor) => (
                       <button
                         type="button"
                         key={anchor.id}
                         onClick={() => onRequestAnchorFocus(anchor.id, mat.id)}
                         title={t('writing.ref.locate_anchor', { ordinal: anchor.ordinal })}
                         aria-label={t('writing.ref.locate_anchor_aria', { ordinal: anchor.ordinal })}
                         className={cn(
                           'inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 font-label text-[9px] font-medium transition-all',
                           activeCitationAnchorId === anchor.id
                             ? 'border-primary/30 bg-primary/10 text-primary'
                             : 'border-outline-variant bg-surface-lowest text-foreground/50 hover:border-primary/20 hover:text-foreground'
                         )}
                       >
                         <Link2 size={10} />
                         <span>#{anchor.ordinal}</span>
                       </button>
                     ))}
                     {anchorsForMaterial.length > 3 && (
                       <span className="inline-flex items-center rounded-sm border border-outline-variant bg-surface-low px-2.5 py-1 font-label text-[9px] font-medium text-foreground/40">
                         +{anchorsForMaterial.length - 3}
                       </span>
                     )}
                   </div>
                 )}
                 <div className="flex flex-wrap gap-1.5">
                    {(mat.focusPointsZh).map((fp, idx) => (
                       <span 
                         key={idx} 
                         className="font-label text-[9px] font-medium px-2 py-0.5 bg-surface-low rounded-sm border border-outline-variant/50"
                       >
                         {fp}
                       </span>
                    ))}
                 </div>
                 <div className="mt-4 flex flex-wrap gap-2">
                   <button
                     type="button"
                     onClick={() => onRequestCitationInsertion(mat.id)}
                     className="inline-flex items-center gap-1.5 rounded-sm bg-primary px-3 py-1.5 font-label text-[10px] font-medium text-primary-foreground transition-all hover:bg-primary/90"
                     aria-label={t('writing.ref.insert_citation_aria', { title: mat.titleZh })}
                   >
                     <ArrowRight size={10} />
                     {t('writing.ref.insert_citation')}
                   </button>
                   <button
                     type="button"
                     onClick={() => {
                       onSelectMaterial(mat.id);
                       if (anchorsForMaterial[0]) {
                         onRequestAnchorFocus(anchorsForMaterial[0].id, mat.id);
                       }
                     }}
                     disabled={!anchorsForMaterial.length}
                     className="inline-flex items-center gap-1.5 rounded-sm border border-outline-variant bg-surface-lowest px-3 py-1.5 font-label text-[10px] font-medium text-foreground/60 transition-all hover:text-foreground hover:border-primary/20 disabled:cursor-not-allowed disabled:opacity-40"
                     aria-label={anchorsForMaterial.length ? t('writing.ref.locate_first_aria', { title: mat.titleZh }) : t('writing.ref.no_anchor_aria', { title: mat.titleZh })}
                   >
                     <ExternalLink size={10} />
                     {t('writing.ref.locate_text')}
                   </button>
                 </div>
              </div>
                );
              })()
            ))}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
