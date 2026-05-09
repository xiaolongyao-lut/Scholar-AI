import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { WikiReviewItemModel } from '@/types/wiki';

import { ReviewQueuePanel } from './ReviewQueuePanel';

const reviewItems: WikiReviewItemModel[] = [
  {
    item_id: 'review-1',
    kind: 'claim',
    title: '需要人工复核的 Claim',
    page_path: 'claims/claim-a.md',
    summary: 'Claim 需要补充 quote context。',
    status: 'pending',
    created_at: '2026-05-04T10:00:00Z',
    source: 'doctor',
    metadata: {},
    decision: null,
  },
  {
    item_id: 'review-2',
    kind: 'synthesis',
    title: '已批准的综合页',
    page_path: 'synthesis/topic-a.md',
    summary: '证据链已经完成。',
    status: 'approved',
    created_at: '2026-05-04T11:00:00Z',
    source: 'reviewer',
    metadata: { priority: 'low' },
    decision: {
      status: 'approved',
      reason: '证据链完整，可进入 final。',
      decided_at: '2026-05-04T11:10:00Z',
      decided_by: 'reviewer-a',
    },
  },
];

describe('ReviewQueuePanel', () => {
  it('renders review statuses, decision details, and local status filtering', () => {
    const onRefresh = vi.fn();
    render(<ReviewQueuePanel items={reviewItems} isLoading={false} error={null} onRefresh={onRefresh} />);

    expect(screen.getByRole('heading', { name: '治理队列只读面' })).toBeInTheDocument();
    expect(screen.getByText('需要人工复核的 Claim')).toBeInTheDocument();
    expect(screen.getByText('claims/claim-a.md')).toBeInTheDocument();
    expect(screen.getByText('证据链完整，可进入 final。')).toBeInTheDocument();
    expect(screen.getByText('2 / 2 items')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'approved' } });

    expect(screen.queryByText('需要人工复核的 Claim')).not.toBeInTheDocument();
    expect(screen.getByText('已批准的综合页')).toBeInTheDocument();
    expect(screen.getByText('1 / 2 items')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /刷新 review queue/i }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
