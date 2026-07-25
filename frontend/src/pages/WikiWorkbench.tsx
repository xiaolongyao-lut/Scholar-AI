import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, BookMarked, CheckCircle2, ChevronDown, Download, FilePlus2, FileText, RefreshCw, Search, Settings2, ShieldCheck, Square } from 'lucide-react';

import { WikiCompileDryRunPanel } from '@/components/wiki/WikiCompileDryRunPanel';
import { WikiImportMarkdownPanel } from '@/components/wiki/WikiImportMarkdownPanel';
import { DoctorReportPanel } from '@/components/wiki/DoctorReportPanel';
import { GraphDebugPanel } from '@/components/wiki/GraphDebugPanel';
import { WikiGraphSegmentedView } from '@/components/graph/WikiGraphSegmentedView';
import { evidenceGraphToGraphPayload } from '@/components/knowledge/evidenceGraphAdapter';
import { getWikiEvidenceGraph, type EvidenceGraphPayload } from '@/services/graphApi';
import { WikiPagePreviewPanel } from '@/components/wiki/WikiPagePreviewPanel';
import { ReviewQueuePanel } from '@/components/wiki/ReviewQueuePanel';
import { WikiPageListPanel } from '@/components/wiki/WikiPageListPanel';
import { WikiStatusCard } from '@/components/wiki/WikiStatusCard';
import { PageHeader } from '@/components/common/PageHeader';
import { formatWikiError, formatWikiPageLabel, sanitizeWikiVisibleText } from '@/components/wiki/wikiDisplay';
import { buildSettingsSectionPath } from '@/pages/settingsSections';
import {
  getWikiDoctor,
  getWikiGraph,
  getWikiPageDetail,
  getWikiPages,
  getWikiReview,
  approveWikiReviewItem,
  rejectWikiReviewItem,
  withdrawWikiReviewPromotion,
  getWikiStatus,
  preflightWikiRevalidation,
  applyWikiRevalidation,
  createWikiManualPage,
  runWikiCompileDryRun,
  searchWiki,
  exportWikiMarkdown,
  WikiApiError,
} from '@/services/wikiApi';
import type {
  WikiCompileDryRunInputModel,
  WikiCompileDryRunModel,
  WikiManualPageInputModel,
  WikiManualPageKind,
  WikiManualPageStatus,
  WikiPageMutationModel,
  WikiDoctorModel,
  WikiGraphModel,
  WikiPageDetailModel,
  WikiPageListModel,
  WikiReviewDecisionInputModel,
  WikiReviewPromotionWithdrawalInputModel,
  WikiReviewItemModel,
  WikiReviewListModel,
  WikiSearchModel,
  WikiExportModel,
  WikiStatusModel,
  WikiRevalidationModel,
} from '@/types/wiki';
import { cn } from '@/lib/utils';

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === 'AbortError') return true;
  if (typeof err !== 'object' || err === null) return false;
  const record = err as { name?: unknown; code?: unknown };
  return record.name === 'AbortError' || record.name === 'CanceledError' || record.code === 'ERR_CANCELED';
}

export function formatPanelError(err: unknown, label: string): string {
  if (err instanceof WikiApiError) {
    const message = err.status >= 500
      ? `${label}暂不可用（${err.status}）。请确认后端服务已启动并已启用对应功能。`
      : err.message;
    return formatWikiError(message, `读取${label}失败。`);
  }
  if (err instanceof Error) {
    const message = err.message === 'Failed to fetch'
      ? `${label}接口不可达。请确认前端当前能访问后端 API。`
      : err.message;
    return formatWikiError(message, `读取${label}失败。`);
  }
  return `读取${label}失败。`;
}

interface WikiWorkbenchProps {
  embedded?: boolean;
}

type WikiReviewAction = 'approve' | 'reject';

interface WikiReviewRetryEntry {
  fingerprint: string;
  requestId: string;
}

function createWikiReviewRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `wiki-review-${crypto.randomUUID()}`;
  }
  return `wiki-review-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function wikiReviewRequestFingerprint(
  item: WikiReviewItemModel,
  action: WikiReviewAction,
  reason: string,
): string {
  const targetIdentity = item.target?.type === 'wiki_page_revision'
    ? item.target.page_id
    : item.target?.type === 'annotation_note'
      ? `${item.target.project_id}:${item.target.material_id}:${item.target.note_id}`
      : '';
  return JSON.stringify({
    action,
    item_id: item.item_id,
    item_revision: item.item_revision,
    target_type: item.target?.type ?? 'unbound',
    target_identity: targetIdentity,
    target_content_hash: item.target?.expected_content_hash ?? '',
    reason: reason.trim(),
    decided_by: 'user',
  });
}

export function WikiWorkbench({ embedded = false }: WikiWorkbenchProps = {}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState<WikiStatusModel | null>(null);
  const [isStatusLoading, setIsStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [revalidation, setRevalidation] = useState<WikiRevalidationModel | null>(null);
  const [isRevalidationLoading, setIsRevalidationLoading] = useState(false);
  const [revalidationError, setRevalidationError] = useState<string | null>(null);
  const [pageList, setPageList] = useState<WikiPageListModel | null>(null);
  const [isPagesLoading, setIsPagesLoading] = useState(true);
  const [pagesError, setPagesError] = useState<string | null>(null);
  const [selectedPagePath, setSelectedPagePath] = useState<string | null>(null);
  const [pageDetail, setPageDetail] = useState<WikiPageDetailModel | null>(null);
  const [isPageDetailLoading, setIsPageDetailLoading] = useState(false);
  const [pageDetailError, setPageDetailError] = useState<string | null>(null);
  const [doctor, setDoctor] = useState<WikiDoctorModel | null>(null);
  const [isDoctorLoading, setIsDoctorLoading] = useState(true);
  const [doctorError, setDoctorError] = useState<string | null>(null);
  const [review, setReview] = useState<WikiReviewListModel | null>(null);
  const [isReviewLoading, setIsReviewLoading] = useState(true);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [graph, setGraph] = useState<WikiGraphModel | null>(null);
  const [isGraphLoading, setIsGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphPayload, setGraphPayload] = useState<EvidenceGraphPayload | null>(null);
  const [isGraphPayloadLoading, setIsGraphPayloadLoading] = useState(true);
  const [graphPayloadError, setGraphPayloadError] = useState<string | null>(null);
  const [compileResult, setCompileResult] = useState<WikiCompileDryRunModel | null>(null);
  const [isCompileLoading, setIsCompileLoading] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [manualCreateResult, setManualCreateResult] = useState<WikiPageMutationModel | null>(null);
  const [isManualCreateLoading, setIsManualCreateLoading] = useState(false);
  const [manualCreateError, setManualCreateError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResult, setSearchResult] = useState<WikiSearchModel | null>(null);
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<WikiExportModel | null>(null);
  const [isExportLoading, setIsExportLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const compileAbortRef = useRef<AbortController | null>(null);
  const manualCreateAbortRef = useRef<AbortController | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);
  const exportAbortRef = useRef<AbortController | null>(null);
  const reviewRetryRef = useRef<Map<string, WikiReviewRetryEntry>>(new Map());

  const targetPagePath = useMemo(() => {
    const page = searchParams.get('page')?.trim();
    return page && page.length > 0 ? page : null;
  }, [searchParams]);
  const graphViewerPayload = useMemo(
    () => graphPayload ? evidenceGraphToGraphPayload(graphPayload) : null,
    [graphPayload],
  );

  const loadStatus = useCallback(async () => {
    setIsStatusLoading(true);
    setStatusError(null);
    try {
      setStatus(await getWikiStatus());
    } catch (err: unknown) {
      setStatusError(formatPanelError(err, '知识库状态'));
    } finally {
      setIsStatusLoading(false);
    }
  }, []);

  const loadPages = useCallback(async () => {
    setIsPagesLoading(true);
    setPagesError(null);
    try {
      setPageList(await getWikiPages());
    } catch (err: unknown) {
      setPagesError(formatPanelError(err, '知识页列表'));
    } finally {
      setIsPagesLoading(false);
    }
  }, []);

  const handlePreflightRevalidation = useCallback(async (): Promise<void> => {
    setIsRevalidationLoading(true);
    setRevalidationError(null);
    try {
      setRevalidation(await preflightWikiRevalidation());
    } catch (err: unknown) {
      setRevalidationError(formatPanelError(err, '重新验证预检'));
    } finally {
      setIsRevalidationLoading(false);
    }
  }, []);

  const handleApplyRevalidation = useCallback(async (expectedHash: string): Promise<void> => {
    setIsRevalidationLoading(true);
    setRevalidationError(null);
    try {
      const result = await applyWikiRevalidation(expectedHash);
      setRevalidation(result);
      await loadStatus();
    } catch (err: unknown) {
      setRevalidationError(formatPanelError(err, '重新验证'));
    } finally {
      setIsRevalidationLoading(false);
    }
  }, [loadStatus]);

  const loadDoctor = useCallback(async () => {
    setIsDoctorLoading(true);
    setDoctorError(null);
    try {
      setDoctor(await getWikiDoctor());
    } catch (err: unknown) {
      setDoctorError(formatPanelError(err, '知识库诊断'));
    } finally {
      setIsDoctorLoading(false);
    }
  }, []);

  const loadReview = useCallback(async (): Promise<boolean> => {
    setIsReviewLoading(true);
    setReviewError(null);
    try {
      setReview(await getWikiReview());
      return true;
    } catch (err: unknown) {
      setReviewError(formatPanelError(err, '复审队列'));
      return false;
    } finally {
      setIsReviewLoading(false);
    }
  }, []);

  const loadGraph = useCallback(async () => {
    setIsGraphLoading(true);
    setGraphError(null);
    try {
      setGraph(await getWikiGraph());
    } catch (err: unknown) {
      setGraphError(formatPanelError(err, '知识图谱'));
    } finally {
      setIsGraphLoading(false);
    }
  }, []);

  const loadGraphPayload = useCallback(async () => {
    setIsGraphPayloadLoading(true);
    setGraphPayloadError(null);
    try {
      setGraphPayload(await getWikiEvidenceGraph());
    } catch (err: unknown) {
      setGraphPayloadError(formatPanelError(err, '知识图谱视图'));
    } finally {
      setIsGraphPayloadLoading(false);
    }
  }, []);

  const loadPageDetail = useCallback(async (pagePath: string) => {
    setSelectedPagePath(pagePath);
    setIsPageDetailLoading(true);
    setPageDetailError(null);
    try {
      setPageDetail(await getWikiPageDetail(pagePath));
    } catch (err: unknown) {
      setPageDetail(null);
      setPageDetailError(formatPanelError(err, '知识页预览'));
    } finally {
      setIsPageDetailLoading(false);
    }
  }, []);

  const handleSelectPagePath = useCallback((pagePath: string) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.set('page', pagePath);
    setSearchParams(nextSearchParams);
    if (pagePath === targetPagePath) {
      void loadPageDetail(pagePath);
    }
  }, [loadPageDetail, searchParams, setSearchParams, targetPagePath]);

  const refreshSelectedPage = useCallback(() => {
    if (!selectedPagePath) {
      return;
    }
    void loadPageDetail(selectedPagePath);
  }, [loadPageDetail, selectedPagePath]);

  const handleGraphReviewApplied = useCallback(async () => {
    await Promise.all([
      loadPages(),
      loadGraph(),
      loadGraphPayload(),
      selectedPagePath ? loadPageDetail(selectedPagePath) : Promise.resolve(),
    ]);
  }, [loadGraph, loadGraphPayload, loadPageDetail, loadPages, selectedPagePath]);

  const refreshAfterReviewDecision = useCallback(async () => {
    await Promise.all([
      loadStatus(),
      loadPages(),
      loadReview(),
      loadGraph(),
      loadGraphPayload(),
      selectedPagePath ? loadPageDetail(selectedPagePath) : Promise.resolve(),
    ]);
  }, [loadGraph, loadGraphPayload, loadPageDetail, loadPages, loadReview, loadStatus, selectedPagePath]);

  const buildReviewDecisionInput = useCallback((
    item: WikiReviewItemModel,
    action: WikiReviewAction,
    reason: string,
  ): WikiReviewDecisionInputModel => {
    if (action === 'approve' && item.promotion_intent) {
      const intent = item.promotion_intent;
      return {
        target_type: 'wiki_page_revision',
        item_id: item.item_id,
        reason: intent.reason,
        decided_by: 'user',
        request_id: intent.request_id,
        expected_item_revision: intent.expected_item_revision,
        expected_target_content_hash: intent.target.expected_content_hash,
      };
    }
    const cacheKey = `${action}:${item.item_id}`;
    const fingerprint = wikiReviewRequestFingerprint(item, action, reason);
    const cached = reviewRetryRef.current.get(cacheKey);
    const requestId = cached?.fingerprint === fingerprint
      ? cached.requestId
      : createWikiReviewRequestId();
    reviewRetryRef.current.set(cacheKey, { fingerprint, requestId });
    const baseInput = {
      item_id: item.item_id,
      reason,
      decided_by: 'user',
      request_id: requestId,
      expected_item_revision: item.item_revision,
    };
    if (item.target?.type === 'wiki_page_revision') {
      return {
        ...baseInput,
        target_type: 'wiki_page_revision',
        expected_target_content_hash: item.target.expected_content_hash,
      };
    }
    if (item.target?.type === 'annotation_note') {
      return {
        ...baseInput,
        target_type: 'annotation_note',
        expected_target_content_hash: item.target.expected_content_hash,
      };
    }
    return {
      ...baseInput,
      target_type: 'unbound',
    };
  }, []);

  const refreshReviewAfterConflict = useCallback(async (
    error: unknown,
    item: WikiReviewItemModel,
    action: WikiReviewAction | 'withdraw',
  ): Promise<never> => {
    if (!(error instanceof WikiApiError) || error.status !== 409) {
      throw error;
    }
    if (action !== 'withdraw') {
      reviewRetryRef.current.delete(`${action}:${item.item_id}`);
    }
    const refreshed = await loadReview();
    if (!refreshed) {
      throw new WikiApiError('审核项已发生变化，但读取最新版本失败；请手动刷新后重试。', 409);
    }
    throw new WikiApiError('审核项已发生变化，已刷新为最新版本；请核对后重试。', 409);
  }, [loadReview]);

  const handleApproveReview = useCallback(async (item: WikiReviewItemModel, reason: string): Promise<void> => {
    try {
      await approveWikiReviewItem(buildReviewDecisionInput(item, 'approve', reason));
    } catch (error: unknown) {
      await refreshReviewAfterConflict(error, item, 'approve');
    }
    await refreshAfterReviewDecision();
  }, [buildReviewDecisionInput, refreshAfterReviewDecision, refreshReviewAfterConflict]);

  const handleRejectReview = useCallback(async (item: WikiReviewItemModel, reason: string): Promise<void> => {
    try {
      await rejectWikiReviewItem(buildReviewDecisionInput(item, 'reject', reason));
    } catch (error: unknown) {
      await refreshReviewAfterConflict(error, item, 'reject');
    }
    await refreshAfterReviewDecision();
  }, [buildReviewDecisionInput, refreshAfterReviewDecision, refreshReviewAfterConflict]);

  const handleWithdrawReview = useCallback(async (
    item: WikiReviewItemModel,
    reason: string,
  ): Promise<void> => {
    const intent = item.promotion_intent;
    if (!intent) {
      throw new WikiApiError('当前没有可撤回的晋升操作，请刷新后重试。', 409);
    }
    const input: WikiReviewPromotionWithdrawalInputModel = {
      item_id: item.item_id,
      reason,
      expected_item_revision: item.item_revision,
      expected_promotion_operation_id: intent.operation_id,
    };
    try {
      await withdrawWikiReviewPromotion(input);
    } catch (error: unknown) {
      await refreshReviewAfterConflict(error, item, 'withdraw');
    }
    await refreshAfterReviewDecision();
  }, [refreshAfterReviewDecision, refreshReviewAfterConflict]);

  const handleRunCompileDryRun = useCallback(async (input: WikiCompileDryRunInputModel) => {
    const abortController = new AbortController();
    compileAbortRef.current = abortController;
    setIsCompileLoading(true);
    setCompileError(null);
    try {
      const result = await runWikiCompileDryRun(input, 15000, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        return;
      }
      setCompileResult(result);
    } catch (err: unknown) {
      if (isAbortError(err) || abortController.signal.aborted) {
        return;
      }
      setCompileError(formatPanelError(err, '知识写入'));
    } finally {
      if (compileAbortRef.current === abortController) {
        compileAbortRef.current = null;
        setIsCompileLoading(false);
      }
    }
  }, []);

  const handleStopCompileDryRun = useCallback(() => {
    const controller = compileAbortRef.current;
    if (!controller) return;
    controller.abort();
    compileAbortRef.current = null;
    setIsCompileLoading(false);
    setCompileError('已停止生成编译计划。');
  }, []);

  const handleCreateManualPage = useCallback(async (input: WikiManualPageInputModel) => {
    const abortController = new AbortController();
    manualCreateAbortRef.current = abortController;
    setIsManualCreateLoading(true);
    setManualCreateError(null);
    setManualCreateResult(null);
    try {
      const result = await createWikiManualPage(input, 15000, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        return;
      }
      setManualCreateResult(result);
      void loadPages();
      void loadReview();
      void loadGraph();
      void loadGraphPayload();
    } catch (err: unknown) {
      if (isAbortError(err) || abortController.signal.aborted) {
        return;
      }
      setManualCreateError(formatPanelError(err, '手动录入'));
    } finally {
      if (manualCreateAbortRef.current === abortController) {
        manualCreateAbortRef.current = null;
        setIsManualCreateLoading(false);
      }
    }
  }, [loadGraph, loadGraphPayload, loadPages, loadReview]);

  const handleStopManualCreate = useCallback(() => {
    const controller = manualCreateAbortRef.current;
    if (!controller) return;
    controller.abort();
    manualCreateAbortRef.current = null;
    setIsManualCreateLoading(false);
    setManualCreateError('已停止手动录入。');
  }, []);

  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchResult(null);
      setSearchError(null);
      return;
    }
    const abortController = new AbortController();
    searchAbortRef.current = abortController;
    setIsSearchLoading(true);
    setSearchError(null);
    try {
      const result = await searchWiki(query, 15000, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        return;
      }
      setSearchResult(result);
    } catch (err: unknown) {
      if (isAbortError(err) || abortController.signal.aborted) {
        return;
      }
      setSearchResult(null);
      setSearchError(formatPanelError(err, '知识检索'));
    } finally {
      if (searchAbortRef.current === abortController) {
        searchAbortRef.current = null;
        setIsSearchLoading(false);
      }
    }
  }, [searchQuery]);

  const handleStopSearch = useCallback(() => {
    const controller = searchAbortRef.current;
    if (!controller) return;
    controller.abort();
    searchAbortRef.current = null;
    setIsSearchLoading(false);
    setSearchError('已停止搜索。');
  }, []);

  const handleExport = useCallback(async () => {
    const abortController = new AbortController();
    exportAbortRef.current = abortController;
    setIsExportLoading(true);
    setExportError(null);
    try {
      const result = await exportWikiMarkdown(30000, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        return;
      }
      setExportResult(result);
    } catch (err: unknown) {
      if (isAbortError(err) || abortController.signal.aborted) {
        return;
      }
      setExportResult(null);
      setExportError(formatPanelError(err, '页面导出'));
    } finally {
      if (exportAbortRef.current === abortController) {
        exportAbortRef.current = null;
        setIsExportLoading(false);
      }
    }
  }, []);

  const handleStopExport = useCallback(() => {
    const controller = exportAbortRef.current;
    if (!controller) return;
    controller.abort();
    exportAbortRef.current = null;
    setIsExportLoading(false);
    setExportError('已停止导出。');
  }, []);

  useEffect(() => {
    void loadStatus();
    void loadPages();
    void loadDoctor();
    void loadReview();
    void loadGraph();
    void loadGraphPayload();
  }, [loadDoctor, loadGraph, loadGraphPayload, loadPages, loadReview, loadStatus]);

  useEffect(() => {
    return () => {
      compileAbortRef.current?.abort();
      manualCreateAbortRef.current?.abort();
      searchAbortRef.current?.abort();
      exportAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (targetPagePath && targetPagePath !== selectedPagePath) {
      void loadPageDetail(targetPagePath);
    }
  }, [loadPageDetail, selectedPagePath, targetPagePath]);

  useEffect(() => {
    if (!pageList?.pages.length) {
      if (!targetPagePath) {
        setSelectedPagePath(null);
        setPageDetail(null);
        setPageDetailError(null);
      }
      return;
    }

    if (selectedPagePath && !targetPagePath && !pageList.pages.some((page) => page.path === selectedPagePath)) {
      setSelectedPagePath(null);
      setPageDetail(null);
      setPageDetailError(null);
    }
  }, [pageList, selectedPagePath, targetPagePath]);

  const headline = useMemo(() => {
    if (!status) {
      return '正在加载知识库状态…';
    }
    if (!status.enabled) {
      return '知识库当前未启用';
    }
    if (status.stale) {
      return '知识库已启用，索引需要重新生成';
    }
    return '知识库已启用，索引为最新';
  }, [status]);
  const isProbeLoading = isStatusLoading || isPagesLoading || isDoctorLoading || isReviewLoading || isGraphLoading || isGraphPayloadLoading;
  const handleProbeWiki = useCallback(() => {
    void loadStatus();
    void loadPages();
    void loadDoctor();
    void loadReview();
    void loadGraph();
    void loadGraphPayload();
  }, [loadDoctor, loadGraph, loadGraphPayload, loadPages, loadReview, loadStatus]);

  return (
    <div className={embedded ? 'flex min-h-0 flex-col gap-4' : 'flex h-full min-h-0 flex-col gap-4 overflow-auto bg-background px-6 py-5'}>
      {!embedded ? (
        <PageHeader
          icon={<BookMarked size={18} />}
          title={headline}
          subtitle="检索、复审、页面与图谱。"
          className="mb-0"
        />
      ) : null}

      {embedded ? (
        <EmbeddedWikiSimpleView
          status={status}
          pageList={pageList}
          review={review}
          isPagesLoading={isPagesLoading}
          pagesError={pagesError}
          isReviewLoading={isReviewLoading}
          reviewError={reviewError}
          selectedPagePath={selectedPagePath}
          pageDetail={pageDetail}
          isPageDetailLoading={isPageDetailLoading}
          pageDetailError={pageDetailError}
          searchQuery={searchQuery}
          searchResult={searchResult}
          isSearchLoading={isSearchLoading}
          searchError={searchError}
          isManualLoading={isManualCreateLoading}
          manualError={manualCreateError}
          manualResult={manualCreateResult}
          onQueryChange={setSearchQuery}
          onSearch={() => void handleSearch()}
          onStopSearch={handleStopSearch}
          onRefreshReview={() => void loadReview()}
          onApproveReview={handleApproveReview}
          onRejectReview={handleRejectReview}
          onWithdrawReview={handleWithdrawReview}
          onRefreshPages={() => void loadPages()}
          onSelectPagePath={handleSelectPagePath}
          onRefreshSelectedPage={refreshSelectedPage}
          onCreateManual={(input) => void handleCreateManualPage(input)}
          onStopManual={handleStopManualCreate}
          onOpenSettings={() => navigate(buildSettingsSectionPath('experimental'))}
        >
          {/* 高级 / 诊断：保留全部既有富面板，默认折叠 */}
          <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-xs leading-6 text-foreground/65">
            <div className="flex flex-wrap items-center gap-2 font-medium text-foreground/80">
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[11px] text-primary">状态</span>
              <button
                type="button"
                onClick={() => navigate(buildSettingsSectionPath('experimental'))}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-[11px] text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
              >
                前往功能开关
              </button>
              <button
                type="button"
                onClick={handleProbeWiki}
                disabled={isProbeLoading}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary/35 bg-primary/10 px-2.5 py-1.5 text-[11px] text-primary transition-colors hover:bg-primary/15 disabled:cursor-wait disabled:opacity-60"
              >
                <RefreshCw size={12} className={isProbeLoading ? 'animate-spin' : ''} />
                探查
              </button>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <span>启用：{status?.enabled ? '已开启' : '未开启'}</span>
              <span>页面：{pageList?.pages.length ?? status?.page_count ?? 0} 个</span>
              <span>复审：{review?.items.length ?? 0} 条</span>
              <span>图谱：{graphPayload ? `${graphPayload.nodes.length} 节点 / ${graphPayload.edges.length} 边` : '未生成'}</span>
            </div>
          </section>

          <WikiKnowledgeLayerCard
            status={status}
            pageList={pageList}
            doctor={doctor}
            review={review}
            graph={graph}
            isExporting={isExportLoading}
            exportResult={exportResult}
            exportError={exportError}
            onRefreshAll={handleProbeWiki}
            onExport={() => void handleExport()}
            onStopExport={handleStopExport}
            onOpenSettings={() => navigate(buildSettingsSectionPath('experimental'))}
          />

          <WikiCompileDryRunPanel
            result={compileResult}
            isLoading={isCompileLoading}
            error={compileError}
            isWikiEnabled={status?.enabled ?? false}
            isWikiStale={status?.stale ?? false}
            manualResult={manualCreateResult}
            manualError={manualCreateError}
            isManualLoading={isManualCreateLoading}
            onRun={(input) => void handleRunCompileDryRun(input)}
            onStop={handleStopCompileDryRun}
            onCreateManual={(input) => void handleCreateManualPage(input)}
            onStopManual={handleStopManualCreate}
          />

          <WikiImportMarkdownPanel
            isWikiEnabled={status?.enabled ?? false}
            reviewQueueCount={review?.items.length ?? 0}
            onImported={() => {
              void loadStatus();
              void loadPages();
              void loadReview();
              void loadGraph();
              void loadGraphPayload();
            }}
          />

          <section className="overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
            <div className="flex items-center justify-between border-b border-outline-variant/60 px-4 py-2">
              <div className="flex items-center gap-2">
                <span className="font-headline text-sm font-semibold text-foreground">知识图谱</span>
                <span className="text-[10px] text-foreground/45">
                  {graphPayload ? `${graphPayload.nodes.length} 节点 · ${graphPayload.edges.length} 边` : '尚未加载'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => void loadGraphPayload()}
                className="rounded-md border border-outline-variant/60 bg-surface-low px-2 py-0.5 text-[11px] text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
              >
                刷新
              </button>
            </div>
            <div className="h-[420px]">
              <WikiGraphSegmentedView
                payload={graphViewerPayload}
                domain="wiki"
                loading={isGraphPayloadLoading}
                error={graphPayloadError}
                variant="explorer"
                onReviewApplied={handleGraphReviewApplied}
              />
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-3">
            <WikiStatusCard
              status={status}
              isLoading={isStatusLoading}
              error={statusError}
              onRefresh={() => void loadStatus()}
              revalidation={revalidation}
              isRevalidationLoading={isRevalidationLoading}
              revalidationError={revalidationError}
              onPreflightRevalidation={() => void handlePreflightRevalidation()}
              onApplyRevalidation={(expectedHash) => void handleApplyRevalidation(expectedHash)}
            />
            <DoctorReportPanel
              doctor={doctor}
              isLoading={isDoctorLoading}
              error={doctorError}
              onRefresh={() => void loadDoctor()}
            />
            <GraphDebugPanel
              graph={graph}
              isLoading={isGraphLoading}
              error={graphError}
              onRefresh={() => void loadGraph()}
            />
          </section>
        </EmbeddedWikiSimpleView>
      ) : (
        <>
      <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-xs leading-6 text-foreground/65">
        <div className="flex flex-wrap items-center gap-2 font-medium text-foreground/80">
          <span className="rounded bg-primary/10 px-2 py-0.5 text-[11px] text-primary">状态</span>
          <button
            type="button"
            onClick={() => navigate(buildSettingsSectionPath('experimental'))}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-[11px] text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
          >
            前往功能开关
          </button>
          <button
            type="button"
            onClick={handleProbeWiki}
            disabled={isProbeLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-primary/35 bg-primary/10 px-2.5 py-1.5 text-[11px] text-primary transition-colors hover:bg-primary/15 disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw size={12} className={isProbeLoading ? 'animate-spin' : ''} />
            探查
          </button>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <span>启用：{status?.enabled ? '已开启' : '未开启'}</span>
          <span>页面：{pageList?.pages.length ?? status?.page_count ?? 0} 个</span>
          <span>复审：{review?.items.length ?? 0} 条</span>
          <span>图谱：{graphPayload ? `${graphPayload.nodes.length} 节点 / ${graphPayload.edges.length} 边` : '未生成'}</span>
        </div>
      </section>

      <WikiKnowledgeLayerCard
        status={status}
        pageList={pageList}
        doctor={doctor}
        review={review}
        graph={graph}
        isExporting={isExportLoading}
        exportResult={exportResult}
        exportError={exportError}
        onRefreshAll={handleProbeWiki}
        onExport={() => void handleExport()}
        onStopExport={handleStopExport}
        onOpenSettings={() => navigate(buildSettingsSectionPath('experimental'))}
      />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <ReviewQueuePanel
          items={review?.items ?? null}
          isLoading={isReviewLoading}
          error={reviewError}
          onRefresh={() => void loadReview()}
          onApprove={handleApproveReview}
          onReject={handleRejectReview}
          onWithdraw={handleWithdrawReview}
        />
        <WikiImportMarkdownPanel
          isWikiEnabled={status?.enabled ?? false}
          reviewQueueCount={review?.items.length ?? 0}
          onImported={() => {
            void loadStatus();
            void loadPages();
            void loadReview();
            void loadGraph();
            void loadGraphPayload();
          }}
        />
        <WikiCompileDryRunPanel
          result={compileResult}
          isLoading={isCompileLoading}
          error={compileError}
          isWikiEnabled={status?.enabled ?? false}
          isWikiStale={status?.stale ?? false}
          manualResult={manualCreateResult}
          manualError={manualCreateError}
          isManualLoading={isManualCreateLoading}
          onRun={(input) => void handleRunCompileDryRun(input)}
          onStop={handleStopCompileDryRun}
          onCreateManual={(input) => void handleCreateManualPage(input)}
          onStopManual={handleStopManualCreate}
        />
      </section>

      <section className="overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
        <div className="flex items-center justify-between border-b border-outline-variant/60 px-4 py-2">
          <div className="flex items-center gap-2">
            <span className="font-headline text-sm font-semibold text-foreground">知识图谱</span>
            <span className="text-[10px] text-foreground/45">
              {graphPayload ? `${graphPayload.nodes.length} 节点 · ${graphPayload.edges.length} 边` : '尚未加载'}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void loadGraphPayload()}
            className="rounded-md border border-outline-variant/60 bg-surface-low px-2 py-0.5 text-[11px] text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            刷新
          </button>
        </div>
        <div className="h-[420px]">
          <WikiGraphSegmentedView
            payload={graphViewerPayload}
            domain="wiki"
            loading={isGraphPayloadLoading}
            error={graphPayloadError}
            variant="explorer"
            onReviewApplied={handleGraphReviewApplied}
          />
        </div>
      </section>

      <WikiSearchPanel
        query={searchQuery}
        result={searchResult}
        isLoading={isSearchLoading}
        error={searchError}
        onQueryChange={setSearchQuery}
        onSearch={() => void handleSearch()}
        onStopSearch={handleStopSearch}
        onSelectPage={handleSelectPagePath}
      />

      <section className="grid gap-4 xl:grid-cols-2">
        <WikiPageListPanel
          pages={pageList?.pages ?? null}
          isLoading={isPagesLoading}
          error={pagesError}
          onRefresh={() => void loadPages()}
          selectedPath={selectedPagePath}
          onSelectPath={handleSelectPagePath}
        />
        <WikiPagePreviewPanel
          selectedPath={selectedPagePath}
          page={pageDetail}
          isLoading={isPageDetailLoading}
          error={pageDetailError}
          onRefresh={refreshSelectedPage}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <WikiStatusCard
          status={status}
          isLoading={isStatusLoading}
          error={statusError}
          onRefresh={() => void loadStatus()}
          revalidation={revalidation}
          isRevalidationLoading={isRevalidationLoading}
          revalidationError={revalidationError}
          onPreflightRevalidation={() => void handlePreflightRevalidation()}
          onApplyRevalidation={(expectedHash) => void handleApplyRevalidation(expectedHash)}
        />
        <DoctorReportPanel
          doctor={doctor}
          isLoading={isDoctorLoading}
          error={doctorError}
          onRefresh={() => void loadDoctor()}
        />
        <GraphDebugPanel
          graph={graph}
          isLoading={isGraphLoading}
          error={graphError}
          onRefresh={() => void loadGraph()}
        />
      </section>
        </>
      )}
    </div>
  );
}

function WikiKnowledgeLayerCard({
  status,
  pageList,
  doctor,
  review,
  graph,
  isExporting,
  exportResult,
  exportError,
  onRefreshAll,
  onExport,
  onStopExport,
  onOpenSettings,
}: {
  status: WikiStatusModel | null;
  pageList: WikiPageListModel | null;
  doctor: WikiDoctorModel | null;
  review: WikiReviewListModel | null;
  graph: WikiGraphModel | null;
  isExporting: boolean;
  exportResult: WikiExportModel | null;
  exportError: string | null;
  onRefreshAll: () => void;
  onExport: () => void;
  onStopExport: () => void;
  onOpenSettings: () => void;
}) {
  const pageCount = Number(pageList?.pages.length ?? status?.page_count ?? 0);
  const reviewCount = Number(review?.items.length ?? 0);
  const graphCount = Number(graph?.structuredGraph?.node_count ?? 0);
  const doctorState = doctor?.structuredReport?.status ?? 'warning';
  const doctorText = doctorState === 'ok' ? '诊断正常' : doctorState === 'error' ? '需要处理' : '需要复核';
  const enabledText = status?.enabled ? '已启用' : '未启用';
  const indexText = status?.stale ? '索引待刷新' : '索引可用';

  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <ShieldCheck size={18} />
          </div>
          <div className="min-w-0">
            <h2 className="font-headline text-base font-semibold text-foreground">知识库状态</h2>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!status?.enabled ? (
            <button
              type="button"
              onClick={onOpenSettings}
              className="inline-flex items-center gap-1.5 rounded-md border border-primary/25 bg-primary/8 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <Settings2 size={13} />
              查看功能开关
            </button>
          ) : null}
          <button
            type="button"
            onClick={onRefreshAll}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw size={13} />
            刷新
          </button>
          <button
            type="button"
            onClick={isExporting ? onStopExport : onExport}
            disabled={!status?.enabled}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isExporting ? <Square size={13} /> : <Download size={13} />}
            {isExporting ? '停止' : '导出页面文件'}
          </button>
        </div>
      </div>

      {exportError ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          {exportError}
        </div>
      ) : null}
      {exportResult ? (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
          <div>已导出 {exportResult.page_count} 页，文件已保存到本机工作区。</div>
        </div>
      ) : null}

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <FlowStatus label="运行状态" value={enabledText} detail={indexText} active={Boolean(status?.enabled && !status?.stale)} />
        <FlowStatus label="页面库" value={`${pageCount} 页`} detail="已编译页面" active={pageCount > 0} />
        <FlowStatus label="待审页面" value={`${reviewCount} 项`} detail={doctorText} active={doctorState === 'ok'} />
        <FlowStatus label="图谱" value={`${graphCount} 节点`} detail="页面关系" active={graphCount > 0} />
      </div>

      {!status?.enabled ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <div>
              <p>知识库未启用。</p>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function WikiSearchPanel({
  query,
  result,
  isLoading,
  error,
  onQueryChange,
  onSearch,
  onStopSearch,
  onSelectPage,
}: {
  query: string;
  result: WikiSearchModel | null;
  isLoading: boolean;
  error: string | null;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  onStopSearch: () => void;
  onSelectPage: (pagePath: string) => void;
}) {
  const refs = result?.evidence_refs ?? [];
  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 flex-1">
          <label className="font-label text-[11px] font-medium text-foreground/65" htmlFor="wiki-search-query">
            知识检索
          </label>
          <div className="mt-1 flex min-w-0 gap-2">
            <input
              id="wiki-search-query"
              type="search"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  onSearch();
                }
              }}
              placeholder="搜索已编译页面"
              className="min-w-0 flex-1 rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
            />
            <button
              type="button"
              onClick={isLoading ? onStopSearch : onSearch}
              disabled={!isLoading && query.trim().length === 0}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isLoading ? <Square size={13} /> : <Search size={13} />}
              {isLoading ? '停止' : '搜索'}
            </button>
          </div>
        </div>
        <div className="text-[11px] text-foreground/45">
          {result ? `${refs.length} 条结果` : '等待查询'}
        </div>
      </div>

      {error ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {result?.warnings.length ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          {result.warnings.join(' ')}
        </div>
      ) : null}

      {refs.length > 0 ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {refs.map((ref, index) => {
            const pagePath = typeof ref.page_path === 'string' ? ref.page_path : '';
            return (
              <button
                key={`${pagePath}-${index}`}
                type="button"
                onClick={() => {
                  if (pagePath) {
                    onSelectPage(pagePath);
                  }
                }}
                disabled={!pagePath}
                className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-surface-high disabled:cursor-default disabled:opacity-70"
              >
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <FileText size={14} className="shrink-0 text-primary/70" />
                  <span className="truncate">{sanitizeWikiVisibleText(ref.title, formatWikiPageLabel(pagePath))}</span>
                </div>
                <div className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/55">
                  {ref.snippet || pagePath}
                </div>
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function FlowStatus({ label, value, detail, active }: { label: string; value: string; detail: string; active: boolean }) {
  return (
    <div className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-foreground/45">{label}</span>
        <CheckCircle2 size={13} className={active ? 'text-emerald-500' : 'text-foreground/25'} />
      </div>
      <div className="mt-1 truncate text-sm font-medium text-foreground">{value}</div>
      <div className="mt-0.5 truncate text-[11px] text-foreground/45">{detail}</div>
    </div>
  );
}

interface EmbeddedWikiSimpleViewProps {
  status: WikiStatusModel | null;
  pageList: WikiPageListModel | null;
  review: WikiReviewListModel | null;
  isPagesLoading: boolean;
  pagesError: string | null;
  isReviewLoading: boolean;
  reviewError: string | null;
  selectedPagePath: string | null;
  pageDetail: WikiPageDetailModel | null;
  isPageDetailLoading: boolean;
  pageDetailError: string | null;
  searchQuery: string;
  searchResult: WikiSearchModel | null;
  isSearchLoading: boolean;
  searchError: string | null;
  isManualLoading: boolean;
  manualError: string | null;
  manualResult: WikiPageMutationModel | null;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  onStopSearch: () => void;
  onRefreshReview: () => void;
  onApproveReview: (item: WikiReviewItemModel, reason: string) => Promise<void>;
  onRejectReview: (item: WikiReviewItemModel, reason: string) => Promise<void>;
  onWithdrawReview: (item: WikiReviewItemModel, reason: string) => Promise<void>;
  onRefreshPages: () => void;
  onSelectPagePath: (pagePath: string) => void;
  onRefreshSelectedPage: () => void;
  onCreateManual: (input: WikiManualPageInputModel) => void;
  onStopManual: () => void;
  onOpenSettings: () => void;
  children: React.ReactNode;
}

/**
 * Embedded 模式只暴露记忆流核心动作：搜索 / 复审 / 记一下 / 看页面预览。
 * 其它工程能力（状态触发说明、知识层卡、图谱大卡、Doctor、状态、图调试、编译预案）
 * 收进高级折叠，避免日常使用界面太重。
 *
 * 输入：embedded 父组件中所有现有状态 + 操作回调（不新增数据请求）。
 * 输出：渲染节点；children 是高级折叠的内容。
 */
function EmbeddedWikiSimpleView({
  status,
  pageList,
  review,
  isPagesLoading,
  pagesError,
  isReviewLoading,
  reviewError,
  selectedPagePath,
  pageDetail,
  isPageDetailLoading,
  pageDetailError,
  searchQuery,
  searchResult,
  isSearchLoading,
  searchError,
  isManualLoading,
  manualError,
  manualResult,
  onQueryChange,
  onSearch,
  onStopSearch,
  onRefreshReview,
  onApproveReview,
  onRejectReview,
  onWithdrawReview,
  onRefreshPages,
  onSelectPagePath,
  onRefreshSelectedPage,
  onCreateManual,
  onStopManual,
  onOpenSettings,
  children,
}: EmbeddedWikiSimpleViewProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialCapture = searchParams.get('action') === 'capture';
  const [captureOpen, setCaptureOpen] = useState(initialCapture);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // 当外部链接带 ?action=capture 时自动展开「记一下」，并把参数清掉避免每次刷新都展开。
  useEffect(() => {
    if (searchParams.get('action') === 'capture') {
      setCaptureOpen(true);
      const next = new URLSearchParams(searchParams);
      next.delete('action');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const wikiEnabled = status?.enabled ?? false;
  const reviewCount = review?.items.length ?? 0;
  const pageCount = pageList?.pages.length ?? status?.page_count ?? 0;

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {!wikiEnabled ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p>知识库未启用。</p>
              <button
                type="button"
                onClick={onOpenSettings}
                className="inline-flex items-center gap-1 rounded-md border border-amber-300/60 bg-amber-100/60 px-2 py-0.5 text-[11px] text-amber-900 transition-colors hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-200"
              >
                <Settings2 size={11} />
                前往功能开关
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1">
            <label className="font-label text-[11px] font-medium text-foreground/65" htmlFor="wiki-embedded-search">
              知识检索
            </label>
            <div className="mt-1 flex min-w-0 gap-2">
              <input
                id="wiki-embedded-search"
                type="search"
                value={searchQuery}
                onChange={(event) => onQueryChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') onSearch();
                }}
                placeholder="搜索已沉淀页面"
                className="min-w-0 flex-1 rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
              />
              <button
                type="button"
                onClick={isSearchLoading ? onStopSearch : onSearch}
                disabled={!isSearchLoading && searchQuery.trim().length === 0}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSearchLoading ? <Square size={13} /> : <Search size={13} />}
                {isSearchLoading ? '停止' : '搜索'}
              </button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-foreground/55">
            <span>已沉淀 {pageCount} 页</span>
            <span>待审 {reviewCount} 条</span>
            <button
              type="button"
              onClick={() => setCaptureOpen((value) => !value)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors',
                captureOpen
                  ? 'border-primary/35 bg-primary/10 text-primary'
                  : 'border-outline-variant/60 bg-surface-low text-foreground/70 hover:border-primary/35 hover:text-primary',
              )}
            >
              <FilePlus2 size={13} />
              {captureOpen ? '收起记一下' : '记一下'}
            </button>
          </div>
        </div>

        {searchError ? (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {searchError}
          </div>
        ) : null}

        {searchResult?.warnings.length ? (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            {searchResult.warnings.join(' ')}
          </div>
        ) : null}

        {searchResult && searchResult.evidence_refs.length > 0 ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {searchResult.evidence_refs.map((ref, index) => {
              const pagePath = typeof ref.page_path === 'string' ? ref.page_path : '';
              return (
                <button
                  key={`${pagePath}-${index}`}
                  type="button"
                  onClick={() => pagePath && onSelectPagePath(pagePath)}
                  disabled={!pagePath}
                  className="min-w-0 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-surface-high disabled:cursor-default disabled:opacity-70"
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <FileText size={14} className="shrink-0 text-primary/70" />
                    <span className="truncate">{ref.title || pagePath || '知识页面'}</span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/55">
                    {ref.snippet || pagePath}
                  </div>
                </button>
              );
            })}
          </div>
        ) : null}
      </section>

      {captureOpen ? (
        <SimpleCaptureForm
          isManualLoading={isManualLoading}
          manualError={manualError}
          manualResult={manualResult}
          isWikiEnabled={wikiEnabled}
          onCreateManual={onCreateManual}
          onStopManual={onStopManual}
          onClose={() => setCaptureOpen(false)}
        />
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <ReviewQueuePanel
          items={review?.items ?? null}
          isLoading={isReviewLoading}
          error={reviewError}
          onRefresh={onRefreshReview}
          onApprove={onApproveReview}
          onReject={onRejectReview}
          onWithdraw={onWithdrawReview}
        />
        <div className="grid gap-4">
          <WikiPageListPanel
            pages={pageList?.pages ?? null}
            isLoading={isPagesLoading}
            error={pagesError}
            onRefresh={onRefreshPages}
            selectedPath={selectedPagePath}
            onSelectPath={onSelectPagePath}
          />
        </div>
      </section>

      <WikiPagePreviewPanel
        selectedPath={selectedPagePath}
        page={pageDetail}
        isLoading={isPageDetailLoading}
        error={pageDetailError}
        onRefresh={onRefreshSelectedPage}
      />

      <details
        className="rounded-lg border border-outline-variant/50 bg-surface-lowest"
        open={advancedOpen}
        onToggle={(event) => setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-2 text-[11px] text-foreground/60 marker:hidden">
          <span className="inline-flex items-center gap-1.5">
            <ChevronDown size={12} className={cn('transition-transform', advancedOpen ? 'rotate-0' : '-rotate-90')} />
            更多工具
          </span>
          <span className="text-foreground/40">状态、图谱、导入、导出</span>
        </summary>
        <div className="flex flex-col gap-4 px-4 pb-4 pt-2">
          {children}
        </div>
      </details>
    </div>
  );
}

interface SimpleCaptureFormProps {
  isManualLoading: boolean;
  manualError: string | null;
  manualResult: WikiPageMutationModel | null;
  isWikiEnabled: boolean;
  onCreateManual: (input: WikiManualPageInputModel) => void;
  onStopManual: () => void;
  onClose: () => void;
}

/**
 * 轻量「记一下」表单，把 createWikiManualPage 拆出来在 embedded 顶部直接用。
 * 当前后端会创建待确认草稿，并同步进入复审队列。
 */
function SimpleCaptureForm({
  isManualLoading,
  manualError,
  manualResult,
  isWikiEnabled,
  onCreateManual,
  onStopManual,
  onClose,
}: SimpleCaptureFormProps) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState<WikiManualPageKind>('concept');
  const status: WikiManualPageStatus = 'review';

  const canSubmit = isWikiEnabled && title.trim().length > 0 && body.trim().length > 0 && !isManualLoading;

  return (
    <section className="rounded-lg border border-primary/35 bg-primary/5 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-foreground">
            <FilePlus2 size={15} className="text-primary" />
            <h3 className="font-headline text-sm font-semibold">记一下</h3>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-outline-variant/50 px-2 py-1 text-[11px] text-foreground/55 transition-colors hover:border-primary/30 hover:text-foreground"
        >
          收起
        </button>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <label className="block text-xs text-foreground/55">
          <span className="font-label text-[11px] text-foreground/45">标题</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="比如：扩散模型采样步骤的关键观察"
            className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs text-foreground/55">
            <span className="font-label text-[11px] text-foreground/45">类型</span>
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as WikiManualPageKind)}
              className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
            >
              <option value="concept">概念</option>
              <option value="synthesis">综合结论</option>
              <option value="exploration">探索记录</option>
              <option value="experiment">实验结果</option>
              <option value="question">问题</option>
              <option value="paper">论文摘要</option>
            </select>
          </label>
          <div className="rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2">
            <div className="font-label text-[11px] text-foreground/45">保存位置</div>
            <div className="mt-1 text-sm text-foreground">待确认草稿</div>
          </div>
        </div>
      </div>

      <label className="mt-3 block text-xs text-foreground/55">
        <span className="font-label text-[11px] text-foreground/45">内容</span>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={5}
          placeholder="可以粘贴原文片段、写一两句结论、附上后续要追问的问题。"
          className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
        />
      </label>

      {!isWikiEnabled ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          知识库未启用。
        </div>
      ) : null}

      {manualError ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {manualError}
        </div>
      ) : null}

      {manualResult ? (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
          已保存为待确认：{formatWikiPageLabel(manualResult.slug || manualResult.message, '新页面')}。
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={isManualLoading ? onStopManual : () => onCreateManual({
            title: title.trim(),
            kind,
            status,
            body: body.trim(),
          })}
          disabled={!isManualLoading && !canSubmit}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isManualLoading ? <Square size={13} /> : <FilePlus2 size={13} />}
          {isManualLoading ? '停止' : '保存待确认'}
        </button>
      </div>
    </section>
  );
}
