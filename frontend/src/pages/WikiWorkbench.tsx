import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BookMarked } from 'lucide-react';

import { WikiCompileDryRunPanel } from '@/components/wiki/WikiCompileDryRunPanel';
import { DoctorReportPanel } from '@/components/wiki/DoctorReportPanel';
import { GraphDebugPanel } from '@/components/wiki/GraphDebugPanel';
import { WikiPagePreviewPanel } from '@/components/wiki/WikiPagePreviewPanel';
import { ReviewQueuePanel } from '@/components/wiki/ReviewQueuePanel';
import { WikiPageListPanel } from '@/components/wiki/WikiPageListPanel';
import { WikiStatusCard } from '@/components/wiki/WikiStatusCard';
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
      setDoctorError(formatPanelError(err, 'Wiki Doctor', '/api/wiki/doctor'));
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
      setReviewError(formatPanelError(err, 'Wiki Review', '/api/wiki/review'));
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
      setGraphError(formatPanelError(err, 'Wiki Graph', '/api/wiki/graph'));
    } finally {
      setIsGraphLoading(false);
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
      setCompileError(formatPanelError(err, 'Wiki Compile', '/api/wiki/compile'));
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
  }, [loadDoctor, loadGraph, loadPages, loadReview, loadStatus]);

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
      return '正在同步 Wiki 控制面…';
    }
    if (!status.enabled) {
      return 'Wiki 当前保持 default-off，可安全观测';
    }
    if (status.stale) {
      return 'Wiki 已启用，但索引状态需要人工关注';
    }
    return 'Wiki 已启用，status 面保持对齐';
  }, [status]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 p-8">
      <section className="relative overflow-hidden rounded-[28px] border border-outline-variant/40 bg-surface-lowest px-6 py-8 shadow-sm">
        <div className="absolute inset-y-0 right-0 w-1/3 bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.14),_transparent_60%)]" />
        <div className="relative max-w-3xl space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-label uppercase tracking-[0.22em] text-primary/80">
            <BookMarked size={13} />
            Wave 12 / Wiki workbench
          </div>
          <h1 className="font-display text-3xl font-semibold text-foreground">{headline}</h1>
          <p className="max-w-2xl font-body text-sm leading-7 text-foreground/60">
            这一页先把 Wiki 的状态面做实：它应该让人一眼看出 enabled / stale / page count / canonical paths，
            同时把 Pages、Review、Graph、Doctor 四个后续分区提前摆上桌面，而不是把所有能力埋进 API 文档里。
          </p>
        </div>
      </section>

      <WikiStatusCard status={status} isLoading={isStatusLoading} error={statusError} onRefresh={() => void loadStatus()} />

      <section className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
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

      <section className="grid gap-6 xl:grid-cols-2">
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

      <section className="grid gap-6 xl:grid-cols-2">
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