import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  BrainCircuit,
  ChevronDown,
  CheckCircle2,
  ClipboardCopy,
  FileCheck,
  FileUp,
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
  AcademicWritingLintResponse,
  CitationSourceResource,
  FigureAssetResource,
  JournalStyleSpecDraftResponse,
  ProjectExportReviewFinding,
  ProjectStats,
  WritingDraft,
  WritingMaterialResource,
  WritingSection,
} from '@/types/resources';

type CheckStatus = 'pass' | 'warn' | 'fail' | 'pending';
type ReviewSeverity = 'critical' | 'major' | 'minor' | 'format';
type FocusKey = 'novelty' | 'methods' | 'evidence' | 'reproducibility' | 'structure' | 'citations' | 'figures' | 'language';
type JournalStyleStatus = 'idle' | 'drafting' | 'confirming' | 'confirmed' | 'error';
type AcademicAuditStatus = 'idle' | 'running' | 'ready' | 'error';
type AcademicWritingLintIssue = NonNullable<AcademicWritingLintResponse['issues']>[number];

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

interface JournalStyleReviewState {
  activeProfileId: string;
  draftProfileId: string;
  hasDraft: boolean;
  confirmed: boolean;
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
const MAX_JOURNAL_SPEC_UPLOAD_BYTES = 256_000;

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

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- AbortError 守卫工具, 暂未在主流程中使用, 保留供 task cancel 路径恢复
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

function formatByteCount(bytes: number | null | undefined): string {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes <= 0) {
    return '0 KB';
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  return `${Math.ceil(bytes / 1024)} KB`;
}

function sanitizeDisplayFilename(filename: string | null | undefined): string {
  const trimmed = normalizeText(filename);
  if (!trimmed) {
    return '粘贴文本';
  }
  const normalized = trimmed.replace(/\\/g, '/');
  const leaf = normalized.split('/').filter(Boolean).pop();
  return normalizeText(leaf).slice(0, 120) || '规范文件';
}

function formatCitationStyle(style: JournalStyleSpecDraftResponse['profile']['citation_style']): string {
  return style === 'author_year' ? '作者-年份引用' : '数字编号引用';
}

function formatCaptionPosition(position: string): string {
  const normalized = normalizeText(position).toLowerCase();
  if (normalized === 'above') {
    return '题注在上';
  }
  if (normalized === 'below') {
    return '题注在下';
  }
  return normalizeText(position) || '未指定';
}

function isJournalStyleDraftConfirmed(
  draft: JournalStyleSpecDraftResponse,
  activeProfileId: string,
): boolean {
  const normalizedActiveId = normalizeText(activeProfileId);
  return draft.status === 'confirmed' || (
    Boolean(normalizedActiveId) && draft.profile.profile_id === normalizedActiveId
  );
}

function buildJournalStyleReviewState(
  draft: JournalStyleSpecDraftResponse | null,
  activeProfileId: string,
): JournalStyleReviewState {
  const normalizedActiveProfileId = normalizeText(activeProfileId);
  const draftProfileId = normalizeText(draft?.profile.profile_id);
  return {
    activeProfileId: normalizedActiveProfileId,
    draftProfileId,
    hasDraft: Boolean(draft),
    confirmed: draft ? isJournalStyleDraftConfirmed(draft, normalizedActiveProfileId) : Boolean(normalizedActiveProfileId),
  };
}

function academicLintStyleProfile(journalStyle: JournalStyleReviewState): string | null {
  if (!journalStyle.confirmed) {
    return null;
  }
  const profileId = normalizeText(journalStyle.activeProfileId || journalStyle.draftProfileId).replace(/-/g, '_');
  if (!/^[A-Za-z0-9_]{1,80}$/.test(profileId)) {
    return null;
  }
  return profileId;
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
  journalStyle: JournalStyleReviewState;
  selectedFocus: FocusKey[];
  dataset: ReviewDataset;
  manuscript: string;
}): string {
  const { journalRules, journalStyle, selectedFocus, dataset, manuscript } = params;
  const sectionTitles = dataset.sections
    .sort((left, right) => left.order - right.order)
    .map((section) => `${section.order + 1}. ${section.title}`)
    .join('\n');
  const citedCount = countCitations(dataset.citations);
  const focusText = REVIEW_FOCUS_OPTIONS
    .filter((option) => selectedFocus.includes(option.key))
    .map((option) => `- ${option.label}: ${option.description}`)
    .join('\n');
  const localFindings = buildReviewFindings(dataset, journalRules, journalStyle)
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

function formatJournalStyleProfileForPrompt(
  profile: JournalStyleSpecDraftResponse['profile'] | null | undefined,
  params: { status?: string; activeProfileId?: string } = {},
): string {
  const activeProfileId = normalizeText(params.activeProfileId);
  if (!profile) {
    return activeProfileId ? `已确认的期刊样式 profile：${activeProfileId}` : '';
  }

  const margins = profile.margins_cm;
  const confirmed = params.status === 'confirmed' || profile.profile_id === activeProfileId;
  return [
    `期刊样式 profile（${confirmed ? '已确认' : '待确认'}）：${profile.profile_id}`,
    `- 期刊：${profile.journal_name}`,
    `- 引用体例：${formatCitationStyle(profile.citation_style)}`,
    `- 正文字号：${profile.body_pt} pt；标题字号：${profile.title_pt} pt`,
    `- 字体：Latin ${profile.latin_font}；中文 ${profile.cjk_font}`,
    `- 页边距：上 ${margins.top} cm、下 ${margins.bottom} cm、左 ${margins.left} cm、右 ${margins.right} cm`,
    `- 图题位置：${formatCaptionPosition(profile.figure_caption_position)}；表题位置：${formatCaptionPosition(profile.table_caption_position)}`,
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
  const { activeProjectId, activeJournalStyleProfileId, setActiveJournalStyleProfileId } = useWriting();
  const normalizedProjectId = normalizeText(activeProjectId);
  const [journalRules, setJournalRules] = useState(DEFAULT_JOURNAL_RULES);
  const [journalName, setJournalName] = useState('');
  const [selectedSpecFile, setSelectedSpecFile] = useState<File | null>(null);
  const [styleDraft, setStyleDraft] = useState<JournalStyleSpecDraftResponse | null>(null);
  const [styleStatus, setStyleStatus] = useState<JournalStyleStatus>('idle');
  const [styleError, setStyleError] = useState<string | null>(null);
  const styleFileInputRef = React.useRef<HTMLInputElement | null>(null);
  const styleFileInputId = React.useId();
  const styleFileHelpId = `${styleFileInputId}-help`;
  const styleFileErrorId = `${styleFileInputId}-error`;
  const [styleAuditOpen, setStyleAuditOpen] = useState(false);
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
  const [academicAudit, setAcademicAudit] = useState<AcademicWritingLintResponse | null>(null);
  const [academicAuditStatus, setAcademicAuditStatus] = useState<AcademicAuditStatus>('idle');
  const [academicAuditError, setAcademicAuditError] = useState<string | null>(null);
  const mountedRef = React.useRef(true);
  const pollingGenerationRef = React.useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setStyleDraft(null);
    setStyleError(null);
    setStyleStatus('idle');
    setSelectedSpecFile(null);
    setStyleAuditOpen(false);
    setAcademicAudit(null);
    setAcademicAuditStatus('idle');
    setAcademicAuditError(null);
    if (styleFileInputRef.current) {
      styleFileInputRef.current.value = '';
    }
  }, [normalizedProjectId]);

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

  const journalStyleReview = useMemo(
    () => buildJournalStyleReviewState(styleDraft, activeJournalStyleProfileId),
    [activeJournalStyleProfileId, styleDraft],
  );
  const checks = useMemo(
    () => buildChecks(dataset, normalizedProjectId, journalRules, journalStyleReview),
    [dataset, journalRules, journalStyleReview, normalizedProjectId],
  );
  const findings = useMemo(
    () => buildReviewFindings(dataset, journalRules, journalStyleReview),
    [dataset, journalRules, journalStyleReview],
  );
  const passCount = checks.filter((check) => check.status === 'pass').length;
  const failCount = checks.filter((check) => check.status === 'fail').length;
  const score = checks.length > 0 ? Math.round((passCount / checks.length) * 100) : 0;
  const ringColor = failCount > 0 ? 'text-red-500' : score >= 70 ? 'text-emerald-500' : 'text-amber-500';
  const manuscriptChars = countDraftCharacters(dataset.drafts);
  const citationCount = countCitations(dataset.citations);
  const canDraftStyle = Boolean(normalizedProjectId && journalName.trim() && journalRules.trim().length >= 20);
  const canUploadStyle = Boolean(normalizedProjectId && journalName.trim() && selectedSpecFile);
  const academicAuditStyleProfile = useMemo(
    () => academicLintStyleProfile(journalStyleReview),
    [journalStyleReview],
  );
  const manuscriptForAudit = useMemo(
    () => compileManuscriptPreview(dataset.sections, dataset.drafts),
    [dataset.drafts, dataset.sections],
  );
  const canRunAcademicAudit = Boolean(normalizedProjectId && manuscriptForAudit.trim());

  const journalStylePromptContext = useMemo(() => formatJournalStyleProfileForPrompt(styleDraft?.profile, {
    status: styleDraft?.status,
    activeProfileId: activeJournalStyleProfileId,
  }), [activeJournalStyleProfileId, styleDraft?.profile, styleDraft?.status]);

  const promptPreview = useMemo(() => buildAiReviewPrompt({
    journalRules: [journalRules, journalStylePromptContext].filter(Boolean).join('\n\n'),
    journalStyle: journalStyleReview,
    selectedFocus,
    dataset,
    manuscript: compileManuscriptPreview(dataset.sections, dataset.drafts, 6000),
  }), [dataset, journalRules, journalStylePromptContext, journalStyleReview, selectedFocus]);

  useEffect(() => {
    setAcademicAudit(null);
    setAcademicAuditStatus('idle');
    setAcademicAuditError(null);
  }, [academicAuditStyleProfile, manuscriptForAudit]);

  const handleToggleFocus = useCallback((key: FocusKey) => {
    setSelectedFocus((current) => {
      if (current.includes(key)) {
        return current.filter((item) => item !== key);
      }
      return [...current, key];
    });
  }, []);

  const handleSpecFileChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0] ?? null;
    setStyleError(null);
    setStyleDraft(null);
    if (!file) {
      setSelectedSpecFile(null);
      setStyleStatus('idle');
      return;
    }
    const filename = file.name.toLowerCase();
    const supported = filename.endsWith('.txt') || filename.endsWith('.md') || filename.endsWith('.markdown');
    if (!supported) {
      setSelectedSpecFile(null);
      setStyleStatus('error');
      setStyleError('仅支持 UTF-8 文本或 Markdown 期刊规范文件。');
      event.currentTarget.value = '';
      return;
    }
    if (file.size > MAX_JOURNAL_SPEC_UPLOAD_BYTES) {
      setSelectedSpecFile(null);
      setStyleStatus('error');
      setStyleError('期刊规范文件需小于 256 KB。');
      event.currentTarget.value = '';
      return;
    }
    setSelectedSpecFile(file);
    setStyleStatus('idle');
  }, []);

  const handleRunAcademicAudit = useCallback(async () => {
    if (!canRunAcademicAudit || academicAuditStatus === 'running') {
      return;
    }
    setAcademicAuditStatus('running');
    setAcademicAuditError(null);
    try {
      const service = getWritingBackendService();
      const result = await service.lintAcademicWriting({
        text: manuscriptForAudit,
        content_type: 'manuscript',
        language: 'auto',
        required_sections: ['introduction', 'review'],
        require_evidence_refs: true,
        require_figure_table_formula_refs: dataset.figures.length > 0,
        style_profile: academicAuditStyleProfile,
        audit_context: {
          invocation_surface: 'direct_api',
          project_id: normalizedProjectId,
          source: 'frontend-reviewer',
          tool_chain: ['reviewer_submission', 'academic_writing_lint'],
          used_mcp_tools: [],
          reasoning_trace: ['Local deterministic reviewer audit before AI review.'],
        },
      });
      if (!mountedRef.current) {
        return;
      }
      setAcademicAudit(result);
      setAcademicAuditStatus('ready');
      setStatusMessage(`确定性写作审计完成：${Math.round(result.score)} 分。`);
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setAcademicAudit(null);
      setAcademicAuditStatus('error');
      setAcademicAuditError(formatWritingRuntimeError(err, '确定性写作审计失败。'));
    }
  }, [academicAuditStatus, academicAuditStyleProfile, canRunAcademicAudit, dataset.figures.length, manuscriptForAudit, normalizedProjectId]);

  const handleDraftJournalStyle = useCallback(async () => {
    if (!canDraftStyle || styleStatus === 'drafting' || styleStatus === 'confirming') {
      return;
    }
    setStyleStatus('drafting');
    setStyleError(null);
    try {
      const service = getWritingBackendService();
      const draft = await service.draftJournalStyleSpec({
        project_id: normalizedProjectId,
        journal_name: journalName.trim(),
        spec_text: journalRules.trim(),
      });
      if (!mountedRef.current) {
        return;
      }
      setStyleDraft(draft);
      setStyleAuditOpen(false);
      setStyleStatus('idle');
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setStyleDraft(null);
      setStyleStatus('error');
      setStyleError(formatWritingRuntimeError(err, '期刊规范草拟失败，请检查输入长度和格式。'));
    }
  }, [canDraftStyle, journalName, journalRules, normalizedProjectId, styleStatus]);

  const handleUploadJournalStyle = useCallback(async () => {
    if (!canUploadStyle || !selectedSpecFile || styleStatus === 'drafting' || styleStatus === 'confirming') {
      return;
    }
    setStyleStatus('drafting');
    setStyleError(null);
    try {
      const service = getWritingBackendService();
      const draft = await service.uploadJournalStyleSpec(
        normalizedProjectId,
        journalName.trim(),
        selectedSpecFile,
      );
      if (!mountedRef.current) {
        return;
      }
      setStyleDraft(draft);
      setStyleAuditOpen(false);
      setJournalRules((current) => (
        current.trim().length >= 20
          ? current
          : `已上传 ${draft.source.filename}，请以草拟结果为准。`
      ));
      setStyleStatus('idle');
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setStyleDraft(null);
      setStyleStatus('error');
      setStyleError(formatWritingRuntimeError(err, '期刊规范上传解析失败。'));
    }
  }, [canUploadStyle, journalName, normalizedProjectId, selectedSpecFile, styleStatus]);

  const handleConfirmJournalStyle = useCallback(async () => {
    if (!styleDraft || styleStatus === 'confirming') {
      return;
    }
    setStyleStatus('confirming');
    setStyleError(null);
    try {
      const service = getWritingBackendService();
      const confirmed = await service.confirmJournalStyleSpec({
        project_id: normalizedProjectId,
        draft_id: styleDraft.draft_id,
        confirmed_by: 'frontend-reviewer',
      });
      if (!mountedRef.current) {
        return;
      }
      setActiveJournalStyleProfileId(confirmed.profile.profile_id);
      setStyleDraft((current) => current
        ? { ...current, status: 'confirmed', profile: confirmed.profile }
        : current);
      setStyleAuditOpen(true);
      setStyleStatus('confirmed');
      setStatusMessage(`期刊规范已确认：${confirmed.profile.profile_id}`);
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setStyleStatus('error');
      setStyleError(formatWritingRuntimeError(err, '期刊规范确认失败。'));
    }
  }, [normalizedProjectId, setActiveJournalStyleProfileId, styleDraft, styleStatus]);

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
        journalRules: [journalRules, journalStylePromptContext].filter(Boolean).join('\n\n'),
        journalStyle: journalStyleReview,
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
  }, [dataset, journalRules, journalStylePromptContext, journalStyleReview, normalizedProjectId, running, selectedFocus]);

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
            <span>后台任务，可在任务中心查看。</span>
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

          <SectionCard
            title="目标期刊要求"
            icon={<FileCheck size={14} />}
            headerRight={
              activeJournalStyleProfileId
                ? <StatusPill tone="success">已确认规范</StatusPill>
                : <StatusPill tone="neutral">未确认规范</StatusPill>
            }
          >
            <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div className="space-y-3">
                <label className="block">
                  <span className="mb-1 block font-label text-xs font-medium text-foreground/65">期刊名称</span>
                  <input
                    type="text"
                    value={journalName}
                    onChange={(event) => setJournalName(event.target.value)}
                    placeholder="例如 Journal of Additive Manufacturing"
                    className="h-9 w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 text-sm text-foreground outline-none transition-colors placeholder:text-foreground/30 focus:border-primary/60"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block font-label text-xs font-medium text-foreground/65">作者指南 / 投稿规范</span>
                  <textarea
                    value={journalRules}
                    onChange={(event) => setJournalRules(event.target.value)}
                    rows={7}
                    placeholder="粘贴目标期刊要求"
                    className="min-h-[148px] w-full resize-y rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm leading-6 text-foreground outline-none transition-colors placeholder:text-foreground/30 focus:border-primary/60"
                  />
                </label>
              </div>
              <div className="flex flex-col gap-3">
                <div className="rounded-md border border-outline-variant/60 bg-surface-low px-3 py-3">
                  <input
                    id={styleFileInputId}
                    ref={styleFileInputRef}
                    type="file"
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    onChange={handleSpecFileChange}
                    aria-describedby={`${styleFileHelpId}${styleError ? ` ${styleFileErrorId}` : ''}`}
                    aria-invalid={Boolean(styleError)}
                    className="sr-only"
                  />
                  <label htmlFor={styleFileInputId} className="sr-only">官方规范文件</label>
                  <button
                    type="button"
                    onClick={() => styleFileInputRef.current?.click()}
                    disabled={!normalizedProjectId}
                    className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <FileUp size={14} />
                    选择规范文件
                  </button>
                  <p id={styleFileHelpId} className="mt-2 truncate text-[11px] text-foreground/45">
                    {selectedSpecFile ? `${sanitizeDisplayFilename(selectedSpecFile.name)} · ${formatByteCount(selectedSpecFile.size)}` : 'UTF-8 .txt / .md / .markdown · 最大 256 KB'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => void handleDraftJournalStyle()}
                    disabled={!canDraftStyle || styleStatus === 'drafting' || styleStatus === 'confirming'}
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {styleStatus === 'drafting' && !selectedSpecFile ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                    草拟
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleUploadJournalStyle()}
                    disabled={!canUploadStyle || styleStatus === 'drafting' || styleStatus === 'confirming'}
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {styleStatus === 'drafting' && selectedSpecFile ? <Loader2 size={13} className="animate-spin" /> : <FileUp size={13} />}
                    上传草拟
                  </button>
                </div>
                {styleError ? (
                  <div
                    id={styleFileErrorId}
                    role="alert"
                    className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                  >
                    {styleError}
                  </div>
                ) : null}
                {activeJournalStyleProfileId ? (
                  <div role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
                    当前 Word 导出规范：{activeJournalStyleProfileId}
                  </div>
                ) : null}
              </div>
            </div>
            {styleDraft ? (
              <JournalStyleAuditPanel
                activeProfileId={activeJournalStyleProfileId}
                detailsOpen={styleAuditOpen}
                draft={styleDraft}
                isConfirming={styleStatus === 'confirming'}
                onConfirm={() => void handleConfirmJournalStyle()}
                onToggleDetails={() => setStyleAuditOpen((open) => !open)}
              />
            ) : null}
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
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard
              title="确定性写作审计"
              icon={<ShieldCheck size={14} />}
              headerRight={
                <div className="flex items-center gap-2">
                  <StatusPill tone={
                    academicAuditStatus === 'ready'
                      ? (academicAudit?.passed ? 'success' : 'warning')
                      : academicAuditStatus === 'running'
                        ? 'info'
                        : academicAuditStatus === 'error'
                          ? 'danger'
                          : 'neutral'
                  }>
                    {academicAuditStatus === 'ready'
                      ? (academicAudit?.passed ? '已通过' : '需修订')
                      : academicAuditStatus === 'running'
                        ? '审计中'
                        : academicAuditStatus === 'error'
                          ? '失败'
                          : '未运行'}
                  </StatusPill>
                  <button
                    type="button"
                    onClick={() => void handleRunAcademicAudit()}
                    disabled={!canRunAcademicAudit || academicAuditStatus === 'running'}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {academicAuditStatus === 'running' ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
                    运行审计
                  </button>
                </div>
              }
            >
              {academicAuditError ? (
                <div role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                  {academicAuditError}
                </div>
              ) : null}
              <AcademicWritingAuditPanel
                audit={academicAudit}
                canRun={canRunAcademicAudit}
                status={academicAuditStatus}
                styleProfile={academicAuditStyleProfile}
              />
            </SectionCard>

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
                    当前审稿 AI：{reviewModel}
                  </p>
                </div>
              )}
            </SectionCard>
          </div>

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

