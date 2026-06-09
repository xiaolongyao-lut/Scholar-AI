import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ClipboardCopy,
  FileCheck,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Square,
  XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { SectionCard } from '@/components/common/SectionCard';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import { useWriting } from '@/contexts/WritingContext';
import { formatWritingRuntimeError } from '@/components/writing/writingRuntimeDisplay';
import { getWritingBackendService } from '@/services/writingBackend';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import {
  artifactContentRecord,
  findLatestArtifact,
  startBackgroundJob,
  waitForRuntimeJobTerminalState,
} from '@/services/backgroundJobRunner';
import type {
  CitationSourceResource,
  FigureAssetResource,
  ProjectExportReviewFinding,
  ProjectStats,
  WritingDraft,
  WritingMaterialResource,
  WritingSection,
} from '@/types/resources';

type CheckStatus = 'pass' | 'warn' | 'fail' | 'pending';
type ReviewSeverity = 'critical' | 'major' | 'minor' | 'format';
type FocusKey = 'novelty' | 'methods' | 'evidence' | 'reproducibility' | 'structure' | 'citations' | 'figures' | 'language';

interface CheckItem {
  id: string;
  label: string;
  description: string;
  status: CheckStatus;
}

interface ReviewFinding {
  id: string;
  severity: ReviewSeverity;
  title: string;
  detail: string;
  recommendation: string;
  anchor?: string;
}

interface ReviewDataset {
  stats: ProjectStats | null;
  sections: WritingSection[];
  drafts: WritingDraft[];
  materials: WritingMaterialResource[];
  citations: CitationSourceResource[];
  figures: FigureAssetResource[];
  exportFindings: ProjectExportReviewFinding[];
}

interface FocusOption {
  key: FocusKey;
  label: string;
  description: string;
}

const EMPTY_DATASET: ReviewDataset = {
  stats: null,
  sections: [],
  drafts: [],
  materials: [],
  citations: [],
  figures: [],
  exportFindings: [],
};

const DEFAULT_JOURNAL_RULES = [
  '目标期刊要求（可选）：',
  '- 研究问题、创新性和贡献是否清楚。',
  '- 方法、实验设计、数据来源和统计/计算流程是否足以复现。',
  '- 结论是否由结果和引用证据支撑，避免过度推断。',
  '- 图表、引用、摘要、关键词和章节结构是否符合投稿习惯。',
].join('\n');

const REVIEW_FOCUS_OPTIONS: FocusOption[] = [
  { key: 'novelty', label: '创新性', description: '研究问题、贡献边界、和现有工作的差异' },
  { key: 'methods', label: '方法可靠性', description: '实验/建模流程、变量控制、统计或计算细节' },
  { key: 'evidence', label: '证据支撑', description: '论断、结果、引用和反例是否对应' },
  { key: 'reproducibility', label: '可复现性', description: '数据、代码、参数、样本和操作流程是否可追踪' },
  { key: 'structure', label: '结构逻辑', description: '摘要、引言、方法、结果、讨论是否衔接' },
  { key: 'citations', label: '引用完整性', description: '正文引用、参考文献元数据和引用覆盖' },
  { key: 'figures', label: '图表质量', description: '图表编号、标题、正文引用和可读性' },
  { key: 'language', label: '表达与格式', description: '学术表达、摘要可读性、术语一致性' },
];

const statusConfig: Record<CheckStatus, { icon: React.ElementType; tone: StatusTone; label: string }> = {
  pass: { icon: CheckCircle2, tone: 'success', label: '通过' },
  warn: { icon: AlertTriangle, tone: 'warning', label: '需关注' },
  fail: { icon: XCircle, tone: 'danger', label: '需修复' },
  pending: { icon: FileCheck, tone: 'info', label: '待审' },
};

