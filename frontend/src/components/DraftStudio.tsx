import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import { useWriting } from '@/contexts/WritingContext';
import { ListPlus, Loader2 } from 'lucide-react';
import { parseCitationAnchors } from '@/lib/citationAnchors';

// Types
import type { 
  ManuscriptSection, 
  DraftContent, 
  WritingAction, 
  TransformResult, 
  WritingMaterial,
  ContinuationContext,
  CitationAnchor,
  CitationInsertRequest,
  CitationFocusRequest,
} from '@/types/writing';

// Sub-components
import { OutlineNavigator } from './writing/OutlineNavigator';
import { WritingCanvas } from './writing/WritingCanvas';
import { AssistantDock } from './writing/AssistantDock';
import { ReferenceDrawer } from './writing/ReferenceDrawer';
import { StatusBar } from './writing/StatusBar';
import { useJobEventPolling } from '@/hooks/useJobEventPolling';
import { ExportPreviewModal } from './writing/ExportPreviewModal';
import { formatWritingRuntimeError, sanitizeRuntimeVisibleText } from './writing/writingRuntimeDisplay';

const writingBackend = getWritingBackendService();
const runtimeClient = getWritingRuntimeClient();

type ActiveJobTracking = {
  jobId: string;
  sessionId: string;
  actionId: string;
  inputText: string;
  outputMode: string;
};

const createRequestId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const getRuntimeSessionStorageKey = (projectId: string) => `writing-runtime-session:${projectId}`;

export function formatDraftStudioDiagnosticError(
  error: unknown,
  fallback = '写作运行状态已变化。',
): string {
  return formatWritingRuntimeError(error, fallback);
}

const createEmptyDraftContent = (sectionId: string): DraftContent => ({
  sectionId,
  content: '',
  wordCount: 0,
  lastSavedAt: new Date().toISOString(),
  isDirty: false,
});

