import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import { cn } from '@/lib/utils';
import { getLocalizedSectionTitle as getLocalizedSectionTitleUtil } from '@/lib/writing_i18n';
import type { 
  ManuscriptSection, 
  DraftContent, 
  Revision, 
  WritingAction, 
  TransformResult, 
  WritingMaterial 
} from '@/types/writing';
import {
  ChevronRight,
  Layers,
  X,
  Save,
  Loader2,
  Play,
  Clock,
  StickyNote,
  CheckCircle,
  Sparkles,
  Languages,
  RefreshCw,
  Minimize2,
  Maximize2,
  GitBranch,
  UserCheck,
  FileText,
  Shield,
  Code,
  BookOpen,
  ExternalLink,
  AlertTriangle,
  Diff,
  Info,
  History,
  CheckCircle2,
  ArrowRight
} from 'lucide-react';
import {
  getSimulationSectionsForProject,
  getSimulationDraftForSection,
  getSimulationMaterialsForProject,
} from '@/lib/simulationData';
import { useWriting } from '@/contexts/WritingContext';
import { motion, AnimatePresence } from 'framer-motion';

const writingBackend = getWritingBackendService();

const actionIconMap: Record<string, React.ReactNode> = {
  Languages: <Languages size={18} />, 
  RefreshCw: <RefreshCw size={18} />,
  Minimize2: <Minimize2 size={18} />, 
  Maximize2: <Maximize2 size={18} />,
  Sparkles: <Sparkles size={18} />, 
  GitBranch: <GitBranch size={18} />,
  UserCheck: <UserCheck size={18} />, 
  FileText: <FileText size={18} />,
  Shield: <Shield size={18} />, 
  Code: <Code size={18} />,
};

const FALLBACK_ACTIONS: WritingAction[] = [
  { id: 'zh_to_en', nameZh: '中英翻译', nameEn: 'ZH ➔ EN Translate', descriptionZh: '学术级中译英，保持术语一致性', descriptionEn: 'Academic ZH-to-EN translation with terminology consistency', category: 'translate', supportedScopes: ['selection', 'section'], icon: 'Languages' },
  { id: 'en_polish', nameZh: '英文润色', nameEn: 'English Polish', descriptionZh: '提升句式多样性与地道表达', descriptionEn: 'Enhance sentence variety and idiomatic expression', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'Sparkles' },
  { id: 'zh_rewrite', nameZh: '中文改写', nameEn: 'Chinese Rewrite', descriptionZh: '调整语义逻辑，规避重复', descriptionEn: 'Adjust semantic logic and avoid repetition', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'RefreshCw' },
  { id: 'logic_check', nameZh: '逻辑对齐', nameEn: 'Logic Alignment', descriptionZh: '检查段落内部与前后的叙事逻辑', descriptionEn: 'Verify internal and contextual narrative logic', category: 'check', supportedScopes: ['section', 'full_draft'], icon: 'GitBranch' },
  { id: 'humanize', nameZh: '去 AI 化', nameEn: 'Humanize Content', descriptionZh: '降低文本的机械感，使其更自然', descriptionEn: 'Reduce mechanical tone for a more natural flow', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'UserCheck' },
];

