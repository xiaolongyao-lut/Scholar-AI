import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BookDown,
  Check,
  CheckCircle2,
  Clock3,
  Download,
  ExternalLink,
  FileCheck2,
  FolderKanban,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
} from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import { Modal, ModalBody, ModalFooter, ModalHeader } from '@/components/ui/Modal';
import { useWriting } from '@/contexts/WritingContext';
import { cn } from '@/lib/utils';
import {
  acquisitionErrorMessage,
  controlAcquisitionDownload,
  getAcquisitionImportReceipt,
  getAcquisitionStatus,
  importAcquisitionArtifact,
  isVerifiedImportReceipt,
  queueAcquisitionDownload,
  resolveAcquisitionGate,
  runAcquisitionDownload,
  searchAcquisition,
  type AccessEvidence,
  type AcquisitionStatus,
  type CandidateManifest,
  type DownloadControlAction,
  type DownloadJob,
  type DownloadJobStatus,
  type HumanAccessGate,
  type ImportReceipt,
  type PdfCandidate,
  type SearchRun,
} from '@/services/acquisitionApi';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingProject } from '@/types/resources';

interface ProjectOption {
  id: string;
  title: string;
}

interface Feedback {
  tone: 'success' | 'danger' | 'info';
  message: string;
}

interface ProjectStatusSnapshot {
  projectId: string;
  value: AcquisitionStatus;
}

const JOB_LABELS: Record<DownloadJobStatus, string> = {
  queued: '等待开始',
  running: '正在下载',
  paused: '已暂停',
  human_required: '需要人工处理',
  validating: '正在校验',
  completed: '校验通过',
  failed: '执行失败',
  cancelled: '已取消',
};

const JOB_TONES: Record<DownloadJobStatus, StatusTone> = {
  queued: 'neutral',
  running: 'info',
  paused: 'warning',
  human_required: 'warning',
  validating: 'info',
  completed: 'success',
  failed: 'danger',
  cancelled: 'neutral',
};

function receiptLabel(receipt: ImportReceipt): string {
  if (receipt.status === 'failed') return receipt.publication_state === 'failed' ? '发布校验失败' : '导入失败';
  if (isVerifiedImportReceipt(receipt)) {
    return receipt.status === 'duplicate' ? '项目中已存在（已核验）' : '已导入项目（已核验）';
  }
  if (receipt.publication_state === 'pending') return '发布校验中';
  return '旧回执未核验';
}

function receiptTone(receipt: ImportReceipt): StatusTone {
  if (receipt.status === 'failed' || receipt.publication_state === 'failed') return 'danger';
  if (isVerifiedImportReceipt(receipt)) return receipt.status === 'duplicate' ? 'warning' : 'success';
  return receipt.publication_state === 'pending' ? 'info' : 'warning';
}

function isPublicationRetryableReceipt(receipt: ImportReceipt): boolean {
  return receipt.receipt_schema_version === 'scholar-ai-import-receipt/v2'
    && receipt.publication_state === 'pending'
    && (receipt.status === 'queued' || receipt.status === 'completed' || receipt.status === 'duplicate');
}

const GATE_LABELS: Record<string, string> = {
  login: '登录要求',
  captcha: '验证码',
  paywall: '付费访问',
  robots: '来源访问限制',
  sso: '机构登录',
  two_factor: '二次验证',
  cloudflare: '来源安全检查',
  http_401: '需要授权',
  http_403: '访问受限',
  http_407: '代理授权',
  http_429: '访问频率限制',
  http_503: '来源暂不可用',
  html_instead_of_pdf: '需要人工确认文件',
};

function sourceLabel(sourceId: string): string {
  const labels: Record<string, string> = {
    arxiv: 'arXiv',
    crossref: 'Crossref',
    openalex: 'OpenAlex',
    pubmed: 'PubMed',
    semantic_scholar: 'Semantic Scholar',
    unpaywall: 'Unpaywall',
  };
  return labels[sourceId] ?? sourceId.replace(/_/g, ' ');
}

function formatDateTime(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(parsed));
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '尚未下载';
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function safeEvidenceStatement(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (
    !normalized
    || /(?:https?:\/\/|[A-Za-z]:[\\/]|\.sqlite|authorization|bearer|token|secret|env=)/i.test(normalized)
  ) {
    return '该下载地址具有可核验的开放获取依据。';
  }
  return normalized.length > 180 ? `${normalized.slice(0, 177)}...` : normalized;
}

function feedbackClasses(tone: Feedback['tone']): string {
  if (tone === 'danger') {
    return 'border-red-200 bg-red-50 text-red-800 dark:border-red-800/50 dark:bg-red-950/35 dark:text-red-200';
  }
  if (tone === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800/50 dark:bg-emerald-950/35 dark:text-emerald-200';
  }
  return 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800/50 dark:bg-sky-950/35 dark:text-sky-200';
}

function upsertJob(jobs: DownloadJob[], nextJob: DownloadJob): DownloadJob[] {
  const remaining = jobs.filter((job) => job.job_id !== nextJob.job_id);
  return [nextJob, ...remaining].sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
}

function openAccessEvidence(pdf: PdfCandidate): boolean {
  return pdf.access_evidence.access_route === 'open_access';
}

function candidateSecondaryLine(candidate: CandidateManifest): string {
  const authorText = candidate.authors.slice(0, 3).join('、') || '作者信息暂缺';
  const yearText = candidate.year ? String(candidate.year) : '年份未知';
  return `${authorText}${candidate.authors.length > 3 ? ' 等' : ''} · ${yearText}`;
}