const WorkspaceEmptyState = ({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) => (
  <div className="h-full flex items-center justify-center bg-background px-8">
    <div className="max-w-xl rounded-xl border border-outline-variant bg-surface-lowest shadow-lg shadow-black/5 p-10 text-center">
      <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Loader2 size={22} className="opacity-70" />
      </div>
      <h2 className="font-headline text-2xl font-semibold tracking-tight text-foreground">{title}</h2>
      <p className="mt-3 font-body text-sm leading-6 text-foreground/60">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  </div>
);

const FALLBACK_ACTIONS: WritingAction[] = [
  { id: 'zh_to_en', nameZh: '中英翻译', nameEn: 'ZH ➔ EN Translate', descriptionZh: '学术级中译英，保持术语一致性', descriptionEn: 'Academic ZH-to-EN translation with terminology consistency', category: 'translate', supportedScopes: ['selection', 'section'], icon: 'Languages' },
  { id: 'en_polish', nameZh: '英文润色', nameEn: 'English Polish', descriptionZh: '提升句式多样性与地道表达', descriptionEn: 'Enhance sentence variety and idiomatic expression', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'Sparkles' },
  { id: 'zh_rewrite', nameZh: '中文改写', nameEn: 'Chinese Rewrite', descriptionZh: '调整语义逻辑，规避重复', descriptionEn: 'Adjust semantic logic and avoid repetition', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'RefreshCw' },
  { id: 'logic_check', nameZh: '逻辑对齐', nameEn: 'Logic Alignment', descriptionZh: '检查段落内部与前后的叙事逻辑', descriptionEn: 'Verify internal and contextual narrative logic', category: 'check', supportedScopes: ['section', 'full_draft'], icon: 'GitBranch' },
  { id: 'humanize', nameZh: '去 AI 化', nameEn: 'Humanize Content', descriptionZh: '降低文本的机械感，使其更自然', descriptionEn: 'Reduce mechanical tone for a more natural flow', category: 'rewrite', supportedScopes: ['selection', 'section'], icon: 'UserCheck' },
];

export function DraftStudio() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { 
    activeProjectId, 
    setActiveProjectId,
    projectDataVersion,
    activeSectionId, 
    setActiveSectionId,
    zenMode,
    setZenMode,
    citationDrawerOpen,
    setCitationDrawerOpen,
    outputMode,
    setConnectionState,
    setSessionStatus,
    sessionMessage,
    setSessionMessage,
    setActiveJobTimeline,
  } = useWriting();

  // Data States
  const [sections, setSections] = useState<ManuscriptSection[]>([]);
  const [actions, setActions] = useState<WritingAction[]>([]);
  const [materials, setMaterials] = useState<WritingMaterial[]>([]);
  const [draft, setDraft] = useState<DraftContent | null>(null);
  const [realDraftId, setRealDraftId] = useState<string | null>(null);
  const [runtimeSession, setRuntimeSession] = useState<{ projectId: string; sessionId: string } | null>(null);
  const [activeCitationAnchorId, setActiveCitationAnchorId] = useState<string | null>(null);
  const [focusedMaterialId, setFocusedMaterialId] = useState<string | null>(null);
  const [citationInsertRequest, setCitationInsertRequest] = useState<CitationInsertRequest | null>(null);
  const [citationFocusRequest, setCitationFocusRequest] = useState<CitationFocusRequest | null>(null);
  
  // Loading & UI States
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [rightTab, setRightTab] = useState<'assistant' | 'history' | 'inspire'>('inspire');

  // Transform States
  const [runningActionId, setRunningActionId] = useState<string | null>(null);
  const [transformResult, setTransformResult] = useState<TransformResult | null>(null);
  const [showComparison, setShowComparison] = useState(false);
  const [activeJobTracking, setActiveJobTracking] = useState<ActiveJobTracking | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);

  const citationAnchors = React.useMemo(
    () => parseCitationAnchors(draft?.content || ''),
    [draft?.content]
  );

  const citationCountByMaterial = React.useMemo(() => {
    return citationAnchors.reduce<Record<string, number>>((acc, anchor) => {
      const materialKey = anchor.materialId || '__unbound__';
      acc[materialKey] = (acc[materialKey] || 0) + 1;
      return acc;
    }, {});
  }, [citationAnchors]);

  useJobEventPolling({
    jobId: activeJobTracking?.jobId ?? null,
    sessionId: activeJobTracking?.sessionId ?? null,
    enabled: activeJobTracking !== null,
    onTerminalState: async ({ jobId, statusDetail }) => {
      const tracking = activeJobTracking;

      try {
        if (statusDetail.status === 'completed') {
          const artifacts = await runtimeClient.getJobArtifacts(jobId);
          const textArtifact = artifacts.find(a => a.artifact_type === 'transformed_text');
          const rawContent = textArtifact?.content;
          const resultText = typeof rawContent === 'string'
            ? rawContent
            : rawContent && typeof rawContent === 'object'
              ? String(
                  (rawContent as Record<string, unknown>).output_text
                  ?? (rawContent as Record<string, unknown>).text
                  ?? ''
                )
              : '';

          setTransformResult({
            jobId,
            actionId: tracking?.actionId || '',
            inputText: tracking?.inputText || draft?.content || '',
            outputText: resultText,
            applied: false,
            createdAt: new Date().toISOString()
          });
          setShowComparison(true);
          setSessionStatus('idle');
          setSessionMessage(t('writing.studio.action_completed'));
        } else {
          const fallbackMessage = statusDetail.status === 'cancelled'
            ? t('writing.studio.action_cancelled')
            : t('writing.studio.action_failed');
          setSessionStatus('error');
          setSessionMessage(sanitizeRuntimeVisibleText(statusDetail.error, fallbackMessage));
          setTransformResult(null);
          setShowComparison(false);
        }
      } catch (err) {
        setSessionStatus('error');
        setSessionMessage(sanitizeRuntimeVisibleText(
          err instanceof Error ? err.message : null,
          t('writing.studio.action_result_error'),
        ));
        setTransformResult(null);
        setShowComparison(false);
      } finally {
        setRunningActionId(null);
        setActiveJobTracking(null);
      }
    },
  });

  const activeProjectIdRef = React.useRef<string | null>(activeProjectId);
  const runtimeSessionPromiseRef = React.useRef<{ projectId: string; promise: Promise<string | null> } | null>(null);
  const actionsCacheRef = React.useRef<WritingAction[] | null>(null);
  const actionsPromiseRef = React.useRef<Promise<WritingAction[]> | null>(null);
  const actionRunGenerationRef = React.useRef(0);

  useEffect(() => {
    activeProjectIdRef.current = activeProjectId;
  }, [activeProjectId]);

  const loadWritingActions = useCallback(async (forceRefresh = false): Promise<WritingAction[]> => {
    if (!forceRefresh && actionsCacheRef.current) {
      return actionsCacheRef.current;
    }

    if (!forceRefresh && actionsPromiseRef.current) {
      return actionsPromiseRef.current;
    }

    const request = writingBackend
      .listWritingActions()
      .catch(() => FALLBACK_ACTIONS)
      .then((availableActions) => {
        actionsCacheRef.current = availableActions;
        return availableActions;
      })
      .finally(() => {
        actionsPromiseRef.current = null;
      });

    actionsPromiseRef.current = request;
    return request;
  }, []);

  const ensureRuntimeSession = useCallback(async (quiet = false): Promise<string | null> => {
    if (!activeProjectId) {
      return null;
    }

    if (runtimeSession?.projectId === activeProjectId && runtimeSession.sessionId) {
      return runtimeSession.sessionId;
    }

    if (runtimeSessionPromiseRef.current?.projectId === activeProjectId) {
      return runtimeSessionPromiseRef.current.promise;
    }

    const requestProjectId = activeProjectId;
    const bootstrapPromise = (async () => {
      const storageKey = getRuntimeSessionStorageKey(activeProjectId);
      let storedSessionId: string | null = null;

      if (typeof window !== 'undefined') {
        try {
          storedSessionId = window.localStorage.getItem(storageKey);
        } catch (storageError) {
          if (!quiet) {
            console.warn(
              'Runtime session storage unavailable; creating a new session.',
              formatDraftStudioDiagnosticError(storageError, '本机写作会话缓存不可用。'),
            );
          }
        }
      }

      if (storedSessionId) {
        try {
          const existingSession = await runtimeClient.getSession(storedSessionId);
          if (activeProjectIdRef.current === requestProjectId) {
            setRuntimeSession({ projectId: requestProjectId, sessionId: existingSession.session_id });
          }
          return existingSession.session_id;
        } catch (error) {
          if (typeof window !== 'undefined') {
            try {
              window.localStorage.removeItem(storageKey);
            } catch (storageError) {
              if (!quiet) {
                console.warn(
                  'Unable to clear stale runtime session storage.',
                  formatDraftStudioDiagnosticError(storageError, '本机写作会话缓存清理失败。'),
                );
              }
            }
          }

          if (!quiet) {
            console.warn(
              'Stored runtime session could not be restored; creating a new one.',
              formatDraftStudioDiagnosticError(error, '旧写作会话无法恢复，正在创建新会话。'),
            );
          }
        }
      }

      const createdSession = await runtimeClient.createSession({
        mode: 'hybrid',
        user_id: null,
        settings: {
          project_id: activeProjectId,
          section_id: activeSectionId || null,
          source: 'draft-studio',
        },
        tags: ['draft-studio', activeProjectId],
      });

      if (typeof window !== 'undefined') {
        try {
          window.localStorage.setItem(storageKey, createdSession.session_id);
        } catch (storageError) {
          if (!quiet) {
            console.warn(
              'Unable to persist runtime session id locally.',
              formatDraftStudioDiagnosticError(storageError, '本机写作会话缓存保存失败。'),
            );
          }
        }
      }

      if (activeProjectIdRef.current === requestProjectId) {
        setRuntimeSession({ projectId: requestProjectId, sessionId: createdSession.session_id });
      }
      return createdSession.session_id;
    })().catch((error) => {
      console.error(
        'Failed to bootstrap runtime session:',
        formatDraftStudioDiagnosticError(error, t('writing.studio.session_init_failed')),
      );
      setConnectionState('degraded');
      if (!quiet && activeProjectIdRef.current === requestProjectId) {
        setSessionStatus('error');
        setSessionMessage(t('writing.studio.session_init_failed'));
      }
      return null;
    });

    runtimeSessionPromiseRef.current = {
      projectId: requestProjectId,
      promise: bootstrapPromise,
    };

    try {
      return await bootstrapPromise;
    } finally {
      if (runtimeSessionPromiseRef.current?.projectId === requestProjectId) {
        runtimeSessionPromiseRef.current = null;
      }
    }
  }, [activeProjectId, activeSectionId, runtimeSession, setConnectionState, setSessionMessage, setSessionStatus]);

  useEffect(() => {
    if (!activeProjectId) {
      setRuntimeSession(null);
      return;
    }

    void ensureRuntimeSession(true);
  }, [activeProjectId, ensureRuntimeSession]);

  useEffect(() => {
    if (!citationAnchors.length) {
      if (activeCitationAnchorId !== null) {
        setActiveCitationAnchorId(null);
      }
      return;
    }

    if (activeCitationAnchorId && !citationAnchors.some((anchor) => anchor.id === activeCitationAnchorId)) {
      setActiveCitationAnchorId(citationAnchors[0].id);
    }
  }, [activeCitationAnchorId, citationAnchors]);

  // Escape closes transient workspace chrome without stealing editor undo shortcuts.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') {
        return;
      }

      if (citationDrawerOpen) {
        e.preventDefault();
        setCitationDrawerOpen(false);
        return;
      }

      if (zenMode) {
        e.preventDefault();
        setZenMode(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [citationDrawerOpen, setCitationDrawerOpen, zenMode, setZenMode]);

  useEffect(() => {
    if (activeProjectId) {
      return;
    }

    let cancelled = false;

    const bootstrapWorkspace = async () => {
      setLoading(true);
      setSessionStatus('loading');
      setSessionMessage(t('writing.studio.loading_project'));

      try {
        const [projects, availableActions] = await Promise.all([
          writingBackend.listProjects(),
          loadWritingActions(),
        ]);

        if (cancelled) {
          return;
        }

        setActions(availableActions);

        if (projects.length === 0) {
          setSections([]);
          setMaterials([]);
          setDraft(null);
          setRealDraftId(null);
          setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'online' : 'offline');
          setSessionStatus('idle');
          setSessionMessage(t('writing.studio.no_projects_hint'));
          setLoading(false);
          return;
        }

        setActiveProjectId(projects[0].project_id);
      } catch (err) {
        if (cancelled) {
          return;
        }

        console.error(
          'Failed to bootstrap writing workspace:',
          formatDraftStudioDiagnosticError(err, t('writing.studio.project_load_error')),
        );
        setActions(FALLBACK_ACTIONS);
        setSections([]);
        setMaterials([]);
        setDraft(null);
        setRealDraftId(null);
        setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'degraded' : 'offline');
        setSessionStatus('error');
        setSessionMessage(t('writing.studio.project_load_error'));
        setLoading(false);
      }
    };

    void bootstrapWorkspace();

    return () => {
      cancelled = true;
    };
  }, [
    activeProjectId,
    setActiveProjectId,
    setConnectionState,
    setSessionMessage,
    setSessionStatus,
  ]);

  const loadProjectData = useCallback(async (projectId: string) => {
    setLoading(true);
    setSessionStatus('loading');
    setSessionMessage(t('writing.studio.loading_data'));
    try {
      const [secs, mats, availableActions] = await Promise.all([
        writingBackend.listSections(projectId),
        writingBackend.listMaterials(projectId),
        loadWritingActions(),
      ]);

      // Normalize backend types to local UI types
      const normalizedSecs: ManuscriptSection[] = secs.map((section) => ({
        id: section.section_id,
        projectId: section.project_id,
        titleZh: section.title,
        titleEn: section.title,
        status: 'drafting',
        wordCount: 0,
        order: section.order,
      }));

      const normalizedMats: WritingMaterial[] = mats.map((material) => ({
        id: material.material_id,
        titleZh: material.title,
        titleEn: material.title_en || material.title,
        summaryZh: material.summary,
        summaryEn: material.summary_en || material.summary,
        type: material.type || 'reference',
        focusPointsZh: [...(material.focus_points ?? [])],
        focusPointsEn: [...(material.focus_points_en ?? [])]
      }));

      setSections(normalizedSecs);
      setMaterials(normalizedMats);
      setActions(availableActions);
      setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'online' : 'offline');
      setSessionStatus('idle');
      setSessionMessage(null);

      if (normalizedSecs.length === 0) {
        setActiveSectionId('');
        setRealDraftId(null);
        setDraft(null);
        setSessionMessage(t('writing.studio.no_sections_hint'));
        return;
      }

      const hasActiveSection = normalizedSecs.some((section) => section.id === activeSectionId);
      if (!hasActiveSection) {
        setActiveSectionId(normalizedSecs[0].id);
      }
    } catch (err) {
      console.error(
        'Failed to load project data:',
        formatDraftStudioDiagnosticError(err, t('writing.studio.data_load_error')),
      );
      setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'degraded' : 'offline');
      setActions(FALLBACK_ACTIONS);
      setSections([]);
      setMaterials([]);
      setDraft(null);
      setRealDraftId(null);
      setSessionStatus('error');
      setSessionMessage(t('writing.studio.data_load_error'));
    } finally {
      setLoading(false);
    }
  }, [activeSectionId, loadWritingActions, setActiveSectionId, setConnectionState, setSessionMessage, setSessionStatus]);

  useEffect(() => {
    if (activeProjectId) loadProjectData(activeProjectId);
  }, [activeProjectId, loadProjectData, projectDataVersion]);

  // Load draft for active section
  useEffect(() => {
    if (!activeSectionId || !activeProjectId) return;
    
    const loadDraft = async () => {
      try {
        setSessionStatus('loading');
        setSessionMessage(t('writing.studio.loading_draft'));
        const drafts = await writingBackend.listDrafts(activeProjectId, activeSectionId);
        if (drafts && drafts.length > 0) {
          const d = drafts[0];
          setRealDraftId(d.draft_id);
          setDraft({
            sectionId: activeSectionId,
            content: d.content,
            wordCount: d.content.length,
            lastSavedAt: d.updated_at,
            isDirty: false
          });
          setSessionMessage(null);
        } else {
          setRealDraftId(null);
          setDraft(createEmptyDraftContent(activeSectionId));
          setSessionMessage(t('writing.studio.no_draft_hint'));
        }
      } catch (err) {
        setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'degraded' : 'offline');
        setSessionMessage(t('writing.studio.draft_sync_error'));
        setDraft(createEmptyDraftContent(activeSectionId));
      }
      setIsDirty(false);
      setSessionStatus('idle');
    };

    loadDraft();
  }, [activeSectionId, activeProjectId, setConnectionState, setSessionMessage, setSessionStatus]);

  const handleRunAction = async (actionId: string) => {
    const runGeneration = actionRunGenerationRef.current + 1;
    actionRunGenerationRef.current = runGeneration;
    setRunningActionId(actionId);
    try {
      const sessionId = await ensureRuntimeSession();
      if (!sessionId) {
        throw new Error('Runtime session unavailable');
      }

      setSessionStatus('loading');
      setSessionMessage(t('writing.studio.starting_action'));

      const job = await runtimeClient.createJob({
        session_id: sessionId,
        kind: 'skill_action',
        action_id: actionId,
        input_text: draft?.content || '',
        output_mode: outputMode,
      });

      if (actionRunGenerationRef.current !== runGeneration) {
        await runtimeClient.cancelJob(job.job_id).catch(() => undefined);
        return;
      }

      await runtimeClient.startJob(job.job_id);
      if (actionRunGenerationRef.current !== runGeneration) {
        await runtimeClient.cancelJob(job.job_id).catch(() => undefined);
        return;
      }
      setActiveJobTimeline(null);
      setTransformResult(null);
      setShowComparison(false);
      setActiveJobTracking({
        jobId: job.job_id,
        sessionId,
        actionId,
        inputText: draft?.content || '',
        outputMode,
      });
      setSessionMessage(t('writing.studio.action_started'));
    } catch (err) {
      setConnectionState('degraded');
      setSessionStatus('error');
      setSessionMessage(err instanceof Error && err.message === 'Runtime session unavailable'
        ? t('writing.studio.session_unavailable')
        : t('writing.studio.skill_unavailable'));
      setTransformResult(null);
      setShowComparison(false);
      setRunningActionId(null);
      setActiveJobTracking(null);
    }
  };

  const handleStopAction = async () => {
    actionRunGenerationRef.current += 1;
    const tracking = activeJobTracking;
    if (!tracking) {
      setRunningActionId(null);
      setSessionStatus('idle');
      setSessionMessage(t('writing.studio.action_cancelled'));
      return;
    }

    try {
      setSessionStatus('loading');
      setSessionMessage(t('writing.studio.action_cancelled'));
      await runtimeClient.cancelJob(tracking.jobId);
      setTransformResult(null);
      setShowComparison(false);
      setRunningActionId(null);
      setActiveJobTracking(null);
      setSessionStatus('idle');
      setSessionMessage(t('writing.studio.action_cancelled'));
    } catch {
      setSessionStatus('error');
      setSessionMessage(t('writing.studio.action_failed'));
    }
  };

  const handleRequestCitationInsertion = (materialId: string | null) => {
    const normalizedMaterialId = materialId || null;
    setFocusedMaterialId(normalizedMaterialId);
    setCitationInsertRequest({
      requestId: createRequestId(),
      materialId: normalizedMaterialId,
    });
    if (normalizedMaterialId) {
      setCitationDrawerOpen(true);
    }
  };

  const handleRequestAnchorFocus = (anchor: CitationAnchor) => {
    setActiveCitationAnchorId(anchor.instanceId);
    setFocusedMaterialId(anchor.materialId || null);
    setCitationFocusRequest({
      requestId: createRequestId(),
      anchorId: anchor.id,
      anchorInstanceId: anchor.instanceId,
      anchorStartOffset: anchor.startOffset,
      materialId: anchor.materialId || null,
    });
    setCitationDrawerOpen(true);
  };

  const handleCitationInsertHandled = (
    requestId: string,
    anchorId: string,
    materialId: string | null
  ) => {
    setCitationInsertRequest((current) => (current?.requestId === requestId ? null : current));
    setActiveCitationAnchorId(anchorId);
    setFocusedMaterialId(materialId || null);
  };

  const handleCitationFocusHandled = (requestId: string) => {
    setCitationFocusRequest((current) => (current?.requestId === requestId ? null : current));
  };

  const handleApplyResult = () => {
    if (!transformResult) return;
    setDraft(prev => prev ? { ...prev, content: transformResult.outputText, isDirty: true } : null);
    setIsDirty(true);
    setSessionStatus('idle');
    setSessionMessage(null);
    setShowComparison(false);
    setTransformResult(null);
  };

  const handleSave = async () => {
    if (!draft || !activeProjectId || !activeSectionId) return;
    setSaving(true);
    setSessionStatus('saving');
    setSessionMessage(t('writing.studio.saving_draft'));
    try {
      if (realDraftId) {
        await writingBackend.saveDraft(realDraftId, {
          content: draft.content,
          citation_anchors: citationAnchors,
        });
      } else {
        // Try creating if it doesn't exist
        const newDraft = await writingBackend.createDraft({
          project_id: activeProjectId,
          section_id: activeSectionId,
          content: draft.content,
          title: sections.find(s => s.id === activeSectionId)?.titleZh || 'New Draft',
          citation_anchors: citationAnchors,
        });
        setRealDraftId(newDraft.draft_id);
      }
      setConnectionState('online');
      setSessionStatus('idle');
      setSessionMessage(t('writing.studio.saved'));
      setIsDirty(false);
      setDraft({ ...draft, isDirty: false, lastSavedAt: new Date().toISOString() });
    } catch (err) {
      console.warn(
        'Save failed, using local simulation state',
        formatDraftStudioDiagnosticError(err, t('writing.studio.save_error')),
      );
      setConnectionState(typeof navigator !== 'undefined' && navigator.onLine ? 'degraded' : 'offline');
      setSessionStatus('error');
      setSessionMessage(typeof navigator !== 'undefined' && navigator.onLine ? t('writing.studio.save_error') : t('writing.studio.save_offline'));
      setIsDirty(true);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-primary" size={40} />
          <p className="font-label text-xs font-medium uppercase tracking-wider text-foreground/50 animate-pulse">正在连接写作运行环境…</p>
        </div>
      </div>
    );
  }

  if (!activeProjectId) {
    return (
      <WorkspaceEmptyState
        title={t('writing.draft.no_project')}
        description={sessionMessage || t('writing.draft.no_project_desc')}
      />
    );
  }

  if (sections.length === 0) {
    return (
      <WorkspaceEmptyState
        title={t('writing.draft.no_sections')}
        description={sessionMessage || t('writing.draft.no_sections_desc')}
        action={
          <button
            type="button"
            onClick={() => navigate('/writing/outline')}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-label font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <ListPlus size={15} />
            {t('writing.outline.add_section')}
          </button>
        }
      />
    );
  }

  const activeSection = sections.find(s => s.id === activeSectionId);

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="flex-1 flex overflow-hidden relative">
        <OutlineNavigator sections={sections} />
        <WritingCanvas 
          activeSection={activeSection}
          draft={draft}
          setDraft={setDraft}
          isDirty={isDirty}
          setIsDirty={setIsDirty}
          saving={saving}
          handleSave={handleSave}
          showReferences={citationDrawerOpen}
          setShowReferences={setCitationDrawerOpen}
          showComparison={showComparison}
          setShowComparison={setShowComparison}
          transformResult={transformResult}
          setTransformResult={setTransformResult}
          handleApplyResult={handleApplyResult}
          materials={materials}
          citationAnchors={citationAnchors}
          citationCountByMaterial={citationCountByMaterial}
          activeCitationAnchorInstanceId={activeCitationAnchorId}
          focusedMaterialId={focusedMaterialId}
          citationInsertRequest={citationInsertRequest}
          citationFocusRequest={citationFocusRequest}
          onRequestCitationInsertion={handleRequestCitationInsertion}
          onRequestAnchorFocus={handleRequestAnchorFocus}
          onCitationInsertHandled={handleCitationInsertHandled}
          onCitationFocusHandled={handleCitationFocusHandled}
        />
        <AssistantDock 
          actions={actions}
          runningActionId={runningActionId}
          handleRunAction={handleRunAction}
          handleStopAction={() => void handleStopAction()}
          rightTab={rightTab}
          setRightTab={setRightTab}
          onContinueFromSpark={(ctx: ContinuationContext) => {
            // 将启发点内容 + 证据 + 建议角度插入到草稿末尾
            const sparkContent = ctx.spark.content;
            const evidenceBlock = ctx.evidence_texts.length > 0
              ? '\n\n相关证据:\n' + ctx.evidence_texts.slice(0, 3).map(t => `• ${t}`).join('\n')
              : '';
            const anglesBlock = ctx.suggested_angles.length > 0
              ? '\n\n建议角度:\n' + ctx.suggested_angles.map(a => `‣ ${a}`).join('\n')
              : '';
            const causalBlock = ctx.causal_chain_summary
              ? `\n\n因果链: ${ctx.causal_chain_summary}`
              : '';
            const insertText = `\n\n--- 启发点 ---\n${sparkContent}${causalBlock}${evidenceBlock}${anglesBlock}\n--- ---\n`;
            setDraft(prev => prev ? {
              ...prev,
              content: prev.content + insertText,
              isDirty: true,
            } : null);
            setIsDirty(true);
            setSessionMessage('启发点已插入草稿末尾，可编辑或展开续写');
          }}
        />
        <ReferenceDrawer 
          isOpen={citationDrawerOpen} 
          onClose={() => setCitationDrawerOpen(false)}
          materials={materials}
          draft={draft}
          citationAnchors={citationAnchors}
          citationCountByMaterial={citationCountByMaterial}
          activeMaterialId={focusedMaterialId}
          activeCitationAnchorInstanceId={activeCitationAnchorId}
          activeSectionTitle={sections.find(s => s.id === activeSectionId)?.titleZh}
          onRequestCitationInsertion={(materialId: string | null) => setCitationInsertRequest({ requestId: createRequestId(), materialId })}
          onRequestAnchorFocus={(anchor: CitationAnchor) => setCitationFocusRequest({ 
            requestId: createRequestId(), 
            anchorId: anchor.id,
            anchorInstanceId: anchor.instanceId,
            anchorStartOffset: anchor.startOffset,
            materialId: anchor.materialId || null 
          })}
          onSelectMaterial={(id: string | null) => setFocusedMaterialId(id)}
        />
      </div>
      <StatusBar 
        wordCount={draft?.content?.length || 0}
        isRunningAction={runningActionId !== null}
        citationCount={citationAnchors.length}
        onOpenExport={() => setShowExportModal(true)}
      />

      <ExportPreviewModal 
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        projectId={activeProjectId || ''}
      />
    </div>
  );
}