const severityConfig: Record<ReviewSeverity, { label: string; tone: StatusTone; className: string }> = {
  critical: { label: '致命问题', tone: 'danger', className: 'border-red-200 bg-red-50 dark:border-red-700/40 dark:bg-red-500/15' },
  major: { label: '主要问题', tone: 'warning', className: 'border-amber-200 bg-amber-50 dark:border-amber-700/40 dark:bg-amber-500/15' },
  minor: { label: '次要问题', tone: 'info', className: 'border-sky-200 bg-sky-50 dark:border-sky-700/40 dark:bg-sky-500/15' },
  format: { label: '格式问题', tone: 'neutral', className: 'border-outline-variant/60 bg-surface-low' },
};

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  if (typeof error !== 'object' || error === null) return false;
  const record = error as { name?: unknown; code?: unknown };
  return record.name === 'AbortError' || record.name === 'CanceledError' || record.code === 'ERR_CANCELED';
}

async function readOrFallback<T>(loader: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await loader();
  } catch {
    return fallback;
  }
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

function countCitations(citations: CitationSourceResource[]): number {
  return citations.reduce((sum, item) => sum + Math.max(0, item.citation_count ?? 0), 0);
}

function countDraftCharacters(drafts: WritingDraft[]): number {
  return drafts.reduce((sum, item) => sum + normalizeText(item.content).length, 0);
}

function compileManuscriptPreview(sections: WritingSection[], drafts: WritingDraft[], maxChars = 22000): string {
  const bySectionId = new Map(sections.map((section) => [section.section_id, section]));
  const orderedDrafts = [...drafts].sort((left, right) => {
    const leftOrder = left.section_id ? bySectionId.get(left.section_id)?.order ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER;
    const rightOrder = right.section_id ? bySectionId.get(right.section_id)?.order ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || left.title.localeCompare(right.title);
  });
  const content = orderedDrafts
    .map((draft) => {
      const section = draft.section_id ? bySectionId.get(draft.section_id) : undefined;
      const title = normalizeText(section?.title) || normalizeText(draft.title) || '未命名章节';
      return `## ${title}\n\n${normalizeText(draft.content)}`;
    })
    .filter((part) => part.trim())
    .join('\n\n');
  return content.slice(0, maxChars);
}

function buildAiReviewPrompt(params: {
  journalRules: string;
  selectedFocus: FocusKey[];
  dataset: ReviewDataset;
  manuscript: string;
}): string {
  const { journalRules, selectedFocus, dataset, manuscript } = params;
  const sectionTitles = dataset.sections
    .sort((left, right) => left.order - right.order)
    .map((section) => `${section.order + 1}. ${section.title}`)
    .join('\n');
  const citedCount = countCitations(dataset.citations);
  const focusText = REVIEW_FOCUS_OPTIONS
    .filter((option) => selectedFocus.includes(option.key))
    .map((option) => `- ${option.label}: ${option.description}`)
    .join('\n');
  const localFindings = buildReviewFindings(dataset, journalRules)
    .map((finding) => `- [${severityConfig[finding.severity].label}] ${finding.title}: ${finding.detail}`)
    .join('\n');

  return [
    '你是一名严谨的 AI 学术审稿助手。请根据用户当前手稿、项目材料和可选目标期刊要求，输出中文结构化审稿报告。',
    '',
    '审稿规则：',
    '- 不要编造不存在的实验、数据、引用或期刊要求。',
    '- 每条问题必须说明严重程度、所在章节/证据锚点、为什么影响论文质量、建议怎么改。',
    '- 优先检查创新性、方法可靠性、证据支撑、可复现性、引用完整性、图表和结构逻辑。',
    '- 输出格式固定为：总体判断、必须修改、建议修改、格式与投稿规范、可直接执行的修改清单。',
    '',
    '目标期刊/用户自定义要求：',
    normalizeText(journalRules) || '用户未指定期刊要求，请按通用学术审稿标准审查。',
    '',
    '本次审查重点：',
    focusText || '- 通用学术质量审查',
    '',
    '项目概况：',
    `- 章节数：${dataset.sections.length}`,
    `- 草稿数：${dataset.drafts.length}`,
    `- 手稿字符数：${countDraftCharacters(dataset.drafts)}`,
    `- 关联文献：${dataset.materials.length}`,
    `- 正文引用次数：${citedCount}`,
    `- 图表资产：${dataset.figures.length}`,
    '',
    '章节目录：',
    sectionTitles || '暂无章节目录。',
    '',
    '本地基础检查发现：',
    localFindings || '暂无本地基础检查发现。',
    '',
    '手稿内容（可能已截断）：',
    manuscript || '当前项目还没有可审查的正文草稿。',
  ].join('\n');
}

