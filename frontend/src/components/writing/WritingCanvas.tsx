import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Save, Loader2, BookOpen, Diff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import {
  getEvidenceReferenceBody,
  getEvidenceReferenceMetaParts,
  getEvidenceReferenceTitle,
  getEvidenceReferenceWikiUrl,
} from '@/lib/evidenceReferences';
import {
  ManuscriptSection,
  DraftContent,
  TransformResult,
  WritingMaterial,
  CitationAnchor,
  CitationInsertRequest,
  CitationFocusRequest,
} from '@/types/writing';
import {
  createCitationAnchorId,
  createCitationToken,
  findCitationAnchorRange,
  getCitationAnchorInstanceId,
  getCitationAnchorLabel,
} from '@/lib/citationAnchors';

interface WritingCanvasProps {
  activeSection: ManuscriptSection | undefined;
  draft: DraftContent | null;
  setDraft: React.Dispatch<React.SetStateAction<DraftContent | null>>;
  isDirty: boolean;
  setIsDirty: (dirty: boolean) => void;
  saving: boolean;
  handleSave: () => void;
  showReferences: boolean;
  setShowReferences: (show: boolean) => void;
  showComparison: boolean;
  setShowComparison: (show: boolean) => void;
  transformResult: TransformResult | null;
  setTransformResult: (result: TransformResult | null) => void;
  handleApplyResult: () => void;
  materials: WritingMaterial[];
  citationAnchors: CitationAnchor[];
  citationCountByMaterial: Record<string, number>;
  activeCitationAnchorInstanceId: string | null;
  focusedMaterialId: string | null;
  citationInsertRequest: CitationInsertRequest | null;
  citationFocusRequest: CitationFocusRequest | null;
  onRequestCitationInsertion: (materialId: string | null) => void;
  onRequestAnchorFocus: (anchor: CitationAnchor) => void;
  onCitationInsertHandled: (requestId: string, anchorInstanceId: string, materialId: string | null) => void;
  onCitationFocusHandled: (requestId: string) => void;
}