interface AcademicWritingAuditPanelProps {
  audit: AcademicWritingLintResponse | null;
  canRun: boolean;
  status: AcademicAuditStatus;
  styleProfile: string | null;
}

function formatAuditSurface(surface: AcademicWritingLintResponse['audit']['invocation_surface']): string {
  if (surface === 'external_mcp') {
    return '外部 MCP';
  }
  if (surface === 'api_chat_local_tools') {
    return '本地工具聊天';
  }
  if (surface === 'direct_api') {
    return 'Direct API';
  }
  return '未知';
}

function formatAuditIssueSeverity(severity: AcademicWritingLintIssue['severity']): string {
  if (severity === 'error') {
    return '错误';
  }
  if (severity === 'warning') {
    return '警告';
  }
  return '提示';
}

function AcademicWritingAuditPanel({
  audit,
  canRun,
  status,
  styleProfile,
}: AcademicWritingAuditPanelProps) {
  if (!canRun) {
    return (
      <div className="rounded-md border border-dashed border-outline-variant/70 bg-surface-low px-4 py-4 text-center text-xs leading-5 text-foreground/55">
        当前项目还没有可审计的正文草稿。
      </div>
    );
  }

  if (!audit) {
    return (
      <div className="rounded-md border border-dashed border-outline-variant/70 bg-surface-low px-4 py-4 text-center text-xs leading-5 text-foreground/55">
        {status === 'running' ? '正在运行确定性写作审计。' : '运行审计后可查看 Direct API 质量门、引用证据、图表公式和期刊样式检查。'}
      </div>
    );
  }

  const auditTone: StatusTone = audit.passed ? 'success' : 'warning';
  const disclosureLabel = audit.audit.disclosure_required ? '需要披露' : '无需 MCP/Agent 披露';
  const checks = audit.audit.checks ?? [];
  const issues = audit.issues ?? [];
  const recommendations = audit.recommendations ?? [];

  return (
    <section aria-label="确定性写作审计结果" className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="审计分数" value={`${Math.round(audit.score)}`} />
        <Metric label="质量门" value={audit.audit.quality_gate === 'passed' ? 'passed' : 'failed'} />
        <Metric label="调用面" value={formatAuditSurface(audit.audit.invocation_surface)} />
        <Metric label="Style" value={styleProfile || '未绑定'} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="章节" value={`${audit.metrics.section_count}`} />
        <Metric label="证据锚点" value={`${audit.metrics.evidence_ref_count}`} />
        <Metric label="图/表/式" value={`${audit.metrics.figure_ref_count}/${audit.metrics.table_ref_count}/${audit.metrics.equation_ref_count}`} />
        <Metric label="引用" value={`${audit.metrics.citation_count}`} />
      </div>
      <div className="flex flex-wrap gap-2">
        <StatusPill tone={auditTone}>{audit.passed ? '审计通过' : '审计未通过'}</StatusPill>
        <StatusPill tone={audit.audit.agent_mediated ? 'warning' : 'success'}>
          {audit.audit.agent_mediated ? 'Agent mediated' : 'Direct API'}
        </StatusPill>
        <StatusPill tone={audit.audit.mcp_tool_calls_used ? 'warning' : 'success'}>
          {audit.audit.mcp_tool_calls_used ? 'MCP tools used' : 'No MCP tools'}
        </StatusPill>
        <StatusPill tone={audit.audit.disclosure_required ? 'warning' : 'success'}>
          {disclosureLabel}
        </StatusPill>
      </div>
      {checks.length > 0 ? (
        <div className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
          <div className="font-label text-[11px] font-semibold text-foreground/65">机器检查项</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {checks.map((check) => (
              <span key={check} className="rounded bg-surface-high px-2 py-1 font-mono text-[10px] text-foreground/60">
                {check}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {issues.length > 0 ? (
        <div className="grid gap-2 lg:grid-cols-2">
          {issues.slice(0, 4).map((issue) => (
            <article key={`${issue.code}-${issue.message}`} className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <h4 className="font-mono text-[11px] font-semibold text-foreground">{issue.code}</h4>
                <StatusPill tone={issue.severity === 'error' ? 'danger' : issue.severity === 'warning' ? 'warning' : 'info'}>
                  {formatAuditIssueSeverity(issue.severity)}
                </StatusPill>
              </div>
              <p className="mt-1 text-xs leading-5 text-foreground/65">{issue.message}</p>
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
          确定性审计未发现阻断项。
        </div>
      )}
      {recommendations.length > 0 ? (
        <div className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
          <div className="font-label text-[11px] font-semibold text-foreground/65">修订建议</div>
          <ul className="mt-1 space-y-1 text-xs leading-5 text-foreground/65">
            {recommendations.slice(0, 4).map((recommendation) => (
              <li key={recommendation}>{recommendation}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

interface JournalStyleAuditPanelProps {
  activeProfileId: string;
  detailsOpen: boolean;
  draft: JournalStyleSpecDraftResponse;
  isConfirming: boolean;
  onConfirm: () => void;
  onToggleDetails: () => void;
}

function JournalStyleAuditPanel({
  activeProfileId,
  detailsOpen,
  draft,
  isConfirming,
  onConfirm,
  onToggleDetails,
}: JournalStyleAuditPanelProps) {
  const detailsId = React.useId();
  const confirmed = isJournalStyleDraftConfirmed(draft, activeProfileId);
  const sourceName = sanitizeDisplayFilename(draft.source.filename);
  const sourceKind = draft.source.kind === 'upload' ? '上传文件' : '粘贴文本';
  const profile = draft.profile;
  const margins = profile.margins_cm;

  return (
    <section
      aria-label="期刊规范抽取审计"
      className="mt-3 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-label text-xs font-semibold text-foreground">
              {profile.journal_name}
            </h3>
            <StatusPill tone={confirmed ? 'success' : 'warning'}>
              {confirmed ? '已确认用于导出' : '待人工确认'}
            </StatusPill>
          </div>
          <dl className="mt-2 grid gap-2 text-[11px] text-foreground/60 sm:grid-cols-2 xl:grid-cols-4">
            <JournalStyleFact label="来源" value={`${sourceKind} · ${sourceName}`} />
            <JournalStyleFact label="文件大小" value={formatByteCount(draft.source.bytes)} />
            <JournalStyleFact label="Profile" value={profile.profile_id} />
            <JournalStyleFact label="引用体例" value={formatCitationStyle(profile.citation_style)} />
          </dl>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onToggleDetails}
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 font-label text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
          >
            <ChevronDown size={13} className={cn('transition-transform', detailsOpen ? 'rotate-180' : '')} />
            抽取详情
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isConfirming || confirmed}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-primary px-3 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isConfirming ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
            {confirmed ? '已确认' : '确认用于导出'}
          </button>
        </div>
      </div>

      <div id={detailsId} hidden={!detailsOpen} className="mt-3">
        <div className="grid gap-2 text-[11px] text-foreground/60 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="正文字号" value={`${profile.body_pt} pt`} />
          <Metric label="标题字号" value={`${profile.title_pt} pt`} />
          <Metric label="拉丁字体" value={profile.latin_font} />
          <Metric label="中文字体" value={profile.cjk_font} />
          <Metric label="上边距" value={`${margins.top} cm`} />
          <Metric label="下边距" value={`${margins.bottom} cm`} />
          <Metric label="左边距" value={`${margins.left} cm`} />
          <Metric label="右边距" value={`${margins.right} cm`} />
          <Metric label="图题位置" value={formatCaptionPosition(profile.figure_caption_position)} />
          <Metric label="表题位置" value={formatCaptionPosition(profile.table_caption_position)} />
        </div>
        {draft.warnings.length > 0 ? (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            <div className="font-label font-semibold">需人工复核</div>
            <ul className="mt-1 space-y-1">
              {draft.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function JournalStyleFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] text-foreground/45">{label}</dt>
      <dd className="mt-0.5 truncate font-medium text-foreground/75" title={value}>{value}</dd>
    </div>
  );
}

function buildChecks(
  dataset: ReviewDataset,
  activeProjectId: string,
  journalRules: string,
  journalStyle: JournalStyleReviewState,
): CheckItem[] {
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
    {
      id: 'journal-style-profile',
      label: '导出规范',
      description: journalStyle.confirmed
        ? `已确认 Word 导出规范 ${journalStyle.activeProfileId || journalStyle.draftProfileId}。`
        : journalStyle.hasDraft
          ? '已抽取期刊规范，但还未确认用于 Word 导出和最终审稿。'
          : '未确认期刊导出规范；Word 导出将使用默认样式。',
      status: journalStyle.confirmed ? 'pass' : (journalStyle.hasDraft ? 'warn' : 'pending'),
    },
  ];
}

function buildReviewFindings(
  dataset: ReviewDataset,
  journalRules: string,
  journalStyle: JournalStyleReviewState,
): ReviewFinding[] {
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
  if (journalStyle.hasDraft && !journalStyle.confirmed) {
    findings.push({
      id: 'unconfirmed-journal-style',
      severity: 'format',
      title: '期刊规范尚未确认',
      detail: '当前已有抽取出的期刊样式 profile，但还没有确认用于 Word 导出和最终审稿。',
      recommendation: '展开抽取详情，复核字体、字号、页边距、引用体例和图表题注位置后确认。',
      anchor: journalStyle.draftProfileId,
    });
  } else if (!journalStyle.confirmed && normalizeText(journalRules)) {
    findings.push({
      id: 'missing-journal-style-profile',
      severity: 'format',
      title: '未确认导出规范',
      detail: '已提供期刊规则文本，但 Word 导出仍未绑定确认后的期刊样式 profile。',
      recommendation: '使用“草拟”或“上传草拟”生成可复核 profile，并确认后再做最终导出。',
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