function EvidenceRow({
  pdf,
  busy,
  queued,
  onQueue,
}: {
  pdf: PdfCandidate;
  busy: boolean;
  queued: boolean;
  onQueue: (evidence: AccessEvidence) => void;
}) {
  const evidence = pdf.access_evidence;
  const isOpenAccess = openAccessEvidence(pdf);
  return (
    <div className="flex min-w-0 flex-col gap-2 border-t border-outline-variant/45 py-3 first:border-t-0 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusPill tone={isOpenAccess ? 'success' : 'warning'} icon={isOpenAccess ? <ShieldCheck size={10} /> : <AlertTriangle size={10} />}>
            {isOpenAccess ? '开放获取已核验' : '不可自动下载'}
          </StatusPill>
          <StatusPill tone="neutral">{sourceLabel(evidence.source_platform)}</StatusPill>
          {evidence.license ? <StatusPill tone="info">{evidence.license}</StatusPill> : null}
        </div>
        <p className="mt-1.5 break-words text-xs leading-5 text-foreground/55">
          {safeEvidenceStatement(evidence.statement)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <a
          href={evidence.pdf_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 font-label text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
        >
          <ExternalLink size={13} />
          查看来源
        </a>
        <button
          type="button"
          disabled={!isOpenAccess || busy || queued}
          onClick={() => onQueue(evidence)}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : queued ? <Check size={13} /> : <Download size={13} />}
          {queued ? '已排队' : '加入下载队列'}
        </button>
      </div>
    </div>
  );
}

export function LiteratureAcquisition() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeProjectId, setActiveProjectId } = useWriting();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [statusSnapshot, setStatusSnapshot] = useState<ProjectStatusSnapshot | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [yearFrom, setYearFrom] = useState('');
  const [yearTo, setYearTo] = useState('');
  const [maxResults, setMaxResults] = useState('20');
  const [searching, setSearching] = useState(false);
  const [searchRun, setSearchRun] = useState<SearchRun | null>(null);
  const [searchError, setSearchError] = useState('');
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [receiptsByJob, setReceiptsByJob] = useState<Record<string, ImportReceipt>>({});
  const [gateModal, setGateModal] = useState<HumanAccessGate | null>(null);
  const [gateConfirmed, setGateConfirmed] = useState(false);

  const routeProjectId = (searchParams.get('project_id') ?? '').trim();
  const selectedProjectId = routeProjectId || activeProjectId;
  const status = statusSnapshot?.projectId === selectedProjectId ? statusSnapshot.value : null;
  const selectedProjectIdRef = useRef(selectedProjectId);
  const projectStateIdRef = useRef(selectedProjectId);
  const projectGenerationRef = useRef(0);
  const projectsRequestGenerationRef = useRef(0);
  const statusAuthorityGenerationRef = useRef(0);
  const statusSnapshotRef = useRef<ProjectStatusSnapshot | null>(null);
  const visibleJobsRef = useRef<Map<string, DownloadJob>>(new Map());

  const isCurrentProjectGeneration = useCallback((projectId: string, generation: number): boolean => (
    Boolean(projectId)
    && selectedProjectIdRef.current === projectId
    && projectGenerationRef.current === generation
  ), []);

  const commitStatus = useCallback((
    projectId: string,
    generation: number,
    nextStatus: AcquisitionStatus,
  ): boolean => {
    if (!isCurrentProjectGeneration(projectId, generation)) return false;
    const scopedStatus: AcquisitionStatus = {
      ...nextStatus,
      download_jobs: nextStatus.download_jobs.filter((job) => job.project_id === projectId),
      gates: nextStatus.gates.filter((gate) => gate.project_id === projectId),
    };
    const nextSnapshot: ProjectStatusSnapshot = { projectId, value: scopedStatus };
    statusSnapshotRef.current = nextSnapshot;
    visibleJobsRef.current = new Map(scopedStatus.download_jobs.map((job) => [job.job_id, job]));
    setStatusSnapshot(nextSnapshot);
    return true;
  }, [isCurrentProjectGeneration]);

  const invalidateStatusReads = useCallback((): void => {
    statusAuthorityGenerationRef.current += 1;
    setStatusLoading(false);
  }, []);

  const resetProjectState = useCallback((projectId: string): number => {
    selectedProjectIdRef.current = projectId;
    projectStateIdRef.current = projectId;
    projectGenerationRef.current += 1;
    invalidateStatusReads();
    statusSnapshotRef.current = null;
    visibleJobsRef.current = new Map();
    setStatusSnapshot(null);
    setStatusLoading(Boolean(projectId));
    setStatusError('');
    setSelectedSources(new Set());
    setSearchRun(null);
    setSearchError('');
    setSearching(false);
    setBusyAction(null);
    setFeedback(null);
    setReceiptsByJob({});
    setGateModal(null);
    setGateConfirmed(false);
    return projectGenerationRef.current;
  }, [invalidateStatusReads]);

  const loadProjects = useCallback(async (): Promise<void> => {
    const requestGeneration = projectsRequestGenerationRef.current + 1;
    projectsRequestGenerationRef.current = requestGeneration;
    const requestIsCurrent = (): boolean => projectsRequestGenerationRef.current === requestGeneration;
    setProjectsLoading(true);
    try {
      const list = await getWritingBackendService().listProjects();
      if (!requestIsCurrent()) return;
      const options = list.map((project: WritingProject): ProjectOption => ({
        id: project.project_id,
        title: project.title || '未命名项目',
      }));
      setProjects(options);
      const preferred = routeProjectId && options.some((project) => project.id === routeProjectId)
        ? routeProjectId
        : activeProjectId && options.some((project) => project.id === activeProjectId)
          ? activeProjectId
          : options[0]?.id ?? '';
      if (preferred && preferred !== activeProjectId) setActiveProjectId(preferred);
      if (preferred && preferred !== routeProjectId) {
        const next = new URLSearchParams(searchParams);
        next.set('project_id', preferred);
        setSearchParams(next, { replace: true });
      }
    } catch {
      if (requestIsCurrent()) setProjects([]);
    } finally {
      if (requestIsCurrent()) setProjectsLoading(false);
    }
  }, [activeProjectId, routeProjectId, searchParams, setActiveProjectId, setSearchParams]);

  useEffect(() => {
    void loadProjects();
    return () => {
      projectsRequestGenerationRef.current += 1;
    };
  }, [loadProjects]);

  const refreshStatusForProject = useCallback(async (
    projectId: string,
    projectGeneration: number,
  ): Promise<void> => {
    const requestGeneration = statusAuthorityGenerationRef.current + 1;
    statusAuthorityGenerationRef.current = requestGeneration;
    const requestIsCurrent = (): boolean => (
      statusAuthorityGenerationRef.current === requestGeneration
      && isCurrentProjectGeneration(projectId, projectGeneration)
    );
    if (!projectId) {
      if (projectStateIdRef.current === projectId) {
        statusSnapshotRef.current = null;
        visibleJobsRef.current = new Map();
        setStatusSnapshot(null);
        setStatusLoading(false);
      }
      return;
    }
    if (requestIsCurrent()) {
      setStatusLoading(true);
      setStatusError('');
    }
    try {
      const nextStatus = await getAcquisitionStatus(projectId, 100);
      if (!requestIsCurrent() || !commitStatus(projectId, projectGeneration, nextStatus)) return;
      setSelectedSources((current) => {
        const allowed = new Set(
          nextStatus.sources
            .filter((source) => source.enabled && source.capabilities.includes('search'))
            .map((source) => source.source_id),
        );
        const preserved = [...current].filter((sourceId) => allowed.has(sourceId));
        return new Set(preserved.length > 0 ? preserved : allowed);
      });
    } catch (error: unknown) {
      if (requestIsCurrent()) {
        setStatusError(acquisitionErrorMessage(error, '文献获取服务暂时不可用，请稍后刷新。'));
      }
    } finally {
      if (requestIsCurrent()) setStatusLoading(false);
    }
  }, [commitStatus, isCurrentProjectGeneration]);

  const refreshStatus = useCallback(async (): Promise<void> => {
    await refreshStatusForProject(selectedProjectIdRef.current, projectGenerationRef.current);
  }, [refreshStatusForProject]);

  useEffect(() => {
    const projectGeneration = projectStateIdRef.current === selectedProjectId
      ? projectGenerationRef.current
      : resetProjectState(selectedProjectId);
    selectedProjectIdRef.current = selectedProjectId;
    void refreshStatusForProject(selectedProjectId, projectGeneration);
  }, [refreshStatusForProject, resetProjectState, selectedProjectId]);

  const enabledSearchSources = useMemo(
    () => status?.sources.filter((source) => source.enabled && source.capabilities.includes('search')) ?? [],
    [status?.sources],
  );
  const candidateById = useMemo(
    () => new Map((searchRun?.candidates ?? []).map((candidate) => [candidate.candidate_id, candidate])),
    [searchRun?.candidates],
  );
  const jobs = useMemo(
    () => [...(status?.download_jobs ?? [])].sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at)),
    [status?.download_jobs],
  );
  const openGates = useMemo(
    () => (status?.gates ?? []).filter((gate) => gate.status === 'open'),
    [status?.gates],
  );

  const handleProjectChange = (projectId: string): void => {
    projectsRequestGenerationRef.current += 1;
    if (projectId !== projectStateIdRef.current) resetProjectState(projectId);
    setActiveProjectId(projectId);
    const next = new URLSearchParams(searchParams);
    next.set('project_id', projectId);
    setSearchParams(next, { replace: true });
  };

  const toggleSource = (sourceId: string): void => {
    setSelectedSources((current) => {
      const next = new Set(current);
      if (next.has(sourceId)) next.delete(sourceId);
      else next.add(sourceId);
      return next;
    });
  };

  const handleSearch = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!selectedProjectId || !query.trim() || selectedSources.size === 0 || searching) return;
    const requestProjectId = selectedProjectIdRef.current;
    const projectGeneration = projectGenerationRef.current;
    if (!isCurrentProjectGeneration(requestProjectId, projectGeneration)) return;
    const parsedYearFrom = yearFrom ? Number(yearFrom) : null;
    const parsedYearTo = yearTo ? Number(yearTo) : null;
    if (
      (parsedYearFrom !== null && (!Number.isInteger(parsedYearFrom) || parsedYearFrom < 1800 || parsedYearFrom > 2200))
      || (parsedYearTo !== null && (!Number.isInteger(parsedYearTo) || parsedYearTo < 1800 || parsedYearTo > 2200))
      || (parsedYearFrom !== null && parsedYearTo !== null && parsedYearTo < parsedYearFrom)
    ) {
      setSearchError('请填写 1800 至 2200 之间的有效年份范围。');
      return;
    }
    setSearching(true);
    setSearchError('');
    setFeedback(null);
    try {
      const run = await searchAcquisition({
        projectId: requestProjectId,
        query,
        sources: [...selectedSources],
        maxResults: Number(maxResults),
        yearFrom: parsedYearFrom,
        yearTo: parsedYearTo,
      });
      if (!isCurrentProjectGeneration(requestProjectId, projectGeneration)) return;
      setSearchRun(run);
      if (run.candidates.length === 0) {
        setFeedback({ tone: 'info', message: '检索已完成，没有找到符合条件的候选文献。' });
      } else if (run.source_errors.length > 0) {
        setFeedback({ tone: 'info', message: `找到 ${run.candidates.length} 条候选；部分来源暂不可用。` });
      } else {
        setFeedback({ tone: 'success', message: `检索完成，共找到 ${run.candidates.length} 条候选文献。` });
      }
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(requestProjectId, projectGeneration)) {
        setSearchError(acquisitionErrorMessage(error, '文献检索失败，请稍后重试。'));
      }
    } finally {
      if (isCurrentProjectGeneration(requestProjectId, projectGeneration)) setSearching(false);
    }
  };

  const updateJob = useCallback((
    job: DownloadJob,
    projectId: string,
    projectGeneration: number,
  ): boolean => {
    const current = statusSnapshotRef.current;
    if (
      job.project_id !== projectId
      || !current
      || current.projectId !== projectId
      || !isCurrentProjectGeneration(projectId, projectGeneration)
    ) {
      return false;
    }
    invalidateStatusReads();
    return commitStatus(projectId, projectGeneration, {
      ...current.value,
      download_jobs: upsertJob(current.value.download_jobs, job),
    });
  }, [commitStatus, invalidateStatusReads, isCurrentProjectGeneration]);

  const isCurrentVisibleJob = useCallback((job: DownloadJob): boolean => {
    const projectId = selectedProjectIdRef.current;
    return Boolean(
      projectId
      && job.project_id === projectId
      && visibleJobsRef.current.get(job.job_id) === job,
    );
  }, []);

  const handleQueue = async (candidate: CandidateManifest, evidence: AccessEvidence): Promise<void> => {
    const projectId = selectedProjectIdRef.current;
    const projectGeneration = projectGenerationRef.current;
    if (
      evidence.access_route !== 'open_access'
      || busyAction
      || candidate.project_id !== projectId
      || !isCurrentProjectGeneration(projectId, projectGeneration)
    ) return;
    invalidateStatusReads();
    const actionKey = `queue:${evidence.evidence_id}`;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      const job = await queueAcquisitionDownload(projectId, candidate.candidate_id, evidence.evidence_id);
      if (!updateJob(job, projectId, projectGeneration)) return;
      setFeedback({ tone: 'success', message: '已加入队列。下载不会自动开始，请在任务栏显式点击“开始”。' });
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '下载任务创建失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((current) => current === actionKey ? null : current);
      }
    }
  };

  const handleRun = async (job: DownloadJob): Promise<void> => {
    if (busyAction || !isCurrentVisibleJob(job)) return;
    const projectId = job.project_id;
    const projectGeneration = projectGenerationRef.current;
    invalidateStatusReads();
    const actionKey = `run:${job.job_id}`;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      const nextJob = await runAcquisitionDownload(job.job_id);
      if (!updateJob(nextJob, projectId, projectGeneration)) return;
      if (nextJob.status === 'completed') {
        setFeedback({ tone: 'success', message: 'PDF 已完成大小、格式、可读性和完整性校验，可以导入项目。' });
      } else if (nextJob.status === 'human_required') {
        await refreshStatus();
        if (!isCurrentProjectGeneration(projectId, projectGeneration)) return;
        setFeedback({ tone: 'info', message: '来源要求人工处理。系统已停止自动访问，请在访问要求中继续。' });
      } else if (nextJob.status === 'failed') {
        setFeedback({ tone: 'danger', message: '本次下载未完成。可检查来源状态后显式重试。' });
      }
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '下载执行失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((current) => current === actionKey ? null : current);
      }
    }
  };

  const handleControl = async (job: DownloadJob, action: DownloadControlAction): Promise<void> => {
    if (busyAction || !isCurrentVisibleJob(job)) return;
    const projectId = job.project_id;
    const projectGeneration = projectGenerationRef.current;
    invalidateStatusReads();
    const actionKey = `${action}:${job.job_id}`;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      const nextJob = await controlAcquisitionDownload(job.job_id, action);
      if (!updateJob(nextJob, projectId, projectGeneration)) return;
      const labels: Record<DownloadControlAction, string> = {
        pause: '任务已暂停，已下载的分段会保留。',
        resume: '任务已恢复到等待状态，仍需显式点击“开始”。',
        cancel: '任务已取消。',
      };
      setFeedback({
        tone: 'success',
        message: action === 'cancel' && job.status === 'cancelled'
          ? '取消后的本地文件清理已重试。'
          : labels[action],
      });
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '任务状态更新失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((current) => current === actionKey ? null : current);
      }
    }
  };

  const handleImport = async (job: DownloadJob): Promise<void> => {
    if (!job.artifact_id || job.status !== 'completed' || busyAction || !isCurrentVisibleJob(job)) return;
    const projectId = job.project_id;
    const projectGeneration = projectGenerationRef.current;
    const actionKey = `import:${job.job_id}`;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      const receipt = await importAcquisitionArtifact(job.artifact_id);
      if (
        receipt.project_id !== projectId
        || !isCurrentProjectGeneration(projectId, projectGeneration)
      ) return;
      setReceiptsByJob((current) => ({ ...current, [job.job_id]: receipt }));
      if (receipt.status === 'failed' || receipt.publication_state === 'failed') {
        setFeedback({ tone: 'danger', message: '导入未完成，请稍后重试。' });
      } else if (isVerifiedImportReceipt(receipt)) {
        setFeedback({ tone: 'success', message: '材料入库、索引与发布校验已完成。' });
      } else if (receipt.publication_state === 'pending') {
        setFeedback({ tone: 'info', message: '已提交入库，发布校验尚未完成。' });
      } else {
        setFeedback({ tone: 'info', message: '旧版导入回执未包含发布校验证据。' });
      }
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '文献导入失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((current) => current === actionKey ? null : current);
      }
    }
  };

  const handleReceiptRefresh = async (job: DownloadJob, receipt: ImportReceipt): Promise<void> => {
    if (busyAction || !isCurrentVisibleJob(job) || receipt.project_id !== job.project_id) return;
    const projectId = job.project_id;
    const projectGeneration = projectGenerationRef.current;
    const actionKey = `receipt:${receipt.receipt_id}`;
    setBusyAction(actionKey);
    try {
      const nextReceipt = await getAcquisitionImportReceipt(receipt.receipt_id);
      if (
        nextReceipt.project_id !== projectId
        || !isCurrentProjectGeneration(projectId, projectGeneration)
      ) return;
      setReceiptsByJob((current) => ({ ...current, [job.job_id]: nextReceipt }));
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '导入状态读取失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((current) => current === actionKey ? null : current);
      }
    }
  };

  const openGateModal = (gate: HumanAccessGate): void => {
    const projectId = selectedProjectIdRef.current;
    const current = statusSnapshotRef.current;
    if (
      gate.project_id !== projectId
      || current?.projectId !== projectId
      || !current.value.gates.some((visibleGate) => visibleGate === gate)
    ) return;
    setGateModal(gate);
    setGateConfirmed(false);
  };

  const closeGateModal = (): void => {
    if (busyAction?.startsWith('gate:')) return;
    setGateModal(null);
    setGateConfirmed(false);
  };

  const handleGateResolve = async (): Promise<void> => {
    if (!gateModal || !gateConfirmed || busyAction) return;
    const projectId = selectedProjectIdRef.current;
    const projectGeneration = projectGenerationRef.current;
    const current = statusSnapshotRef.current;
    if (
      gateModal.project_id !== projectId
      || current?.projectId !== projectId
      || !current.value.gates.some((gate) => gate === gateModal)
    ) return;
    invalidateStatusReads();
    const actionKey = `gate:${gateModal.gate_id}`;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      const resolved = await resolveAcquisitionGate(gateModal.gate_id);
      const latest = statusSnapshotRef.current;
      if (
        resolved.gate.project_id !== projectId
        || (resolved.download_job !== null && resolved.download_job.project_id !== projectId)
        || latest?.projectId !== projectId
        || !isCurrentProjectGeneration(projectId, projectGeneration)
      ) return;
      invalidateStatusReads();
      const nextStatus: AcquisitionStatus = {
        ...latest.value,
        gates: latest.value.gates.map((gate) => gate.gate_id === resolved.gate.gate_id ? resolved.gate : gate),
        download_jobs: resolved.download_job
          ? upsertJob(latest.value.download_jobs, resolved.download_job)
          : latest.value.download_jobs,
      };
      if (!commitStatus(projectId, projectGeneration, nextStatus)) return;
      setGateModal(null);
      setGateConfirmed(false);
      setFeedback({ tone: 'success', message: '人工访问步骤已确认。任务已回到等待状态，不会自动继续下载。' });
    } catch (error: unknown) {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setFeedback({ tone: 'danger', message: acquisitionErrorMessage(error, '访问确认失败。') });
      }
    } finally {
      if (isCurrentProjectGeneration(projectId, projectGeneration)) {
        setBusyAction((currentAction) => currentAction === actionKey ? null : currentAction);
      }
    }
  };

  const queuedEvidenceIds = useMemo(
    () => new Set(jobs.map((job) => job.access_evidence_id)),
    [jobs],
  );

  const noProjects = !projectsLoading && projects.length === 0;
  const canSearch = Boolean(
    selectedProjectId
    && query.trim()
    && selectedSources.size > 0
    && !searching
    && enabledSearchSources.length > 0,
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="page-top-band shrink-0 px-4 py-4 sm:px-6 sm:py-5">
        <PageHeader
          icon={<BookDown size={18} />}
          title="文献获取"
          subtitle="按项目检索可核验来源，显式下载、校验并导入现有材料库。"
          className="mb-0"
          actions={
            <>
              <label className="sr-only" htmlFor="acquisition-project">选择项目</label>
              <select
                id="acquisition-project"
                value={selectedProjectId}
                onChange={(event) => handleProjectChange(event.target.value)}
                disabled={projectsLoading || projects.length === 0}
                className="h-9 min-w-0 max-w-[260px] rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs text-foreground outline-none transition-colors focus:border-primary/50 focus:ring-2 focus:ring-primary/15 disabled:opacity-55"
              >
                {projects.length === 0 ? <option value="">暂无项目</option> : null}
                {projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
              </select>
              <button
                type="button"
                onClick={() => void refreshStatus()}
                disabled={!selectedProjectId || statusLoading}
                className="inline-flex h-9 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:opacity-50"
              >
                <RefreshCw size={13} className={statusLoading ? 'animate-spin' : ''} />
                刷新状态
              </button>
            </>
          }
        />
      </div>

      {noProjects ? (
        <EmptyState
          icon={<FolderKanban size={34} />}
          title="先创建一个研究项目"
          description="文献检索、下载记录和导入回执都必须归属明确项目。"
          action={
            <button
              type="button"
              onClick={() => navigate('/projects')}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 font-label text-xs font-medium text-primary-foreground"
            >
              <FolderKanban size={14} />
              前往项目管理
            </button>
          }
          className="min-h-0 flex-1"
        />
      ) : (
        <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {feedback ? (
            <div role="status" className={cn('mb-4 flex items-start gap-2 rounded-md border px-3 py-2.5 font-label text-xs leading-5', feedbackClasses(feedback.tone))}>
              {feedback.tone === 'danger' ? <AlertTriangle size={14} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={14} className="mt-0.5 shrink-0" />}
              <span className="min-w-0 break-words">{feedback.message}</span>
            </div>
          ) : null}
          {statusError ? (
            <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-800 dark:border-red-800/50 dark:bg-red-950/35 dark:text-red-200">
              <span>{statusError}</span>
              <button type="button" onClick={() => void refreshStatus()} className="shrink-0 font-medium underline underline-offset-2">重试</button>
            </div>
          ) : null}

          <div className="grid min-h-full gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.85fr)]">
            <section aria-labelledby="acquisition-search-title" className="min-w-0 overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest">
              <form onSubmit={(event) => void handleSearch(event)} className="border-b border-outline-variant/55 bg-surface-low px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 id="acquisition-search-title" className="font-display text-sm font-semibold text-foreground">检索开放文献</h2>
                    <p className="mt-1 text-xs leading-5 text-foreground/50">仅查询已启用的来源适配器；检索不会创建下载任务。</p>
                  </div>
                  {searchRun ? <StatusPill tone={searchRun.status === 'failed' ? 'danger' : searchRun.status === 'partial' ? 'warning' : 'success'}>{searchRun.status === 'partial' ? '部分完成' : searchRun.status === 'failed' ? '检索失败' : '检索完成'}</StatusPill> : null}
                </div>
                <div className="mt-4 flex min-w-0 flex-col gap-2 sm:flex-row">
                  <label className="relative min-w-0 flex-1">
                    <span className="sr-only">检索词</span>
                    <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground/35" />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      maxLength={1000}
                      placeholder="标题、主题、作者或 DOI"
                      className="h-10 w-full rounded-md border border-outline-variant/60 bg-surface-lowest pl-9 pr-3 text-sm text-foreground outline-none transition-colors placeholder:text-foreground/30 focus:border-primary/50 focus:ring-2 focus:ring-primary/15"
                    />
                  </label>
                  <button
                    type="submit"
                    disabled={!canSearch}
                    className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-md bg-primary px-4 font-label text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                    显式检索
                  </button>
                </div>

                <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_108px_108px_96px] sm:items-end">
                  <fieldset className="min-w-0">
                    <legend className="mb-1.5 font-label text-[11px] font-medium text-foreground/55">检索来源</legend>
                    {statusLoading && !status ? (
                      <span className="inline-flex h-8 items-center gap-1.5 text-xs text-foreground/45"><Loader2 size={13} className="animate-spin" />读取来源</span>
                    ) : enabledSearchSources.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {enabledSearchSources.map((source) => {
                          const checked = selectedSources.has(source.source_id);
                          return (
                            <label key={source.source_id} className={cn('inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 font-label text-xs transition-colors', checked ? 'border-primary/40 bg-primary/10 text-primary' : 'border-outline-variant/60 bg-surface-lowest text-foreground/55 hover:border-primary/30')}>
                              <input type="checkbox" className="sr-only" checked={checked} onChange={() => toggleSource(source.source_id)} />
                              <span className={cn('flex h-3.5 w-3.5 items-center justify-center rounded-sm border', checked ? 'border-primary bg-primary text-primary-foreground' : 'border-outline-variant')}>
                                {checked ? <Check size={10} /> : null}
                              </span>
                              {sourceLabel(source.source_id)}
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-foreground/45">当前没有可用的检索来源。</p>
                    )}
                  </fieldset>
                  <label className="font-label text-[11px] font-medium text-foreground/55">
                    起始年份
                    <input type="number" min={1800} max={2200} value={yearFrom} onChange={(event) => setYearFrom(event.target.value)} placeholder="不限" className="mt-1.5 h-8 w-full rounded-md border border-outline-variant/60 bg-surface-lowest px-2 text-xs text-foreground outline-none focus:border-primary/50" />
                  </label>
                  <label className="font-label text-[11px] font-medium text-foreground/55">
                    截止年份
                    <input type="number" min={1800} max={2200} value={yearTo} onChange={(event) => setYearTo(event.target.value)} placeholder="不限" className="mt-1.5 h-8 w-full rounded-md border border-outline-variant/60 bg-surface-lowest px-2 text-xs text-foreground outline-none focus:border-primary/50" />
                  </label>
                  <label className="font-label text-[11px] font-medium text-foreground/55">
                    结果上限
                    <select value={maxResults} onChange={(event) => setMaxResults(event.target.value)} className="mt-1.5 h-8 w-full rounded-md border border-outline-variant/60 bg-surface-lowest px-2 text-xs text-foreground outline-none focus:border-primary/50">
                      <option value="10">10</option>
                      <option value="20">20</option>
                      <option value="50">50</option>
                    </select>
                  </label>
                </div>
                {searchError ? <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-300">{searchError}</p> : null}
              </form>

              <div className="min-h-[320px]">
                {searching ? (
                  <div className="flex min-h-[320px] flex-col items-center justify-center gap-2 text-foreground/45">
                    <Loader2 size={24} className="animate-spin text-primary" />
                    <p className="font-label text-xs">正在查询所选来源...</p>
                  </div>
                ) : !searchRun ? (
                  <EmptyState icon={<Search size={30} />} title="输入检索条件开始" description="候选结果只包含元数据和访问依据；任何下载都需要再次确认。" className="min-h-[320px]" />
                ) : searchRun.candidates.length === 0 ? (
                  <EmptyState icon={<Search size={30} />} title="没有找到候选文献" description="可以调整关键词、年份或来源后重新检索。" className="min-h-[320px]" />
                ) : (
                  <div className="divide-y divide-outline-variant/55">
                    {searchRun.candidates.map((candidate) => (
                      <article key={candidate.candidate_id} className="px-4 py-4 sm:px-5">
                        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0 flex-1">
                            <h3 className="break-words font-display text-sm font-semibold leading-5 text-foreground">{candidate.title}</h3>
                            <p className="mt-1 break-words text-xs leading-5 text-foreground/50">{candidateSecondaryLine(candidate)}</p>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {candidate.source_platforms.map((source) => <StatusPill key={source} tone="neutral">{sourceLabel(source)}</StatusPill>)}
                              {candidate.doi ? <StatusPill tone="info">DOI 已匹配</StatusPill> : null}
                              {candidate.merged_from_candidate_ids.length > 0 ? <StatusPill tone="primary">多来源合并</StatusPill> : null}
                            </div>
                          </div>
                          <StatusPill tone={candidate.pdf_candidates.some(openAccessEvidence) ? 'success' : 'warning'}>
                            {candidate.pdf_candidates.some(openAccessEvidence) ? `${candidate.pdf_candidates.filter(openAccessEvidence).length} 个 OA 入口` : '无 OA 下载依据'}
                          </StatusPill>
                        </div>
                        {candidate.abstract ? <p className="mt-3 line-clamp-3 break-words text-xs leading-5 text-foreground/55">{candidate.abstract}</p> : null}
                        <div className="mt-3">
                          {candidate.pdf_candidates.length > 0 ? candidate.pdf_candidates.map((pdf) => (
                            <EvidenceRow
                              key={pdf.access_evidence.evidence_id}
                              pdf={pdf}
                              busy={busyAction === `queue:${pdf.access_evidence.evidence_id}`}
                              queued={queuedEvidenceIds.has(pdf.access_evidence.evidence_id)}
                              onQueue={(evidence) => void handleQueue(candidate, evidence)}
                            />
                          )) : (
                            <div className="border-t border-outline-variant/45 pt-3 text-xs text-foreground/45">未提供可核验的 PDF 访问依据，因此不能加入下载队列。</div>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </section>

            <aside className="min-w-0 space-y-4">
              <section aria-labelledby="access-gates-title" className="overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest">
                <div className="flex items-center justify-between gap-3 border-b border-outline-variant/55 bg-surface-low px-4 py-3">
                  <div>
                    <h2 id="access-gates-title" className="font-display text-sm font-semibold text-foreground">访问要求</h2>
                    <p className="mt-0.5 text-[11px] text-foreground/45">登录、验证码、付费墙和限流由用户处理。</p>
                  </div>
                  <StatusPill tone={openGates.length > 0 ? 'warning' : 'neutral'}>{openGates.length} 项</StatusPill>
                </div>
                {openGates.length === 0 ? (
                  <div className="px-4 py-5 text-center text-xs text-foreground/45">当前没有待处理的访问要求。</div>
                ) : (
                  <div className="divide-y divide-outline-variant/55">
                    {openGates.map((gate) => (
                      <div key={gate.gate_id} className="flex items-center gap-3 px-4 py-3">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"><ShieldCheck size={15} /></span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-label text-xs font-semibold text-foreground/75">{GATE_LABELS[gate.gate_type] ?? '人工访问要求'}</p>
                          <p className="mt-0.5 truncate text-[11px] text-foreground/45">{sourceLabel(gate.platform)}</p>
                        </div>
                        <button type="button" onClick={() => openGateModal(gate)} className="inline-flex h-8 shrink-0 items-center rounded-md border border-amber-300/70 bg-amber-50 px-2.5 font-label text-xs font-medium text-amber-800 transition-colors hover:bg-amber-100 dark:border-amber-800/50 dark:bg-amber-950/35 dark:text-amber-200">处理</button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section aria-labelledby="download-jobs-title" className="overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest">
                <div className="flex items-center justify-between gap-3 border-b border-outline-variant/55 bg-surface-low px-4 py-3">
                  <div>
                    <h2 id="download-jobs-title" className="font-display text-sm font-semibold text-foreground">下载与导入</h2>
                    <p className="mt-0.5 text-[11px] text-foreground/45">队列不会自动运行；校验通过后才能导入。</p>
                  </div>
                  <StatusPill tone={jobs.some((job) => job.status === 'failed') ? 'danger' : jobs.some((job) => ['queued', 'running', 'paused', 'validating'].includes(job.status)) ? 'info' : 'neutral'}>{jobs.length} 项</StatusPill>
                </div>
                {statusLoading && !status ? (
                  <div className="flex min-h-[180px] items-center justify-center gap-2 text-xs text-foreground/45"><Loader2 size={16} className="animate-spin" />读取任务</div>
                ) : jobs.length === 0 ? (
                  <div className="px-4 py-8 text-center">
                    <Clock3 size={24} className="mx-auto text-foreground/20" />
                    <p className="mt-2 text-xs text-foreground/45">还没有下载任务。</p>
                  </div>
                ) : (
                  <div className="divide-y divide-outline-variant/55">
                    {jobs.map((job) => {
                      const candidate = candidateById.get(job.candidate_id);
                      const receipt = receiptsByJob[job.job_id];
                      const receiptVerified = receipt ? isVerifiedImportReceipt(receipt) : false;
                      const actionBusy = busyAction?.endsWith(`:${job.job_id}`) ?? false;
                      const canRun = ['queued', 'paused', 'failed'].includes(job.status);
                      const canPause = ['queued', 'running'].includes(job.status);
                      const canResume = job.status === 'paused';
                      const cleanupRetryable = job.status === 'cancelled' && job.error_code === 'cancel_cleanup_failed';
                      const canCancel = !['completed', 'cancelled'].includes(job.status) || cleanupRetryable;
                      return (
                        <article key={job.job_id} className="px-4 py-4">
                          <div className="flex min-w-0 items-start gap-3">
                            <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-md', job.status === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : job.status === 'failed' ? 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300' : 'bg-surface-high text-foreground/55')}>
                              {job.status === 'completed' ? <FileCheck2 size={15} /> : job.status === 'running' || job.status === 'validating' ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="line-clamp-2 break-words font-label text-xs font-semibold leading-5 text-foreground/75">{candidate?.title ?? `${sourceLabel(job.source_platform)} 下载任务`}</p>
                              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                                <StatusPill tone={JOB_TONES[job.status]}>{JOB_LABELS[job.status]}</StatusPill>
                                <span className="text-[10px] text-foreground/40">{formatBytes(job.bytes_downloaded)} · {formatDateTime(job.updated_at)}</span>
                              </div>
                            </div>
                          </div>

                          {job.status === 'failed' ? <p className="mt-2 rounded-md bg-red-50 px-2.5 py-2 text-[11px] leading-4 text-red-700 dark:bg-red-950/30 dark:text-red-300">本次执行未完成。系统已停止访问，可在确认来源可用后重试。</p> : null}
                          {job.status === 'human_required' ? <p className="mt-2 rounded-md bg-amber-50 px-2.5 py-2 text-[11px] leading-4 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200">自动下载已停止，请先处理上方访问要求。</p> : null}
                          {cleanupRetryable ? <p className="mt-2 rounded-md bg-red-50 px-2.5 py-2 text-[11px] leading-4 text-red-700 dark:bg-red-950/30 dark:text-red-300">取消后的本地文件清理未完成，残留文件和校验凭据仍待清除，可重试清理。</p> : null}

                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {canRun ? (
                              <button type="button" onClick={() => void handleRun(job)} disabled={Boolean(busyAction)} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-45">
                                {busyAction === `run:${job.job_id}` ? <Loader2 size={13} className="animate-spin" /> : job.status === 'failed' ? <RotateCcw size={13} /> : <Play size={13} />}
                                {job.status === 'failed' ? '重试' : '开始'}
                              </button>
                            ) : null}
                            {canPause ? <button type="button" onClick={() => void handleControl(job, 'pause')} disabled={Boolean(busyAction)} title="暂停" aria-label="暂停下载" className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 text-foreground/60 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-45">{busyAction === `pause:${job.job_id}` ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}</button> : null}
                            {canResume ? <button type="button" onClick={() => void handleControl(job, 'resume')} disabled={Boolean(busyAction)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-outline-variant/60 px-2.5 font-label text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-45">{busyAction === `resume:${job.job_id}` ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}恢复到队列</button> : null}
                            {canCancel ? <button type="button" onClick={() => void handleControl(job, 'cancel')} disabled={Boolean(busyAction)} title={cleanupRetryable ? '重试清理' : '取消'} aria-label={cleanupRetryable ? '重试清理' : '取消下载'} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 text-foreground/55 transition-colors hover:border-red-300 hover:text-red-600 disabled:opacity-45">{busyAction === `cancel:${job.job_id}` ? <Loader2 size={13} className="animate-spin" /> : cleanupRetryable ? <RefreshCw size={13} /> : <Square size={13} />}</button> : null}
                            {job.status === 'completed' && job.artifact_id ? (
                              <button type="button" onClick={() => void handleImport(job)} disabled={Boolean(busyAction) || Boolean(receipt && receipt.status !== 'failed')} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-45">
                                {busyAction === `import:${job.job_id}` ? <Loader2 size={13} className="animate-spin" /> : <BookDown size={13} />}
                                {receipt ? '已提交导入' : '导入项目'}
                              </button>
                            ) : null}
                          </div>

                          {receipt ? (
                            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-outline-variant/45 pt-3">
                              <StatusPill tone={receiptTone(receipt)} icon={receiptVerified ? <CheckCircle2 size={10} /> : receipt.status === 'failed' || receipt.publication_state === 'failed' ? <AlertTriangle size={10} /> : <Clock3 size={10} />}>{receiptLabel(receipt)}</StatusPill>
                              {isPublicationRetryableReceipt(receipt) ? <button type="button" onClick={() => void handleReceiptRefresh(job, receipt)} disabled={Boolean(busyAction)} title={receipt.status === 'queued' ? '刷新导入状态' : '重试发布校验'} className="inline-flex h-7 items-center gap-1 rounded-md border border-outline-variant/60 px-2 text-[11px] text-foreground/60 hover:border-primary/35 hover:text-primary disabled:opacity-45">{busyAction === `receipt:${receipt.receipt_id}` ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}{receipt.status === 'queued' ? '刷新导入' : '刷新发布校验'}</button> : null}
                              {receiptVerified ? <button type="button" onClick={() => navigate(receipt.open_url)} className="inline-flex h-7 items-center gap-1 rounded-md border border-outline-variant/60 px-2 text-[11px] text-foreground/60 hover:border-primary/35 hover:text-primary"><ExternalLink size={11} />打开文献</button> : null}
                            </div>
                          ) : null}
                          {actionBusy ? <span className="sr-only" role="status">正在更新任务</span> : null}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>
            </aside>
          </div>
        </div>
      )}

      <Modal open={Boolean(gateModal)} onClose={closeGateModal} closeOnBackdrop={!busyAction?.startsWith('gate:')} size="lg" labelledBy="acquisition-gate-title" describedBy="acquisition-gate-description">
        <ModalHeader>
          <div className="flex items-center gap-3 pr-8">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"><ShieldCheck size={17} /></span>
            <div className="min-w-0">
              <h2 id="acquisition-gate-title" className="font-display text-base font-semibold text-foreground">{gateModal ? GATE_LABELS[gateModal.gate_type] ?? '人工访问要求' : '人工访问要求'}</h2>
              <p className="mt-0.5 text-xs text-foreground/45">{gateModal ? sourceLabel(gateModal.platform) : ''}</p>
            </div>
          </div>
        </ModalHeader>
        <ModalBody>
          <div id="acquisition-gate-description" className="space-y-4 text-sm leading-6 text-foreground/65">
            <p>自动访问已停止。仅在你拥有合法访问权限并完成来源页面要求后，才能确认继续。</p>
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900 dark:border-amber-800/50 dark:bg-amber-950/35 dark:text-amber-100">
              Scholar AI 不会绕过登录、验证码、付费墙、机构认证、robots 或访问频率限制。
            </div>
            {gateModal ? (
              <a href={gateModal.url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35">
                <ExternalLink size={14} />
                打开来源页面
              </a>
            ) : null}
            <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-outline-variant/60 px-3 py-3">
              <input type="checkbox" checked={gateConfirmed} onChange={(event) => setGateConfirmed(event.target.checked)} className="mt-0.5 h-4 w-4 accent-primary" />
              <span className="text-xs leading-5 text-foreground/65">我确认已在来源页面完成必要步骤，并且此次访问符合我的授权范围。</span>
            </label>
          </div>
        </ModalBody>
        <ModalFooter>
          <button type="button" onClick={closeGateModal} disabled={busyAction?.startsWith('gate:')} className="inline-flex h-9 items-center rounded-md border border-outline-variant/60 px-3 font-label text-xs text-foreground/65 hover:border-primary/35 hover:text-primary disabled:opacity-45">取消</button>
          <button type="button" onClick={() => void handleGateResolve()} disabled={!gateConfirmed || busyAction?.startsWith('gate:')} className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 font-label text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-45">
            {busyAction?.startsWith('gate:') ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            确认完成并恢复到队列
          </button>
        </ModalFooter>
      </Modal>
    </div>
  );
}