export function DraftStudio() {
  const { t, language: uiLang } = useI18n();
  const { scope, outputMode, currentProjectId } = useWriting();
  const [sections, setSections] = useState<ManuscriptSection[]>([]);
  const [actions, setActions] = useState<WritingAction[]>([]);
  const [activeSectionId, setActiveSectionId] = useState<string>('');
  const [draft, setDraft] = useState<DraftContent | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  // Panels
  const [showReferences, setShowReferences] = useState(false);
  const [materials, setMaterials] = useState<WritingMaterial[]>([]);
  const [rightTab, setRightTab] = useState<'assistant' | 'history'>('assistant');

  // Transform
  const [runningActionId, setRunningActionId] = useState<string | null>(null);
  const [transformResult, setTransformResult] = useState<TransformResult | null>(null);
  const [showComparison, setShowComparison] = useState(false);

  const loadProjectData = useCallback(async (projectId: string) => {
    setLoading(true);
    try {
      const [secs, mats] = await Promise.all([
        writingBackend.listSections(projectId).catch(() => getSimulationSectionsForProject(projectId)),
        writingBackend.getMaterials ? writingBackend.getMaterials(projectId).catch(() => getSimulationMaterialsForProject(projectId)) : getSimulationMaterialsForProject(projectId),
      ]);
      setSections(secs as any);
      setMaterials(mats as any);
      setActions(FALLBACK_ACTIONS);
      if (secs.length > 0) setActiveSectionId(secs[0].id);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (currentProjectId) loadProjectData(currentProjectId);
  }, [currentProjectId, loadProjectData]);

  useEffect(() => {
    if (!activeSectionId) return;
    setDraft({
      sectionId: activeSectionId,
      content: getSimulationDraftForSection(currentProjectId, activeSectionId),
      wordCount: 0,
      lastSavedAt: new Date().toISOString(),
      isDirty: false
    });
    setIsDirty(false);
  }, [activeSectionId, currentProjectId]);

  const handleRunAction = async (actionId: string) => {
    setRunningActionId(actionId);
    // Simulation of AI processing
    setTimeout(() => {
      const mockResult: TransformResult = {
        jobId: 'job-' + Math.random(),
        actionId,
        inputText: draft?.content || '',
        outputText: (draft?.content || '') + "\n\n[AI Optimized Content via " + actionId + "]",
        applied: false,
        createdAt: new Date().toISOString()
      };
      setTransformResult(mockResult);
      setShowComparison(true);
      setRunningActionId(null);
    }, 1500);
  };

  const handleApplyResult = () => {
    if (!transformResult) return;
    setDraft(prev => prev ? { ...prev, content: transformResult.outputText, isDirty: true } : null);
    setIsDirty(true);
    setShowComparison(false);
    setTransformResult(null);
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-background">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="flex-1 flex overflow-hidden">
        
        {/* Section Navigator */}
        <motion.div 
          initial={{ x: -20, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          className="w-64 border-r border-border bg-muted/30 flex flex-col"
        >
          <div className="p-5 border-b border-border flex items-center gap-2">
            <Layers size={14} className="text-primary" />
            <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">{t('writing.outline')}</span>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {sections.map(sec => (
              <button
                key={sec.id}
                onClick={() => setActiveSectionId(sec.id)}
                className={cn(
                  "w-full px-5 py-4 flex items-center gap-3 transition-all border-l-2",
                  activeSectionId === sec.id 
                    ? "bg-primary/10 border-primary text-primary shadow-inner" 
                    : "border-transparent text-muted-foreground hover:bg-muted/50"
                )}
              >
                <CheckCircle size={14} className={activeSectionId === sec.id ? "text-primary" : "text-muted-foreground/30"} />
                <span className="text-xs font-medium truncate flex-1">{uiLang === 'zh' ? sec.titleZh : sec.titleEn}</span>
              </button>
            ))}
          </div>
        </motion.div>

        {/* Editor Area */}
        <div className="flex-1 flex flex-col min-w-0 bg-background relative shadow-2xl">
          <header className="h-14 px-6 flex items-center justify-between border-b border-border bg-white/80 backdrop-blur-md sticky top-0 z-10">
            <div className="flex items-center gap-4">
               <h3 className="font-headline font-bold text-sm">
                  {sections.find(s => s.id === activeSectionId)?.titleZh || "Untitled"}
               </h3>
               {isDirty && <span className="text-[10px] bg-amber-100 text-amber-700 font-black px-2 py-0.5 rounded-full uppercase tracking-tighter">{t('writing.unsaved')}</span>}
            </div>
            <div className="flex items-center gap-2">
               <button 
                  onClick={() => setShowReferences(!showReferences)}
                  className={cn("p-2 rounded-xl transition-all", showReferences ? "bg-primary text-primary-foreground shadow-lg" : "hover:bg-muted text-muted-foreground")}
               >
                  <BookOpen size={18} />
               </button>
               <button 
                  onClick={() => setShowComparison(!showComparison)}
                  disabled={!transformResult}
                  className={cn("p-2 rounded-xl transition-all", showComparison ? "bg-primary text-primary-foreground shadow-lg" : "hover:bg-muted text-muted-foreground disabled:opacity-20")}
               >
                  <Diff size={18} />
               </button>
               <button 
                  onClick={() => setIsDirty(false)}
                  disabled={!isDirty || saving}
                  className={cn("ml-2 px-4 py-1.5 rounded-xl font-bold text-xs flex items-center gap-2 transition-all", isDirty ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20" : "bg-muted text-muted-foreground/50")}
               >
                  {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  {t('writing.save')}
               </button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto custom-scrollbar p-10 max-w-4xl mx-auto w-full">
            <AnimatePresence mode="wait">
              {showComparison && transformResult ? (
                <motion.div 
                  key="comparison"
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  className="grid grid-cols-2 gap-8 h-[70vh]"
                >
                  <div className="flex flex-col gap-4">
                    <span className="text-[10px] font-black uppercase tracking-widest text-destructive/50">{t('writing.original')}</span>
                    <div className="flex-1 p-6 bg-muted/20 rounded-2xl border border-border text-xs text-muted-foreground leading-relaxed overflow-auto custom-scrollbar font-doc italic">
                      {transformResult.inputText}
                    </div>
                  </div>
                  <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-black uppercase tracking-widest text-primary">{t('writing.preview_rewrite')}</span>
                      <button onClick={handleApplyResult} className="bg-primary text-primary-foreground px-3 py-1 rounded-lg text-[10px] font-bold shadow-lg shadow-primary/20">{t('writing.apply_and_close')}</button>
                    </div>
                    <textarea 
                      value={transformResult.outputText}
                      onChange={(e) => setTransformResult({...transformResult, outputText: e.target.value})}
                      className="flex-1 p-6 bg-white/50 backdrop-blur-sm rounded-2xl border border-primary/20 text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xl custom-scrollbar font-doc"
                    />
                  </div>
                </motion.div>
              ) : (
                <motion.textarea
                  key="editor"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  value={draft?.content || ''}
                  onChange={(e) => {
                    setDraft(prev => prev ? {...prev, content: e.target.value} : null);
                    setIsDirty(true);
                  }}
                  className="w-full h-[80vh] bg-transparent resize-none font-doc text-base leading-loose focus:outline-none placeholder:text-muted-foreground/30"
                  placeholder={t('writing.placeholder')}
                />
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Right Action Sidebar */}
        <div className="w-80 border-l border-border bg-white flex flex-col relative">
          <div className="flex border-b border-border bg-muted/10 p-1 m-4 rounded-xl">
             <button onClick={() => setRightTab('assistant')} className={cn("flex-1 py-2 text-[9px] font-black uppercase tracking-widest rounded-lg transition-all", rightTab === 'assistant' ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:bg-white/50")}>
                {t('writing.actions.processing_actions')}
             </button>
             <button onClick={() => setRightTab('history')} className={cn("flex-1 py-2 text-[9px] font-black uppercase tracking-widest rounded-lg transition-all", rightTab === 'history' ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:bg-white/50")}>
                {t('writing.actions.revision_history')}
             </button>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar px-5 pb-10 space-y-6">
            {rightTab === 'assistant' ? (
              <div className="space-y-8">
                {['translate', 'rewrite', 'check'].map(cat => (
                  <div key={cat} className="space-y-3">
                    <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/50 px-2">{t('writing.' + cat)}</h4>
                    <div className="grid gap-2">
                       {actions.filter(a => a.category === cat).map(action => (
                         <button
                           key={action.id}
                           onClick={() => handleRunAction(action.id)}
                           disabled={runningActionId !== null}
                           className={cn(
                             "group w-full p-4 rounded-2xl text-left transition-all border border-transparent",
                             runningActionId === action.id 
                              ? "bg-primary/5 border-primary/20 shadow-inner" 
                              : "bg-muted/30 hover:bg-white hover:border-primary/20 hover:shadow-xl hover:shadow-primary/5 active:scale-95"
                           )}
                         >
                           <div className="flex items-center gap-4">
                             <div className={cn("p-2 rounded-xl transition-all", runningActionId === action.id ? "bg-primary text-primary-foreground animate-pulse" : "bg-white text-primary group-hover:scale-110")}>
                               {runningActionId === action.id ? <RefreshCw size={18} className="animate-spin" /> : actionIconMap[action.icon] || <Sparkles size={18} />}
                             </div>
                             <div className="flex-1 min-w-0">
                               <p className="text-[11px] font-bold tracking-tight">{uiLang === 'zh' ? action.nameZh : action.nameEn}</p>
                             </div>
                             <ChevronRight size={14} className="text-muted-foreground/30 group-hover:text-primary transition-colors" />
                           </div>
                         </button>
                       ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-4">
                 {[1, 2, 3].map(i => (
                   <div key={i} className="p-4 rounded-2xl bg-muted/20 border border-border/50 hover:border-primary/20 transition-all cursor-pointer group">
                      <div className="flex items-center gap-3 mb-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-primary" />
                        <span className="text-[10px] font-black uppercase text-muted-foreground">Snapshot v{i}</span>
                      </div>
                      <p className="text-[11px] text-foreground line-clamp-2">Automatic backup before {i===1 ? 'structural adjustment' : 'language polish'}</p>
                      <div className="mt-3 flex items-center justify-between text-[8px] font-medium text-muted-foreground/50 uppercase tracking-widest">
                        <span className="flex items-center gap-1"><Clock size={10} /> 14:{i*15}</span>
                        <span className="group-hover:text-primary transition-colors flex items-center gap-1">Restore <ArrowRight size={8} /></span>
                      </div>
                   </div>
                 ))}
              </div>
            )}
          </div>
        </div>

        {/* References Drawer (Overlay) */}
        <AnimatePresence>
          {showReferences && (
            <motion.div 
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute right-0 top-0 bottom-0 w-[400px] bg-white/90 backdrop-blur-2xl border-l border-border z-50 shadow-[-20px_0_60px_rgba(0,0,0,0.1)] flex flex-col"
            >
              <div className="p-6 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                   <div className="p-2 bg-secondary/10 text-secondary rounded-xl"><BookOpen size={20} /></div>
                   <h3 className="font-headline font-bold text-base tracking-tight">{t('writing.materials_library')}</h3>
                </div>
                <button onClick={() => setShowReferences(false)} className="p-2 hover:bg-muted rounded-full transition-colors"><X size={20} /></button>
              </div>
              
              <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-4">
                {materials.map(mat => (
                  <div key={mat.id} className="glass-card p-5 rounded-2xl group border border-transparent hover:border-secondary/20 transition-all hover:shadow-2xl hover:shadow-secondary/5">
                     <div className="flex items-center justify-between mb-4">
                        <span className="text-[8px] font-black uppercase px-2 py-0.5 bg-secondary/10 text-secondary rounded tracking-widest">{mat.type}</span>
                        <ExternalLink size={12} className="text-muted-foreground/20 group-hover:text-secondary" />
                     </div>
                     <h5 className="text-[13px] font-bold mb-2 group-hover:text-secondary transition-colors leading-snug">{uiLang === 'zh' ? mat.titleZh : mat.titleEn}</h5>
                     <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-3 mb-4">{(uiLang === 'zh' ? mat.summaryZh : mat.summaryEn)}</p>
                     <div className="flex flex-wrap gap-1.5">
                        {((uiLang === 'zh' ? mat.focusPointsZh : mat.focusPointsEn)).map((fp, idx) => (
                           <span key={idx} className="text-[9px] font-medium px-2 py-0.5 bg-muted/50 rounded-md border border-border/50">{fp}</span>
                        ))}
                     </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Global Status Bar */}
      <footer className="h-10 border-t border-border bg-white px-8 flex items-center justify-between z-20">
         <div className="flex items-center gap-6 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            <div className="flex items-center gap-2">
               <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
               Live System
            </div>
            <div className="h-4 w-px bg-border mx-2" />
            <div className="flex items-center gap-2">
               Mode: <span className="text-primary">{outputMode.toUpperCase()}</span>
            </div>
         </div>
         <div className="flex items-center gap-10">
            <div className="flex items-center gap-6 text-[9px] font-black text-muted-foreground/30">
               {runningActionId && <motion.span animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 2 }} className="text-secondary tracking-tighter">Synchronizing Knowledge Graph...</motion.span>}
               <span>{t('writing.real_time_saved')}</span>
            </div>
            <div className="flex items-center gap-2 bg-muted px-3 py-1 rounded-full text-[11px] font-black tabular-nums">
               <span className="text-foreground">{(draft?.content?.split(/\s+/)?.filter(Boolean)?.length) || 0}</span>
               <span className="text-muted-foreground text-[9px] uppercase tracking-tighter">{t('writing.words')}</span>
            </div>
         </div>
      </footer>
    </div>
  );
}
