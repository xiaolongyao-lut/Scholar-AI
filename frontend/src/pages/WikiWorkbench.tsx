import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, BookMarked, CheckCircle2, Download, FileText, RefreshCw, Search, Settings2, ShieldCheck, Square } from 'lucide-react';

import { WikiCompileDryRunPanel } from '@/components/wiki/WikiCompileDryRunPanel';
import { DoctorReportPanel } from '@/components/wiki/DoctorReportPanel';
import { GraphDebugPanel } from '@/components/wiki/GraphDebugPanel';
import { GraphPayloadViewer } from '@/components/graph/GraphPayloadViewer';
import type { GraphPayloadV0 } from '@/components/graph/payloadToRf';
import { getGraphPayload } from '@/services/graphApi';
import { WikiPagePreviewPanel } from '@/components/wiki/WikiPagePreviewPanel';
import { ReviewQueuePanel } from '@/components/wiki/ReviewQueuePanel';
import { WikiPageListPanel } from '@/components/wiki/WikiPageListPanel';
import { WikiStatusCard } from '@/components/wiki/WikiStatusCard';
import { PageHeader } from '@/components/common/PageHeader';
import { formatWikiError } from '@/components/wiki/wikiDisplay';
import { buildSettingsSectionPath } from '@/pages/settingsSections';
import {
  getWikiDoctor,
  getWikiGraph,
  getWikiPageDetail,
  getWikiPages,
  getWikiReview,
  getWikiStatus,
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
  WikiPageMutationModel,
  WikiDoctorModel,
  WikiGraphModel,
  WikiPageDetailModel,
  WikiPageListModel,
  WikiReviewListModel,
  WikiSearchModel,
  WikiExportModel,
  WikiStatusModel,
} from '@/types/wiki';

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

export function WikiWorkbench({ embedded = false }: WikiWorkbenchProps = {}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState<WikiStatusModel | null>(null);
  const [isStatusLoading, setIsStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
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
  const [graphPayload, setGraphPayload] = useState<GraphPayloadV0 | null>(null);
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

  const targetPagePath = useMemo(() => {
    const page = searchParams.get('page')?.trim();
    return page && page.length > 0 ? page : null;
  }, [searchParams]);

  const loadStatus = useCallback(async () => {
    setIsStatusLoading(true);
    setStatusError(null);
    try {
      setStatus(await getWikiStatus());
    } catch (err: unknown) {
      setStatusError(formatPanelError(err, 'Wiki 状态'));
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
      setPagesError(formatPanelError(err, 'Wiki 页面列表'));
    } finally {
      setIsPagesLoading(false);
    }
  }, []);

  const loadDoctor = useCallback(async () => {
    setIsDoctorLoading(true);
    setDoctorError(null);
    try {
      setDoctor(await getWikiDoctor());
    } catch (err: unknown) {
      setDoctorError(formatPanelError(err, 'Wiki 诊断'));
    } finally {
      setIsDoctorLoading(false);
    }
  }, []);

  const loadReview = useCallback(async () => {
    setIsReviewLoading(true);
    setReviewError(null);
    try {
      setReview(await getWikiReview());
    } catch (err: unknown) {
      setReviewError(formatPanelError(err, 'Wiki 复审队列'));
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
      setGraphError(formatPanelError(err, 'Wiki 图谱'));
    } finally {
      setIsGraphLoading(false);
    }
  }, []);

  const loadGraphPayload = useCallback(async () => {
    setIsGraphPayloadLoading(true);
    setGraphPayloadError(null);
    try {
      setGraphPayload(await getGraphPayload());
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
      setPageDetailError(formatPanelError(err, 'Wiki 页面预览'));
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
      setCompileError(formatPanelError(err, 'Wiki 编译'));
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
      setManualCreateError(formatPanelError(err, 'Wiki 手动录入'));
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
      setSearchError(formatPanelError(err, 'Wiki 搜索'));
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
      setExportError(formatPanelError(err, 'Wiki 导出'));
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
      return '正在加载 Wiki 状态…';
    }
    if (!status.enabled) {
      return 'Wiki 当前未启用';
    }
    if (status.stale) {
      return 'Wiki 已启用，索引需要重新生成';
    }
    return 'Wiki 已启用，索引为最新';
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
          subtitle="面向文献证据的编译知识层：页面、检索、图谱、健康诊断、复审队列和编译预案在这里统一管理。"
          className="mb-0"
        />
      ) : null}

      <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-xs leading-6 text-foreground/65">
        <div className="flex flex-wrap items-center gap-2 font-medium text-foreground/80">
          <span className="rounded bg-primary/10 px-2 py-0.5 text-[11px] text-primary">触发方式</span>
          <span>先在设置里打开“Wiki 知识沉淀”，再运行智能研读、多智能体讨论、写作编译、页面搜索或知识编译；这些动作会把可编译页面写入 Wiki。这里用探查按钮一次检查页面、图谱、索引和复审队列。</span>
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
            探查触发状态
          </button>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <span>启用：{status?.enabled ? '已开启' : '未开启'}</span>
          <span>页面：{pageList?.pages.length ?? status?.page_count ?? 0} 个</span>
          <span>复审：{review?.items.length ?? 0} 条</span>
          <span>图谱：{graphPayload ? `${graphPayload.nodes.length} 节点 / ${graphPayload.edges.length} 边` : '未生成'}</span>
        </div>
        <div className="mt-2 rounded-md border border-outline-variant/40 bg-surface-low px-3 py-2 text-[11px] text-foreground/55">
          如果探查后仍为空，先确认功能开关已打开，再检查任务中心里对应的智能研读、讨论或编译任务是否真的完成。
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
          <GraphPayloadViewer
            payload={graphPayload}
            loading={isGraphPayloadLoading}
            error={graphPayloadError}
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
        <WikiStatusCard status={status} isLoading={isStatusLoading} error={statusError} onRefresh={() => void loadStatus()} />
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
            <h2 className="font-headline text-base font-semibold text-foreground">Wiki 知识层</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-foreground/55">
              Wiki 保存由文献证据支撑的页面、检索索引、图谱关系、待审页面和编译预案；“学到的经验”只处理任务、讨论和工具运行里沉淀的可复用经验，不放 Wiki 页面。
            </p>
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
            <div className="space-y-2">
                <p>
                  Wiki 当前未启用。请点“前往功能开关”，在设置里的“功能开关”中开启“Wiki 知识沉淀”，再返回本页刷新。
                </p>
              <details>
                <summary className="cursor-pointer text-amber-900/75 transition-colors hover:text-amber-950 dark:text-amber-200/80 dark:hover:text-amber-100">
                  它和经验沉淀有什么区别？
                </summary>
                <p className="mt-1 text-amber-900/70 dark:text-amber-200/75">
                  Wiki 用来沉淀项目资料的知识页、检索索引、图谱关系和复审队列；“学到的经验”用来复审智能研读、讨论、写作任务和工具运行中产生的可复用经验，两者相互独立。
                </p>
              </details>
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
            Wiki 检索
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
                  <span className="truncate">{ref.title || pagePath || 'Wiki 页面'}</span>
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
