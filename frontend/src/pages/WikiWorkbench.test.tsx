import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import {
  approveWikiReviewItem,
  getWikiReview,
  rejectWikiReviewItem,
  withdrawWikiReviewPromotion,
  WikiApiError,
} from '@/services/wikiApi';
import type { WikiReviewItemModel } from '@/types/wiki';
import { formatPanelError, WikiWorkbench } from './WikiWorkbench';

vi.mock('@/services/wikiApi', async () => {
  const actual = await vi.importActual<typeof import('@/services/wikiApi')>('@/services/wikiApi');
  return {
    ...actual,
    getWikiStatus: vi.fn(async () => ({
      enabled: false,
      stale: false,
      integrity_status: 'disabled',
      index_hash: 'none',
      source_manifest_hash: 'unknown',
      indexed_source_manifest_hash: 'unknown',
      indexed_page_count: 0,
      source_page_count: null,
      page_count: 0,
      graph_json_exists: false,
      graph_db_exists: false,
      query_index_exists: false,
      review_queue_exists: false,
      paths: {},
      warnings: [],
      manifest_drilldown: {
        schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
        status: 'disabled',
        hash_algorithm: 'sha256',
        limit: 10,
        missing_count: 0,
        extra_count: 0,
        mismatched_count: 0,
        truncated: false,
        missing_pages: [],
        extra_pages: [],
        mismatched_pages: [],
      },
      index_exists: false,
    })),
    preflightWikiRevalidation: vi.fn(),
    applyWikiRevalidation: vi.fn(),
    getWikiPages: vi.fn(async () => ({ enabled: false, pages: [] })),
    getWikiDoctor: vi.fn(async () => ({
      enabled: false,
      report: {},
      warnings: [],
      structuredReport: null,
    })),
    getWikiReview: vi.fn(async () => ({ enabled: false, items: [] })),
    approveWikiReviewItem: vi.fn(),
    rejectWikiReviewItem: vi.fn(),
    withdrawWikiReviewPromotion: vi.fn(),
    getWikiGraph: vi.fn(async () => ({
      enabled: false,
      graph: {},
      structuredGraph: { updated_at: '', node_count: 0, edge_count: 0, nodes: [], edges: [] },
    })),
    runWikiCompileDryRun: vi.fn(),
    createWikiImportMarkdown: vi.fn(),
    searchWiki: vi.fn(),
    exportWikiMarkdown: vi.fn(),
  };
});