/**
 * AI manuscript review workspace.
 *
 * The page keeps review local to the active writing project and never exposes
 * reviewer emails or submission-package actions, because this surface is for
 * manuscript diagnosis rather than external submission.
 */
export function ReviewerSubmission() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();
  const normalizedProjectId = normalizeText(activeProjectId);
  const [journalRules, setJournalRules] = useState(DEFAULT_JOURNAL_RULES);
  const [selectedFocus, setSelectedFocus] = useState<FocusKey[]>(REVIEW_FOCUS_OPTIONS.map((option) => option.key));
  const [dataset, setDataset] = useState<ReviewDataset>(EMPTY_DATASET);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [aiReport, setAiReport] = useState('');
  const [reviewModel, setReviewModel] = useState('当前聊天模型');
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const mountedRef = React.useRef(true);
  const pollingGenerationRef = React.useRef(0);

  useEffect(() => () => {
    mountedRef.current = false;
  }, []);

  const loadDataset = useCallback(async () => {
    if (!normalizedProjectId) {
      setDataset(EMPTY_DATASET);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const service = getWritingBackendService();
      const [
        stats,
        sections,
        drafts,
        materials,
        citations,
        figures,
        exportResult,
      ] = await Promise.all([
        readOrFallback(() => service.getProjectStats(normalizedProjectId), null),
        readOrFallback(() => service.listSections(normalizedProjectId), []),
        readOrFallback(() => service.listDrafts(normalizedProjectId), []),
        readOrFallback(() => service.listMaterials(normalizedProjectId), []),
        readOrFallback(() => service.listCitationSources(normalizedProjectId), []),
        readOrFallback(() => service.listFigureAssets(normalizedProjectId), []),
        readOrFallback(() => service.exportProject(normalizedProjectId, 'json'), null),
      ]);
      setDataset({
        stats,
        sections,
        drafts,
        materials,
        citations,
        figures,
        exportFindings: exportResult?.review_findings ?? [],
      });
    } catch (err) {
      setError(formatWritingRuntimeError(err, 'AI 审稿信息加载失败，请稍后重试。'));
      setDataset(EMPTY_DATASET);
    } finally {
      setLoading(false);
    }
  }, [normalizedProjectId]);

  useEffect(() => {
    void loadDataset();
  }, [loadDataset]);

  const checks = useMemo(() => buildChecks(dataset, normalizedProjectId, journalRules), [dataset, journalRules, normalizedProjectId]);
  const findings = useMemo(() => buildReviewFindings(dataset, journalRules), [dataset, journalRules]);
  const passCount = checks.filter((check) => check.status === 'pass').length;
  const failCount = checks.filter((check) => check.status === 'fail').length;
  const score = checks.length > 0 ? Math.round((passCount / checks.length) * 100) : 0;
  const ringColor = failCount > 0 ? 'text-red-500' : score >= 70 ? 'text-emerald-500' : 'text-amber-500';
  const manuscriptChars = countDraftCharacters(dataset.drafts);
  const citationCount = countCitations(dataset.citations);

  const promptPreview = useMemo(() => buildAiReviewPrompt({
    journalRules,
    selectedFocus,
    dataset,
    manuscript: compileManuscriptPreview(dataset.sections, dataset.drafts, 6000),
  }), [dataset, journalRules, selectedFocus]);

  const handleToggleFocus = useCallback((key: FocusKey) => {
    setSelectedFocus((current) => {
      if (current.includes(key)) {
        return current.filter((item) => item !== key);
      }
      return [...current, key];
    });
  }, []);

  const handleRunAiReview = useCallback(async () => {
    if (!normalizedProjectId || running) {
      return;
    }
    setRunning(true);
    setError(null);
    setStatusMessage(null);
    setAiReport('');
    setActiveJobId(null);
    try {
      const service = getWritingBackendService();
      const exportResult = await readOrFallback(
        () => service.exportProject(normalizedProjectId, 'markdown'),
        null,
      );
      const manuscript = normalizeText(exportResult?.content) || compileManuscriptPreview(dataset.sections, dataset.drafts);
      const query = buildAiReviewPrompt({
        journalRules,
        selectedFocus,
        dataset: {
          ...dataset,
          exportFindings: exportResult?.review_findings ?? dataset.exportFindings,
        },
        manuscript,
      });
      const { job, session } = await startBackgroundJob({
        sessionTitle: 'AI 审稿',
        sessionMetadata: {
          surface: 'writing_reviewer',
          project_id: normalizedProjectId,
        },
        request: {
          kind: 'ai_review',
          input_text: query,
          metadata: {
            project_id: normalizedProjectId,
            prompt: query,
            tier: 'thorough',
            journal_rules: journalRules,
            selected_focus: selectedFocus,
          },
          tags: ['writing', 'ai-review'],
        },
        onJobCreated: (job) => {
          if (mountedRef.current) {
            setActiveJobId(job.job_id);
          }
        },
      });
      if (!mountedRef.current) {
        return;
      }
      setActiveJobId(job.job_id);
      setActiveSessionId(session.session_id);
      setStatusMessage('AI 审稿已进入后台任务；切换界面不会中断，可在任务中心查看进度。');
      const generation = pollingGenerationRef.current + 1;
      pollingGenerationRef.current = generation;
      const status = await waitForRuntimeJobTerminalState(job.job_id, {
        pollIntervalMs: 1800,
        timeoutMs: 30 * 60 * 1000,
      });
      if (!mountedRef.current) {
        return;
      }
      if (pollingGenerationRef.current !== generation) {
        return;
      }
      if (status.status !== 'completed') {
        throw new Error(status.error || 'AI 审稿任务未完成。');
      }
      const artifacts = await getWritingRuntimeClient().getJobArtifacts(job.job_id);
      const artifact = findLatestArtifact(artifacts, 'transformed_text');
      const content = artifactContentRecord(artifact);
      const response = typeof content.response === 'string'
        ? content.response
        : typeof content.text === 'string'
          ? content.text
          : '';
      const model = typeof content.review_model === 'string' && content.review_model.trim()
        ? content.review_model.trim()
        : '当前聊天模型';
      if (!mountedRef.current) {
        return;
      }
      setAiReport(response || 'AI 审稿任务已完成，但没有返回可显示的报告。');
      setReviewModel(model);
      setStatusMessage('AI 审稿已完成。');
      setError(null);
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setStatusMessage(null);
      setError(formatWritingRuntimeError(err, 'AI 审稿后台任务已提交或执行失败。请到任务中心确认任务状态，并检查模型配置是否可用。'));
    } finally {
      if (mountedRef.current) {
        setRunning(false);
      }
    }
  }, [dataset, journalRules, normalizedProjectId, running, selectedFocus]);

  const handleStopReview = useCallback(async () => {
    const normalizedJobId = activeJobId?.trim();
    if (!normalizedJobId) {
      setRunning(false);
      setStatusMessage('已停止等待。已创建的后台任务可在任务中心查看。');
      pollingGenerationRef.current += 1;
      return;
    }
    try {
      await getWritingRuntimeClient().cancelJob(normalizedJobId);
      pollingGenerationRef.current += 1;
      setStatusMessage('已取消 AI 审稿任务。');
    } catch (err) {
      setError(formatWritingRuntimeError(err, '取消 AI 审稿任务失败，请到任务中心查看任务状态。'));
    } finally {
      setRunning(false);
      setActiveJobId(null);
      setActiveSessionId(null);
    }
  }, [activeJobId]);

  const handleCopyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(promptPreview);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch (err) {
      setError(formatWritingRuntimeError(err, '复制审稿提示词失败。'));
    }
  }, [promptPreview]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<ShieldCheck size={18} />}
          title={t('writing.reviewer.title')}
          subtitle={t('writing.reviewer.subtitle')}
          className="mb-0"
          actions={
            <>
              <span className="inline-flex items-center rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs text-foreground/65">
                审稿模型：{reviewModel}
              </span>
              <button
                type="button"
                onClick={() => navigate('/jobs')}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
              >
                <Loader2 size={13} />
                任务中心
              </button>
              <button
                type="button"
                onClick={() => (running ? handleStopReview() : void handleRunAiReview())}
                disabled={!normalizedProjectId}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {running ? <Square size={13} /> : <Sparkles size={13} />}
                {running ? '停止审稿' : '开始 AI 审稿'}
              </button>
              <button
                type="button"
                onClick={() => void loadDataset()}
                disabled={!normalizedProjectId || loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                刷新
              </button>
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
        {error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {error}
          </div>
        ) : null}
        {statusMessage ? (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
            {statusMessage}
          </div>
        ) : null}

        <div className="rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-xs leading-6 text-foreground/65">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-primary/10 px-2 py-0.5 text-[11px] text-primary">探查</span>
            <span>开始后会创建后台任务；切换页面不会中断。任务中心可查看进度，本页保持打开时会自动回填报告。</span>
          </div>
          {activeJobId ? (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-foreground/55">
              <span>当前任务：{activeJobId}</span>
              {activeSessionId ? <span>会话：{activeSessionId}</span> : null}
              <button
                type="button"
                onClick={() => navigate('/jobs')}
                className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 px-2 py-1 text-[11px] text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
              >
                去任务中心
              </button>
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
          <SectionCard className="flex flex-col" bodyClassName="flex flex-1 flex-col items-center justify-center gap-3 py-5 text-center">
            <div className="relative h-24 w-24">
              <svg viewBox="0 0 100 100" className="-rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" className="text-surface-high" strokeWidth="8" />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  fill="none"
                  stroke="currentColor"
                  className={ringColor}
                  strokeWidth="8"
                  strokeDasharray={`${score * 2.64} 264`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="font-headline text-2xl font-bold text-foreground">{score}</span>
              </div>
            </div>
            <div>
              <p className="font-label text-xs text-foreground/55">{t('writing.reviewer.readiness')}</p>
              <p className="mt-1 font-label text-[11px] text-foreground/45">
                {normalizedProjectId ? `基础检查通过 ${passCount} / ${checks.length}` : '未激活项目'}
              </p>
            </div>
            <div className="grid w-full grid-cols-3 gap-2 pt-1 text-center">
              <Metric label="正文" value={`${manuscriptChars}`} />
              <Metric label="引用" value={`${citationCount}`} />
              <Metric label="图表" value={`${dataset.figures.length}`} />
            </div>
          </SectionCard>

          <SectionCard title="目标期刊要求" icon={<FileCheck size={14} />}>
            <textarea
              value={journalRules}
              onChange={(event) => setJournalRules(event.target.value)}
              rows={7}
              placeholder="粘贴目标期刊作者指南、字数、结构、图表、引用、开放数据等要求。留空则按通用学术审稿标准。"
              className="min-h-[148px] w-full resize-y rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm leading-6 text-foreground outline-none transition-colors placeholder:text-foreground/30 focus:border-primary/60"
            />
            <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {REVIEW_FOCUS_OPTIONS.map((option) => {
                const selected = selectedFocus.includes(option.key);
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => handleToggleFocus(option.key)}
                    aria-pressed={selected}
                    className={cn(
                      'min-h-[64px] rounded-md border px-3 py-2 text-left transition-colors',
                      selected
                        ? 'border-primary/45 bg-primary/10 text-foreground'
                        : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/30 hover:text-foreground',
                    )}
                  >
                    <span className="block font-label text-xs font-semibold">{option.label}</span>
                    <span className="mt-1 block text-[11px] leading-4 text-foreground/50">{option.description}</span>
                  </button>
                );
              })}
            </div>
          </SectionCard>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <SectionCard
            title="AI 审稿报告"
            icon={<BrainCircuit size={14} />}
            headerRight={running ? <StatusPill tone="info">审稿中</StatusPill> : aiReport ? <StatusPill tone="success">已生成</StatusPill> : <StatusPill tone="neutral">未开始</StatusPill>}
          >
            {aiReport ? (
              <div className="whitespace-pre-wrap rounded-md border border-outline-variant/60 bg-surface-low px-4 py-3 font-body text-sm leading-7 text-foreground/85">
                {aiReport}
              </div>
            ) : (
            <div className="flex min-h-[220px] flex-col items-center justify-center rounded-md border border-dashed border-outline-variant/70 bg-surface-low px-6 text-center">
                <BrainCircuit className="h-8 w-8 text-foreground/25" aria-hidden />
                <p className="mt-3 text-sm font-medium text-foreground/70">点击“开始 AI 审稿”生成结构化报告</p>
                <p className="mt-1 max-w-xl text-xs leading-5 text-foreground/45">
                  报告会围绕当前手稿、项目文献和上方期刊要求输出：总体判断、主要问题、次要问题、格式问题和可执行修改清单。当前审稿 AI：{reviewModel}
                </p>
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="基础检查"
            icon={<FileCheck size={14} />}
            headerRight={<StatusPill tone="neutral">{passCount}/{checks.length}</StatusPill>}
          >
            <ul className="divide-y divide-outline-variant/30">
              {checks.map((check) => {
                const cfg = statusConfig[check.status];
                return (
                  <li key={check.id} className="flex items-start gap-3 py-2">
                    <div className={cn(
                      'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
                      cfg.tone === 'success' ? 'bg-emerald-50 dark:bg-emerald-950/30' :
                      cfg.tone === 'warning' ? 'bg-amber-50 dark:bg-amber-950/30' :
                      cfg.tone === 'danger' ? 'bg-red-50 dark:bg-red-950/30' :
                      'bg-sky-50 dark:bg-sky-950/30',
                    )}>
                      <cfg.icon size={14} className={cn(
                        cfg.tone === 'success' ? 'text-emerald-600' :
                        cfg.tone === 'warning' ? 'text-amber-600' :
                        cfg.tone === 'danger' ? 'text-red-600' :
                        'text-sky-600',
                      )} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <h4 className="font-label text-sm font-medium text-foreground">{check.label}</h4>
                        <StatusPill tone={cfg.tone}>{cfg.label}</StatusPill>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-foreground/50">{check.description}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </SectionCard>
        </div>

        <SectionCard
          title="待处理问题"
          icon={<AlertTriangle size={14} />}
          headerRight={
            <button
              type="button"
              onClick={() => void handleCopyPrompt()}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-1.5 text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
            >
              <ClipboardCopy size={13} />
              {copied ? '已复制' : '复制审稿提示词'}
            </button>
          }
        >
          {findings.length === 0 ? (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
              基础检查未发现阻断项。仍建议运行 AI 审稿，对创新性、方法和证据链做深度审查。
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {findings.map((finding) => {
                const cfg = severityConfig[finding.severity];
                return (
                  <article key={finding.id} className={cn('rounded-md border px-3 py-3', cfg.className)}>
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="text-sm font-semibold text-foreground">{finding.title}</h4>
                      <StatusPill tone={cfg.tone}>{cfg.label}</StatusPill>
                    </div>
                    {finding.anchor ? (
                      <p className="mt-1 text-[11px] text-foreground/45">{finding.anchor}</p>
                    ) : null}
                    <p className="mt-2 text-xs leading-5 text-foreground/65">{finding.detail}</p>
                    <p className="mt-2 text-xs leading-5 text-foreground/80">
                      <span className="font-medium">建议：</span>{finding.recommendation}
                    </p>
                  </article>
                );
              })}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-outline-variant/50 bg-surface-low px-2 py-2">
      <div className="truncate text-[10px] text-foreground/45">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}

function buildChecks(dataset: ReviewDataset, activeProjectId: string, journalRules: string): CheckItem[] {
  if (!activeProjectId) {
    return [
      { id: 'project', label: '项目上下文', description: '需要先激活一个手稿项目。', status: 'fail' },
      { id: 'drafts', label: '正文草稿', description: '激活项目后检查正文是否可审。', status: 'pending' },
      { id: 'rules', label: '审稿标准', description: '可以粘贴目标期刊要求，也可以使用通用学术审稿标准。', status: 'pending' },
    ];
  }
  const draftCharacters = countDraftCharacters(dataset.drafts);
  const citationCount = countCitations(dataset.citations);
  return [
    {
      id: 'sections',
      label: '章节结构',
      description: `当前 ${dataset.sections.length} 个章节。`,
      status: dataset.sections.length > 0 ? 'pass' : 'fail',
    },
    {
      id: 'drafts',
      label: '正文草稿',
      description: `当前 ${dataset.drafts.length} 个草稿，${draftCharacters} 字符。`,
      status: dataset.drafts.length > 0 ? (draftCharacters >= 3000 ? 'pass' : 'warn') : 'fail',
    },
    {
      id: 'materials',
      label: '项目文献',
      description: `已关联 ${dataset.materials.length} 条来源材料。`,
      status: dataset.materials.length > 0 ? 'pass' : 'warn',
    },
    {
      id: 'citations',
      label: '正文引用',
      description: `引用来源 ${dataset.citations.length} 条，正文引用 ${citationCount} 次。`,
      status: citationCount > 0 ? 'pass' : 'warn',
    },
    {
      id: 'figures',
      label: '图表资产',
      description: `已整理 ${dataset.figures.length} 个图表资产。`,
      status: dataset.figures.length > 0 ? 'pass' : 'pending',
    },
    {
      id: 'journal-rules',
      label: '期刊要求',
      description: normalizeText(journalRules) ? '已提供可编辑审稿标准。' : '未提供期刊规则，将按通用学术审稿标准处理。',
      status: normalizeText(journalRules) ? 'pass' : 'warn',
    },
  ];
}

function buildReviewFindings(dataset: ReviewDataset, journalRules: string): ReviewFinding[] {
  const findings: ReviewFinding[] = [];
  const draftCharacters = countDraftCharacters(dataset.drafts);
  const citationCount = countCitations(dataset.citations);

  if (dataset.sections.length === 0) {
    findings.push({
      id: 'missing-sections',
      severity: 'critical',
      title: '缺少章节结构',
      detail: 'AI 审稿无法判断摘要、引言、方法、结果、讨论等结构是否完整。',
      recommendation: '先在大纲管理中建立章节，再运行审稿。',
    });
  }
  if (dataset.drafts.length === 0) {
    findings.push({
      id: 'missing-drafts',
      severity: 'critical',
      title: '缺少正文草稿',
      detail: '当前项目没有可审查正文，AI 只能审项目元数据，无法判断论证质量。',
      recommendation: '先在手稿工作室写入或导入正文草稿。',
    });
  } else if (draftCharacters < 3000) {
    findings.push({
      id: 'short-draft',
      severity: 'major',
      title: '正文内容偏短',
      detail: `当前正文约 ${draftCharacters} 字符，可能不足以覆盖完整论文结构。`,
      recommendation: '补齐关键章节后再做最终审稿；现在可用于早期结构诊断。',
    });
  }
  if (dataset.materials.length === 0) {
    findings.push({
      id: 'missing-materials',
      severity: 'major',
      title: '缺少关联文献',
      detail: '没有项目文献时，AI 很难检查文献覆盖、相关工作和证据链。',
      recommendation: '先在知识库导入核心文献，并关联到当前写作项目。',
    });
  }
  if (citationCount === 0) {
    findings.push({
      id: 'missing-citations',
      severity: 'major',
      title: '正文缺少引用锚点',
      detail: '当前引用来源没有在正文形成可追踪引用，结论和证据之间缺少闭环。',
      recommendation: '在来源与引用中补充元数据，并在手稿工作室插入引用锚点。',
    });
  }
  if (dataset.figures.length === 0) {
    findings.push({
      id: 'missing-figures',
      severity: 'minor',
      title: '未整理图表资产',
      detail: '许多期刊要求图表编号、标题、正文引用和独立图片文件。',
      recommendation: '如果论文包含图表，请在图表管理中确认图片资产、图题和编号。',
    });
  }
  if (!normalizeText(journalRules)) {
    findings.push({
      id: 'missing-journal-rules',
      severity: 'format',
      title: '未提供目标期刊规则',
      detail: 'AI 会按通用标准审查，但无法检查具体字数、结构、图表、引用格式和数据开放要求。',
      recommendation: '粘贴目标期刊作者指南，或保留通用标准做早期质量审查。',
    });
  }
  for (const exportFinding of dataset.exportFindings) {
    findings.push({
      id: `export-${exportFinding.id}`,
      severity: exportFinding.severity === 'error' ? 'major' : 'format',
      title: '导出审计发现',
      detail: exportFinding.message,
      recommendation: '根据导出审计定位到对应章节、草稿或材料后修复。',
      anchor: [exportFinding.section_id, exportFinding.draft_id, exportFinding.material_id].filter(Boolean).join(' · '),
    });
  }
  return findings;
}
