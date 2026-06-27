import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { WikiStatusModel } from '@/types/wiki';

import { WikiStatusCard } from './WikiStatusCard';

const alignedStatus: WikiStatusModel = {
  enabled: true,
  page_count: 3,
  stale: false,
  integrity_status: 'aligned',
  index_hash: 'abcdef0123456789',
  source_manifest_hash: '1234567890abcdef1234567890abcdef',
  indexed_source_manifest_hash: '1234567890abcdef1234567890abcdef',
  indexed_page_count: 3,
  source_page_count: 3,
  graph_json_exists: true,
  graph_db_exists: true,
  query_index_exists: true,
  review_queue_exists: false,
  paths: {},
  warnings: [],
  manifest_drilldown: {
    schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
    status: 'aligned',
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
};

describe('WikiStatusCard', () => {
  it('renders wiki source manifest integrity and refresh behavior', () => {
    const onRefresh = vi.fn();

    render(<WikiStatusCard status={alignedStatus} isLoading={false} error={null} onRefresh={onRefresh} />);

    expect(screen.getByRole('status', { name: 'Wiki 来源完整性' })).toHaveTextContent('来源已对齐');
    expect(screen.getByRole('status', { name: 'Wiki 来源完整性' })).toHaveTextContent('模型上下文：允许 Wiki 引用');
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(screen.getAllByText('1234567890ab')).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: /刷新状态/i }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('surfaces source hash mismatch as a blocking integrity state', () => {
    render(
      <WikiStatusCard
        status={{
          ...alignedStatus,
          stale: true,
          integrity_status: 'source_hash_mismatch',
          source_manifest_hash: 'aaaaaaaaaaaabbbbbbbbbbbbcccccccccccc',
          indexed_source_manifest_hash: 'ddddddddddddeeeeeeeeeeeeffffffffffff',
          warnings: ['Wiki query index source manifest hash differs from the current generated wiki pages.'],
        }}
        isLoading={false}
        error={null}
        onRefresh={vi.fn()}
      />,
    );

    const integrity = screen.getByRole('status', { name: 'Wiki 来源完整性' });
    expect(integrity).toHaveTextContent('来源已变更');
    expect(integrity).toHaveTextContent('模型上下文：阻断 Wiki 引用');
    expect(screen.getByText('aaaaaaaaaaaa')).toBeInTheDocument();
    expect(screen.getByText('dddddddddddd')).toBeInTheDocument();
    expect(screen.getByText('Wiki 来源清单已变化，检索索引需要重新生成。')).toBeInTheDocument();
  });

  it('renders page-level manifest drift counts and bounded samples', () => {
    render(
      <WikiStatusCard
        status={{
          ...alignedStatus,
          stale: true,
          integrity_status: 'source_hash_mismatch',
          manifest_drilldown: {
            schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
            status: 'source_hash_mismatch',
            hash_algorithm: 'sha256',
            limit: 10,
            missing_count: 1,
            extra_count: 1,
            mismatched_count: 1,
            truncated: false,
            missing_pages: [
              {
                kind: 'missing',
                page_path: 'concepts/d.md',
                source_hash: 'a'.repeat(64),
                indexed_hash: null,
                redacted: false,
              },
            ],
            extra_pages: [
              {
                kind: 'extra',
                page_path: '<redacted>',
                source_hash: null,
                indexed_hash: null,
                redacted: true,
              },
            ],
            mismatched_pages: [
              {
                kind: 'mismatched',
                page_path: 'concepts/a.md',
                source_hash: 'b'.repeat(64),
                indexed_hash: 'c'.repeat(64),
                redacted: false,
              },
            ],
          },
        }}
        isLoading={false}
        error={null}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('源页未入索引')).toBeInTheDocument();
    expect(screen.getByText('索引多余页')).toBeInTheDocument();
    expect(screen.getByText('Hash 不一致')).toBeInTheDocument();
    expect(screen.getByText('concepts/d.md')).toBeInTheDocument();
    expect(screen.getByText('已隐藏路径')).toBeInTheDocument();
    expect(screen.getByText('concepts/a.md')).toBeInTheDocument();
  });

  it.each([
    ['disabled', { enabled: false, integrity_status: 'disabled' }, '模型上下文：未启用'],
    ['empty_no_index', { integrity_status: 'empty_no_index', indexed_page_count: 0, source_page_count: 0 }, '模型上下文：暂无可用索引'],
    ['indexed_manifest_recorded', { integrity_status: 'indexed_manifest_recorded' }, '模型上下文：待来源复核'],
  ])('does not claim model context is allowed for %s integrity state', (_label, overrides, expectedText) => {
    render(
      <WikiStatusCard
        status={{
          ...alignedStatus,
          ...overrides,
        }}
        isLoading={false}
        error={null}
        onRefresh={vi.fn()}
      />,
    );

    const integrity = screen.getByRole('status', { name: 'Wiki 来源完整性' });
    expect(integrity).toHaveTextContent(expectedText);
    expect(integrity).not.toHaveTextContent('模型上下文：允许 Wiki 引用');
  });
});