vi.mock('@/services/graphApi', () => ({
  getWikiEvidenceGraph: vi.fn(async () => ({
    version: 'v1',
    scope: { kind: 'project', ref: '' },
    updated_at: '2026-07-16T00:00:00Z',
    nodes: [],
    edges: [],
    warnings: [],
  })),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function pageReviewItem(
  itemRevision: string,
  expectedContentHash: string,
): WikiReviewItemModel {
  return {
    item_id: 'review-cas',
    kind: 'draft',
    title: '并发候选页',
    page_path: 'drafts/concurrent.md',
    summary: '等待人工判断。',
    status: 'pending',
    created_at: '2026-07-16T00:00:00Z',
    source: 'manual_frontend',
    metadata: {},
    schema_version: 2,
    item_revision: itemRevision,
    target: {
      schema_version: 'scholar-ai-wiki-page-revision-target/v2',
      type: 'wiki_page_revision',
      page_id: 'concurrent',
      page_path: 'drafts/concurrent.md',
      expected_content_hash: expectedContentHash,
      expected_status: 'review',
    },
    promotion_intent: null,
    allowed_actions: ['approve', 'reject'],
    decision: null,
  };
}

describe('WikiWorkbench panel error formatting', () => {
  it('hides backend routes, env labels, capability ids, and local paths', () => {
    const error = new Error(
      'GET /api/wiki/search failed env=VISION_PROVIDER capability_resolved C:\\Users\\example-user\\wiki',
    );

    const message = formatPanelError(error, 'Wiki 搜索');

    expect(message).toBe('读取Wiki 搜索失败。');
    expect(message).not.toContain('/api/wiki/search');
    expect(message).not.toContain('env=VISION_PROVIDER');
    expect(message).not.toContain('capability_resolved');
    expect(message).not.toContain('C:\\Users\\example-user');
  });

  it('keeps safe user-facing Wiki API errors', () => {
    expect(formatPanelError(new WikiApiError('Wiki 集成尚未启用。', 400), 'Wiki 状态')).toBe(
      'Wiki 集成尚未启用。',
    );
  });

  it('summarizes server-side Wiki failures without raw detail', () => {
    const message = formatPanelError(
      new WikiApiError('{"detail":"page_store_path missing"}', 503),
      'Wiki 图谱',
    );

    expect(message).toBe('Wiki 图谱暂不可用（503）。请确认后端服务已启动并已启用对应功能。');
    expect(message).not.toContain('page_store_path');
  });

  it('opens the Settings feature switchboard from the disabled Wiki prompt', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
          <Route path="/settings" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('知识库当前未启用')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '查看功能开关' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/settings?section=experimental');
  });

  it('renders local markdown import controls and keeps the flow dry-run-first', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('本地 Markdown 导入')).toBeInTheDocument());
    expect(screen.getByText('先预览，再写入待确认。')).toBeInTheDocument();
    expect(screen.getByLabelText('Markdown 路径')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '预览' })).toBeDisabled();
  });

  it('writes a review decision only after the user enters a reason and clicks approve', async () => {
    vi.mocked(getWikiReview).mockResolvedValueOnce({
      enabled: true,
      items: [{
        item_id: 'review-1',
        kind: 'draft',
        title: '候选知识页',
        page_path: 'drafts/candidate.md',
        summary: '等待人工判断。',
        status: 'pending',
        created_at: '2026-07-16T00:00:00Z',
        source: 'manual_frontend',
        metadata: {},
        schema_version: 2,
        item_revision: 'review-revision-1',
        target: {
          schema_version: 'scholar-ai-wiki-page-revision-target/v2',
          type: 'wiki_page_revision',
          page_id: 'candidate',
          page_path: 'drafts/candidate.md',
          expected_content_hash: 'a'.repeat(64),
          expected_status: 'review',
        },
        promotion_intent: null,
        allowed_actions: ['approve', 'reject'],
        decision: null,
      }],
    });
    vi.mocked(approveWikiReviewItem).mockResolvedValue({
      item_id: 'review-1',
      kind: 'draft',
      title: '候选知识页',
      page_path: 'drafts/candidate.md',
      summary: '等待人工判断。',
      status: 'approved',
      created_at: '2026-07-16T00:00:00Z',
      source: 'manual_frontend',
      metadata: {},
      schema_version: 2,
      item_revision: 'review-revision-1',
      target: {
        schema_version: 'scholar-ai-wiki-page-revision-target/v2',
        type: 'wiki_page_revision',
        page_id: 'candidate',
        page_path: 'drafts/candidate.md',
        expected_content_hash: 'a'.repeat(64),
        expected_status: 'review',
      },
      promotion_intent: null,
      allowed_actions: [],
      decision: {
        status: 'approved',
        reason: '证据一致。',
        decided_at: '2026-07-16T01:00:00Z',
        decided_by: 'user',
        promotion_receipt: {
          schema_version: 'scholar-ai-wiki-promotion-receipt/v2',
          receipt_id: 'receipt-1',
          review_item_id: 'review-1',
          request_id: 'wiki-review-request-1',
          expected_item_revision: 'review-revision-1',
          request_fingerprint: 'b'.repeat(64),
          outcome: 'promoted',
          target: {
            schema_version: 'scholar-ai-wiki-page-revision-target/v2',
            type: 'wiki_page_revision',
            page_id: 'candidate',
            page_path: 'drafts/candidate.md',
            expected_content_hash: 'a'.repeat(64),
            expected_status: 'review',
          },
          before_content_hash: 'a'.repeat(64),
          after_content_hash: 'c'.repeat(64),
          previous_status: 'review',
          promoted_status: 'final',
          promoted_at: '2026-07-16T01:00:00Z',
          promoted_by: 'user',
        },
      },
    });

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('审核理由：候选知识页');
    expect(approveWikiReviewItem).not.toHaveBeenCalled();
    fireEvent.change(reason, { target: { value: '证据一致。' } });
    fireEvent.click(screen.getByRole('button', { name: '接受并晋升' }));

    await waitFor(() => {
      expect(approveWikiReviewItem).toHaveBeenCalledWith({
        target_type: 'wiki_page_revision',
        item_id: 'review-1',
        reason: '证据一致。',
        decided_by: 'user',
        request_id: expect.stringMatching(/^wiki-review-/),
        expected_item_revision: 'review-revision-1',
        expected_target_content_hash: 'a'.repeat(64),
      });
    });
  });

  it('binds a non-page rejection to the visible review item revision', async () => {
    vi.mocked(rejectWikiReviewItem).mockClear();
    vi.mocked(getWikiReview).mockResolvedValueOnce({
      enabled: true,
      items: [{
        item_id: 'review-warning-1',
        kind: 'warning',
        title: '引用范围警告',
        page_path: 'artifacts/citation-warning.json',
        summary: '需要人工判断。',
        status: 'pending',
        created_at: '2026-07-16T00:00:00Z',
        source: 'citation-review',
        metadata: {},
        schema_version: 2,
        item_revision: 'warning-revision-1',
        target: null,
        promotion_intent: null,
        allowed_actions: ['approve', 'reject'],
        decision: null,
      }],
    });
    vi.mocked(rejectWikiReviewItem).mockResolvedValue({
      item_id: 'review-warning-1',
      kind: 'warning',
      title: '引用范围警告',
      page_path: 'artifacts/citation-warning.json',
      summary: '需要人工判断。',
      status: 'rejected',
      created_at: '2026-07-16T00:00:00Z',
      source: 'citation-review',
      metadata: {},
      schema_version: 2,
      item_revision: 'warning-revision-2',
      target: null,
      promotion_intent: null,
      allowed_actions: [],
      decision: {
        status: 'rejected',
        reason: '引用范围不成立。',
        decided_at: '2026-07-16T01:00:00Z',
        decided_by: 'user',
        promotion_receipt: null,
      },
    });

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('审核理由：引用范围警告');
    fireEvent.change(reason, { target: { value: '引用范围不成立。' } });
    fireEvent.click(screen.getByRole('button', { name: '退回审核项' }));

    await waitFor(() => {
      expect(rejectWikiReviewItem).toHaveBeenCalledWith({
        target_type: 'unbound',
        item_id: 'review-warning-1',
        reason: '引用范围不成立。',
        decided_by: 'user',
        request_id: expect.stringMatching(/^wiki-review-/),
        expected_item_revision: 'warning-revision-1',
      });
    });
  });

  it('reuses the request id for an identical failed retry and rotates it when parameters change', async () => {
    vi.mocked(approveWikiReviewItem).mockClear();
    vi.mocked(getWikiReview).mockResolvedValueOnce({
      enabled: true,
      items: [{
        item_id: 'review-retry',
        kind: 'draft',
        title: '重试候选页',
        page_path: 'drafts/retry.md',
        summary: '等待人工判断。',
        status: 'pending',
        created_at: '2026-07-16T00:00:00Z',
        source: 'manual_frontend',
        metadata: {},
        schema_version: 2,
        item_revision: 'review-revision-retry',
        target: {
          schema_version: 'scholar-ai-wiki-page-revision-target/v2',
          type: 'wiki_page_revision',
          page_id: 'retry',
          page_path: 'drafts/retry.md',
          expected_content_hash: 'd'.repeat(64),
          expected_status: 'review',
        },
        promotion_intent: null,
        allowed_actions: ['approve', 'reject'],
        decision: null,
      }],
    });
    vi.mocked(approveWikiReviewItem).mockRejectedValue(new Error('temporary failure'));

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('审核理由：重试候选页');
    const approve = screen.getByRole('button', { name: '接受并晋升' });
    fireEvent.change(reason, { target: { value: '证据一致。' } });
    fireEvent.click(approve);
    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.click(approve);
    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledTimes(2));

    const firstRequestId = vi.mocked(approveWikiReviewItem).mock.calls[0][0].request_id;
    const secondRequestId = vi.mocked(approveWikiReviewItem).mock.calls[1][0].request_id;
    expect(secondRequestId).toBe(firstRequestId);

    fireEvent.change(reason, { target: { value: '补充核对后仍一致。' } });
    fireEvent.click(approve);
    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledTimes(3));
    expect(vi.mocked(approveWikiReviewItem).mock.calls[2][0].request_id).not.toBe(firstRequestId);
  });

  it('resumes a persisted promotion intent with the original request after restart', async () => {
    vi.mocked(approveWikiReviewItem).mockClear();
    vi.mocked(withdrawWikiReviewPromotion).mockClear();
    vi.mocked(getWikiReview).mockResolvedValueOnce({
      enabled: true,
      items: [{
        item_id: 'review-resume',
        kind: 'draft',
        title: '待恢复候选页',
        page_path: 'drafts/resume.md',
        summary: '晋升已开始。',
        status: 'pending',
        created_at: '2026-07-16T00:00:00Z',
        source: 'manual_frontend',
        metadata: {},
        schema_version: 2,
        item_revision: 'review-revision-resume',
        target: {
          schema_version: 'scholar-ai-wiki-page-revision-target/v2',
          type: 'wiki_page_revision',
          page_id: 'resume',
          page_path: 'drafts/resume.md',
          expected_content_hash: 'a'.repeat(64),
          expected_status: 'review',
        },
        promotion_intent: {
          schema_version: 'scholar-ai-wiki-promotion-intent/v1',
          operation_id: 'operation-resume',
          review_item_id: 'review-resume',
          request_id: 'request-before-restart',
          expected_item_revision: 'review-revision-resume',
          request_fingerprint: 'b'.repeat(64),
          reason: '重启前已核实。',
          target: {
            schema_version: 'scholar-ai-wiki-page-revision-target/v2',
            type: 'wiki_page_revision',
            page_id: 'resume',
            page_path: 'drafts/resume.md',
            expected_content_hash: 'a'.repeat(64),
            expected_status: 'review',
          },
          before_content_hash: 'a'.repeat(64),
          after_content_hash: 'c'.repeat(64),
          previous_status: 'review',
          promoted_status: 'final',
          promoted_at: '2026-07-16T01:00:00Z',
          promoted_by: 'local-user',
        },
        allowed_actions: ['approve', 'withdraw'],
        decision: null,
      }],
    });
    vi.mocked(approveWikiReviewItem).mockRejectedValueOnce(new Error('simulated retry stop'));

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('审核理由：待恢复候选页');
    await waitFor(() => expect(reason).toHaveValue('重启前已核实。'));
    fireEvent.click(screen.getByRole('button', { name: '继续完成晋升' }));

    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledWith({
      target_type: 'wiki_page_revision',
      item_id: 'review-resume',
      reason: '重启前已核实。',
      decided_by: 'user',
      request_id: 'request-before-restart',
      expected_item_revision: 'review-revision-resume',
      expected_target_content_hash: 'a'.repeat(64),
    }));

    const withdrawalReason = screen.getByLabelText('撤回理由：待恢复候选页');
    fireEvent.change(withdrawalReason, { target: { value: '需要补充核对。' } });
    fireEvent.click(screen.getByRole('button', { name: '撤回晋升' }));

    await waitFor(() => expect(withdrawWikiReviewPromotion).toHaveBeenCalledWith({
      item_id: 'review-resume',
      reason: '需要补充核对。',
      expected_item_revision: 'review-revision-resume',
      expected_promotion_operation_id: 'operation-resume',
    }));
  });

  it('records an annotation decision without exposing Wiki promotion actions', async () => {
    const annotationItem: WikiReviewItemModel = {
      item_id: 'annotation-review-1',
      kind: 'annotation_note',
      title: '研究批注',
      page_path: 'annotations/material-1/note-1',
      summary: '一条显式送审的文献批注。',
      status: 'pending',
      created_at: '2026-07-16T00:00:00Z',
      source: 'annotation',
      metadata: {},
      schema_version: 2,
      item_revision: 'annotation-revision-1',
      target: {
        schema_version: 'scholar-ai-annotation-note-review-target/v1',
        type: 'annotation_note',
        project_id: 'project-1',
        material_id: 'material-1',
        note_id: 'note-1',
        expected_updated_at: '2026-07-16T00:00:00Z',
        expected_content_hash: 'd'.repeat(64),
        required_scope: 'wiki_review',
      },
      promotion_intent: null,
      allowed_actions: ['approve', 'reject'],
      decision: null,
    };
    vi.mocked(getWikiReview).mockReset();
    vi.mocked(getWikiReview).mockResolvedValue({ enabled: true, items: [annotationItem] });
    vi.mocked(approveWikiReviewItem).mockReset();
    vi.mocked(approveWikiReviewItem).mockResolvedValue({
      ...annotationItem,
      status: 'approved',
      allowed_actions: [],
      decision: {
        status: 'approved',
        reason: '批注内容与原文一致。',
        decided_at: '2026-07-16T01:00:00Z',
        decided_by: 'user',
        promotion_receipt: null,
      },
    });

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('批注审核理由：研究批注');
    expect(screen.getByText('批注审核只记录人工决定，不会创建 Wiki 页面或确认图谱事实。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '接受并晋升' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '撤回晋升' })).not.toBeInTheDocument();
    fireEvent.change(reason, { target: { value: '批注内容与原文一致。' } });
    fireEvent.click(screen.getByRole('button', { name: '通过批注审核' }));

    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledWith({
      target_type: 'annotation_note',
      item_id: 'annotation-review-1',
      reason: '批注内容与原文一致。',
      decided_by: 'user',
      request_id: expect.stringMatching(/^wiki-review-/),
      expected_item_revision: 'annotation-revision-1',
      expected_target_content_hash: 'd'.repeat(64),
    }));
  });

  it('refreshes a 409 conflict, preserves the reason, and renews the CAS request', async () => {
    const staleItem = pageReviewItem('review-revision-1', 'a'.repeat(64));
    const refreshedItem = pageReviewItem('review-revision-2', 'b'.repeat(64));
    vi.mocked(getWikiReview).mockReset();
    vi.mocked(getWikiReview)
      .mockResolvedValueOnce({ enabled: true, items: [staleItem] })
      .mockResolvedValue({ enabled: true, items: [refreshedItem] });
    vi.mocked(approveWikiReviewItem).mockReset();
    vi.mocked(approveWikiReviewItem)
      .mockRejectedValueOnce(new WikiApiError('review item revision changed', 409))
      .mockResolvedValue({
        ...refreshedItem,
        status: 'approved',
        allowed_actions: [],
        decision: {
          status: 'approved',
          reason: '证据一致。',
          decided_at: '2026-07-16T01:00:00Z',
          decided_by: 'user',
          promotion_receipt: null,
        },
      });

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    const reason = await screen.findByLabelText('审核理由：并发候选页');
    fireEvent.change(reason, { target: { value: '证据一致。' } });
    fireEvent.click(screen.getByRole('button', { name: '接受并晋升' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('审核项已发生变化，已刷新为最新版本；请核对后重试。');
    const refreshedReason = await screen.findByLabelText('审核理由：并发候选页');
    expect(refreshedReason).toHaveValue('证据一致。');
    fireEvent.click(screen.getByRole('button', { name: '接受并晋升' }));

    await waitFor(() => expect(approveWikiReviewItem).toHaveBeenCalledTimes(2));
    const firstRequest = vi.mocked(approveWikiReviewItem).mock.calls[0][0];
    const retryRequest = vi.mocked(approveWikiReviewItem).mock.calls[1][0];
    expect(firstRequest).toMatchObject({
      target_type: 'wiki_page_revision',
      expected_item_revision: 'review-revision-1',
      expected_target_content_hash: 'a'.repeat(64),
    });
    expect(retryRequest).toMatchObject({
      target_type: 'wiki_page_revision',
      expected_item_revision: 'review-revision-2',
      expected_target_content_hash: 'b'.repeat(64),
    });
    expect(retryRequest.request_id).not.toBe(firstRequest.request_id);
  });
});