export function WritingCanvas({
  activeSection,
  draft,
  setDraft,
  isDirty,
  setIsDirty,
  saving,
  handleSave,
  showReferences,
  setShowReferences,
  showComparison,
  setShowComparison,
  transformResult,
  setTransformResult,
  handleApplyResult,
  materials,
  citationAnchors,
  citationCountByMaterial,
  activeCitationAnchorInstanceId,
  focusedMaterialId,
  citationInsertRequest,
  citationFocusRequest,
  onRequestCitationInsertion,
  onRequestAnchorFocus,
  onCitationInsertHandled,
  onCitationFocusHandled,
}: WritingCanvasProps) {
  const { t } = useI18n();
  const {
    zenMode,
    setZenMode,
    connectionState,
    sessionStatus,
    sessionMessage,
    setSessionMessage,
    setSessionStatus,
  } = useWriting();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingSelectionRef = useRef<{ start: number; end: number } | null>(null);
  const handledInsertRequestRef = useRef<string | null>(null);
  const handledFocusRequestRef = useRef<string | null>(null);

  const materialLookup = useMemo(() => {
    return new Map(materials.map((material) => [material.id, material] as const));
  }, [materials]);

  const connectionBadge = {
    online: { label: t('writing.canvas.online'), className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' },
    degraded: { label: t('writing.canvas.degraded'), className: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300' },
    offline: { label: t('writing.canvas.offline'), className: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300' },
  }[connectionState];

  useEffect(() => {
    const request = citationInsertRequest;

    if (!draft || !request || handledInsertRequestRef.current === request.requestId) {
      return;
    }

    const editor = textareaRef.current;
    const content = draft.content || '';
    const cursorEnd = editor?.selectionEnd ?? content.length;
    const anchorId = createCitationAnchorId(request.materialId);
    const token = createCitationToken(anchorId);
    const before = content.slice(0, cursorEnd);
    const after = content.slice(cursorEnd);
    const needsSpaceBefore = before.length > 0 && !/\s$/.test(before);
    const needsSpaceAfter = after.length > 0 && !/^\s/.test(after);
    const insertText = `${needsSpaceBefore ? ' ' : ''}${token}${needsSpaceAfter ? ' ' : ''}`;
    const tokenStartOffset = cursorEnd + (needsSpaceBefore ? 1 : 0);
    const anchorInstanceId = getCitationAnchorInstanceId(anchorId, tokenStartOffset);
    const nextContent = `${before}${insertText}${after}`;
    const nextCursor = cursorEnd + insertText.length;
    const materialLabel = request.materialId ? materialLookup.get(request.materialId)?.titleZh || request.materialId : t('writing.canvas.unbound');

    handledInsertRequestRef.current = request.requestId;
    pendingSelectionRef.current = { start: nextCursor, end: nextCursor };

    setDraft((prev) => prev ? {
      ...prev,
      content: nextContent,
      wordCount: nextContent.split(/\s+/).filter(Boolean).length,
      isDirty: true,
    } : null);
    setIsDirty(true);
    setSessionStatus('idle');
    setSessionMessage(t('writing.canvas.citation_inserted', { label: materialLabel }));
    onCitationInsertHandled(request.requestId, anchorInstanceId, request.materialId);
  }, [citationInsertRequest, draft, materialLookup, onCitationInsertHandled, setDraft, setIsDirty, setSessionMessage, setSessionStatus]);

  useEffect(() => {
    if (!pendingSelectionRef.current || !textareaRef.current) {
      return;
    }

    const { start, end } = pendingSelectionRef.current;
    const editor = textareaRef.current;
    editor.focus();
    editor.setSelectionRange(start, end);
    pendingSelectionRef.current = null;
  }, [draft?.content]);

  useEffect(() => {
    const request = citationFocusRequest;

    if (!draft || !request || handledFocusRequestRef.current === request.requestId) {
      return;
    }

    const range = findCitationAnchorRange(draft.content || '', request.anchorId, request.anchorStartOffset);

    handledFocusRequestRef.current = request.requestId;

    if (!range) {
      setSessionStatus('error');
      setSessionMessage(t('writing.canvas.citation_not_found'));
      onCitationFocusHandled(request.requestId);
      return;
    }

    const editor = textareaRef.current;
    if (editor) {
      editor.focus();
      editor.setSelectionRange(range.startOffset, range.endOffset);
    }

    setSessionMessage(request.materialId ? t('writing.canvas.citation_located') : t('writing.canvas.anchor_located'));
    onCitationFocusHandled(request.requestId);
  }, [citationFocusRequest, draft, onCitationFocusHandled, setSessionMessage, setSessionStatus]);

  const handleRequestCitationInsertion = () => {
    onRequestCitationInsertion(focusedMaterialId);
  };

  const handleAnchorChipClick = (anchor: CitationAnchor) => {
    onRequestAnchorFocus(anchor);
  };

  const activeMaterial = focusedMaterialId ? materialLookup.get(focusedMaterialId) : null;
  const activeAnchor = citationAnchors.find((anchor) => anchor.instanceId === activeCitationAnchorInstanceId) || null;

  const saveLabel = saving
    ? t('writing.canvas.saving')
    : sessionStatus === 'error'
      ? t('writing.canvas.retry_save')
      : isDirty
        ? t('writing.save')
        : t('writing.canvas.saved');

  const saveButtonClass = sessionStatus === 'error'
    ? 'bg-destructive text-destructive-foreground'
    : isDirty
      ? 'bg-primary text-primary-foreground'
      : 'bg-surface-container text-foreground/30';

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-surface relative transition-all duration-500">
      {/* Canvas Header */}
      <motion.header 
        animate={{ opacity: zenMode ? 0.1 : 1 }}
        className="h-14 px-6 flex items-center justify-between border-b border-outline-variant bg-surface-lowest sticky top-0 z-10"
      >
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-3 min-w-0">
             <h3 className="font-headline font-semibold text-sm truncate max-w-[240px] text-foreground">
                {activeSection?.titleZh || t('writing.canvas.untitled')}
             </h3>
             <span className={cn("font-label text-[10px] font-medium px-2 py-0.5 rounded-sm uppercase tracking-wider", connectionBadge.className)}>
               {connectionBadge.label}
             </span>
             {isDirty && (
               <span className="font-label text-[10px] bg-amber-100 text-amber-700 font-medium px-2 py-0.5 rounded-sm uppercase tracking-wider fade-in">
                 {t('writing.unsaved')}
               </span>
             )}
          </div>
          {sessionMessage && (
            <p className={cn(
              "font-label text-[10px] font-medium truncate max-w-[420px]",
              sessionStatus === 'error' ? 'text-destructive' : 'text-foreground/50'
            )}>
              {sessionMessage}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
           {showReferences ? (
           <button 
              onClick={() => setShowReferences(false)}
              title={t('writing.materials_library')}
              aria-label={t('writing.materials_library')}
              aria-expanded="true"
              aria-haspopup="dialog"
              className="p-2 rounded-sm transition-all bg-primary text-primary-foreground"
           >
              <BookOpen size={18} />
           </button>
           ) : (
           <button 
              onClick={() => setShowReferences(true)}
              title={t('writing.materials_library')}
              aria-label={t('writing.materials_library')}
              aria-expanded="false"
              aria-haspopup="dialog"
              className="p-2 rounded-sm transition-all hover:bg-surface-container text-foreground/50"
           >
              <BookOpen size={18} />
           </button>
           )
           }
           <button 
              onClick={handleRequestCitationInsertion}
              title={activeMaterial ? t('writing.canvas.insert_cite', { title: activeMaterial.titleZh }) : t('writing.canvas.insert_cite_generic')}
              aria-label={activeMaterial ? t('writing.canvas.insert_cite', { title: activeMaterial.titleZh }) : t('writing.canvas.insert_cite_generic')}
              className="p-2 rounded-sm hover:bg-surface-container text-foreground/50 transition-all"
           >
              <div className="flex flex-col items-center justify-center leading-none min-w-[38px]">
                <span className="font-label text-[8px] font-medium">{t('writing.canvas.cite_label')}</span>
                <span className="text-[10px] shrink-0">{activeMaterial ? t('writing.canvas.material_selected') : '[^1]'}</span>
              </div>
           </button>
           <button 
              onClick={() => setShowComparison(!showComparison)}
              disabled={!transformResult}
              title={t('writing.preview_rewrite')}
              aria-label={t('writing.preview_rewrite')}
              className={cn(
                "p-2 rounded-sm transition-all", 
                showComparison ? "bg-primary text-primary-foreground" : "hover:bg-surface-container text-foreground/50 disabled:opacity-20 disabled:cursor-not-allowed"
              )}
           >
              <Diff size={18} />
           </button>
           {zenMode ? (
           <button
              type="button"
              onClick={() => setZenMode(false)}
              aria-pressed="true"
              title={t('writing.canvas.zen_exit')}
              aria-label={t('writing.canvas.zen_exit')}
              className="px-3 py-1.5 rounded-sm font-label text-[10px] font-medium uppercase tracking-wider transition-all bg-primary text-primary-foreground"
           >
              {t('writing.canvas.zen_exit_short')}
           </button>
           ) : (
           <button
              type="button"
              onClick={() => setZenMode(true)}
              aria-pressed="false"
              title={t('writing.canvas.zen_enter')}
              aria-label={t('writing.canvas.zen_enter')}
              className="px-3 py-1.5 rounded-sm font-label text-[10px] font-medium uppercase tracking-wider transition-all bg-surface-container text-foreground/50 hover:bg-surface-high"
           >
              {t('writing.canvas.zen_enter_short')}
           </button>
           )}
           <button 
              onClick={handleSave}
              disabled={saving || (!isDirty && sessionStatus !== 'error')}
              aria-label={saveLabel}
              className={cn(
                "ml-2 px-4 py-1.5 rounded-sm font-label text-xs font-medium flex items-center gap-2 transition-all disabled:cursor-not-allowed", 
                saveButtonClass
              )}
           >
              {saving || sessionStatus === 'saving' ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saveLabel}
           </button>
        </div>
      </motion.header>

      {/* Main Writing Area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-10">
        <div className="max-w-writing mx-auto w-full">
          <div className="mb-5 rounded-sm border border-outline-variant bg-surface-lowest px-4 py-3 shadow-sm">
            <div className="flex items-center justify-between gap-4 mb-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-label text-[10px] font-medium uppercase tracking-wider text-foreground/50">{t('writing.canvas.anchor_section')}</span>
                <span className="font-label text-[10px] font-medium px-2 py-0.5 rounded-sm bg-primary/10 text-primary">
                  {citationAnchors.length}
                </span>
              </div>
              {activeAnchor && (
                <span className="font-label text-[10px] text-foreground/50 truncate max-w-[240px]">
                  {t('writing.canvas.current_selection', { label: getCitationAnchorLabel(activeAnchor) })}
                </span>
              )}
            </div>
            {citationAnchors.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {citationAnchors.map((anchor) => {
                  const material = anchor.materialId ? materialLookup.get(anchor.materialId) : null;
                  const materialTitle = material ? material.titleZh : (anchor.materialId || t('writing.canvas.unbound'));
                  const materialCount = citationCountByMaterial[anchor.materialId || '__unbound__'] || 0;
                  const isActive = activeCitationAnchorInstanceId === anchor.instanceId;

                  return (
                    <button
                      key={anchor.instanceId}
                      type="button"
                      onClick={() => handleAnchorChipClick(anchor)}
                      title={`${materialTitle} · ${getCitationAnchorLabel(anchor)}`}
                      aria-label={t('writing.canvas.locate_anchor_aria', { anchor: getCitationAnchorLabel(anchor), material: materialTitle })}
                      className={cn(
                        'inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 font-label text-[10px] font-medium transition-all',
                        isActive
                          ? 'border-primary/30 bg-primary/10 text-primary shadow-sm'
                          : 'border-outline-variant bg-surface-lowest text-foreground/50 hover:border-primary/20 hover:text-foreground'
                      )}
                    >
                      <span className="font-label font-medium">#{anchor.ordinal}</span>
                      <span className="max-w-[150px] truncate">{materialTitle}</span>
                      <span className="rounded-sm bg-surface-container px-2 py-0.5 font-label text-[9px] font-medium uppercase tracking-wider text-foreground/40">
                        {materialCount}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="font-body text-[11px] text-foreground/40 leading-relaxed">
                {t('writing.canvas.no_anchors_hint')}
              </p>
            )}
          </div>

          <AnimatePresence mode="wait">
            {showComparison && transformResult ? (
              <motion.div 
                key="comparison"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                className="grid grid-cols-1 lg:grid-cols-2 gap-8 h-full min-h-[60vh]"
              >
                <div className="flex flex-col gap-4">
                  <span className="font-label text-[10px] font-medium uppercase tracking-wider text-destructive/50">
                    {t('writing.original')}
                  </span>
                  <div className="flex-1 p-6 bg-surface-low rounded-sm border border-outline-variant text-xs text-foreground/60 leading-relaxed overflow-auto custom-scrollbar font-doc italic">
                    {transformResult.inputText}
                  </div>
                  {transformResult.evidenceRefs && transformResult.evidenceRefs.length > 0 && (
                    <div className="mt-4 flex flex-col gap-2">
                      <span className="font-label text-[10px] font-medium uppercase tracking-wider text-primary/70">
                        {t('writing.canvas.evidence_refs')}
                      </span>
                      <div className="flex flex-col gap-2 max-h-[120px] overflow-auto custom-scrollbar">
                        {transformResult.evidenceRefs.map((ref, idx) => {
                          const title = getEvidenceReferenceTitle(ref, t('writing.canvas.evidence_item', { index: idx + 1 }));
                          const body = getEvidenceReferenceBody(ref) ?? t('writing.canvas.evidence_empty');
                          const metaParts = getEvidenceReferenceMetaParts(ref, {
                            chunk: t('writing.canvas.evidence_chunk'),
                            source: t('writing.canvas.evidence_source'),
                            score: t('writing.canvas.evidence_score'),
                          });
                          const wikiUrl = getEvidenceReferenceWikiUrl(ref);
                          const key = `${ref.chunk_id ?? ref.source_id ?? title}-${idx}`;

                          return (
                            <div key={key} className="p-2 bg-surface-lowest rounded-sm border border-outline-variant text-[11px] leading-relaxed text-foreground/70">
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0 truncate font-label text-[10px] font-medium text-foreground/70">
                                  {title}
                                </div>
                                {wikiUrl && (
                                  <a
                                    href={wikiUrl}
                                    className="shrink-0 rounded-sm border border-primary/20 bg-primary/5 px-2 py-0.5 font-label text-[9px] font-medium uppercase tracking-wider text-primary/75 transition-colors hover:border-primary/40 hover:bg-primary/10"
                                  >
                                    Wiki
                                  </a>
                                )}
                              </div>
                              {metaParts.length > 0 && (
                                <div className="mt-1 font-label text-[9px] uppercase tracking-wider text-foreground/40">
                                  {metaParts.join(' · ')}
                                </div>
                              )}
                              <div className="mt-1 text-foreground/70">
                                {body}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <span className="font-label text-[10px] font-medium uppercase tracking-wider text-primary">
                      {t('writing.preview_rewrite')}
                    </span>
                    <button 
                      onClick={handleApplyResult} 
                      className="bg-primary text-primary-foreground px-3 py-1 rounded-sm font-label text-[10px] font-medium"
                    >
                      {t('writing.apply_and_close')}
                    </button>
                  </div>
                  <textarea 
                    value={transformResult.outputText}
                    onChange={(e) => setTransformResult({...transformResult, outputText: e.target.value})}
                    aria-label={t('writing.preview_rewrite')}
                    className="flex-1 p-6 bg-surface-lowest rounded-sm border border-primary/20 text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/20 custom-scrollbar font-doc"
                  />
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="editor"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="w-full relative"
              >
                <div className="rounded-sm border border-outline-variant/60 bg-white dark:bg-surface-lowest shadow-[0_2px_12px_0_rgba(0,0,0,0.06)] dark:shadow-[0_2px_12px_0_rgba(0,0,0,0.25)] px-10 py-8 min-h-[80vh]">
                  <textarea
                    ref={textareaRef}
                    value={draft?.content || ''}
                    onChange={(e) => {
                      setDraft(prev => prev ? {...prev, content: e.target.value} : null);
                      setIsDirty(true);
                      setSessionStatus('idle');
                      setSessionMessage(null);
                    }}
                    className="w-full h-full min-h-[72vh] bg-transparent resize-none font-doc text-base leading-loose focus:outline-none placeholder:text-foreground/20 custom-scrollbar text-gray-800 dark:text-foreground"
                    placeholder={t('writing.placeholder')}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
