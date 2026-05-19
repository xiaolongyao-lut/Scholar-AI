import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BookMarked } from 'lucide-react';

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
import {
  getWikiDoctor,
  getWikiGraph,
  getWikiPageDetail,
  getWikiPages,
  getWikiReview,
  getWikiStatus,
  runWikiCompileDryRun,
  WikiApiError,
} from '@/services/wikiApi';
import type {
  WikiCompileDryRunInputModel,
  WikiCompileDryRunModel,
  WikiDoctorModel,
  WikiGraphModel,
  WikiPageDetailModel,
  WikiPageListModel,
  WikiReviewListModel,
  WikiStatusModel,
} from '@/types/wiki';

function formatPanelError(err: unknown, label: string, route: string): string {
  if (err instanceof WikiApiError) {
    return err.status >= 500
      ? `${label}接口暂不可用（${err.status}）。请确认后端已启动并已挂载 ${route}。`
      : err.message;
  }
  if (err instanceof Error) {
    return err.message === 'Failed to fetch'
      ? `${label}接口不可达。请确认前端当前能访问后端 API。`
      : err.message;
  }
  return `读取${label}失败。`;
}

export function WikiWorkbench() {
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
      setStatusError(formatPanelError(err, 'Wiki 状态', '/api/wiki/status'));
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
      setPagesError(formatPanelError(err, 'Wiki 页面列表', '/api/wiki/pages'));
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
      setDoctorError(formatPanelError(err, 'Wiki 诊断', '/api/wiki/doctor'));
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
      setReviewError(formatPanelError(err, 'Wiki 复审队列', '/api/wiki/review'));
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
      setGraphError(formatPanelError(err, 'Wiki 图谱', '/api/wiki/graph'));
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
      setGraphPayloadError(formatPanelError(err, '知识图谱视图', '/api/graph/payload'));
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
      setPageDetailError(formatPanelError(err, 'Wiki 页面预览', '/api/wiki/pages/{page_path}'));
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
    setIsCompileLoading(true);
    setCompileError(null);
    try {
      setCompileResult(await runWikiCompileDryRun(input));
    } catch (err: unknown) {
      setCompileError(formatPanelError(err, 'Wiki 编译', '/api/wiki/compile'));
    } finally {
      setIsCompileLoading(false);
    }
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto bg-background px-6 py-5">
      <PageHeader
        icon={<BookMarked size={18} />}
        title={headline}
        subtitle="管理 Wiki 状态、页面列表、复审队列、知识图谱与编译计划。"
        className="mb-0"
      />

      <WikiStatusCard status={status} isLoading={isStatusLoading} error={statusError} onRefresh={() => void loadStatus()} />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
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

      <section className="grid gap-4 xl:grid-cols-2">
        <DoctorReportPanel
          doctor={doctor}
          isLoading={isDoctorLoading}
          error={doctorError}
          onRefresh={() => void loadDoctor()}
        />
        <WikiCompileDryRunPanel
          result={compileResult}
          isLoading={isCompileLoading}
          error={compileError}
          isWikiEnabled={status?.enabled ?? false}
          isWikiStale={status?.stale ?? false}
          onRun={(input) => void handleRunCompileDryRun(input)}
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

      <section className="grid gap-4 xl:grid-cols-2">
        <ReviewQueuePanel
          items={review?.items ?? null}
          isLoading={isReviewLoading}
          error={reviewError}
          onRefresh={() => void loadReview()}
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
