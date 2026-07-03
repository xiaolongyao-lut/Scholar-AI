import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createWikiImportMarkdown } from '@/services/wikiApi';
import { WikiImportMarkdownPanel } from './WikiImportMarkdownPanel';

vi.mock('@/services/wikiApi', () => ({
  createWikiImportMarkdown: vi.fn(),
}));

describe('WikiImportMarkdownPanel', () => {
  const originalClipboard = navigator.clipboard;

  afterEach(() => {
    vi.mocked(createWikiImportMarkdown).mockReset();
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      configurable: true,
    });
    Reflect.deleteProperty(window, 'pywebview');
  });

  it('keeps write mode blocked until the user confirms writing', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    render(<WikiImportMarkdownPanel isWikiEnabled reviewQueueCount={3} />);

    expect(screen.getByText('本地 Markdown 导入')).toBeInTheDocument();
    const input = screen.getByLabelText('Markdown 路径');
    fireEvent.change(input, { target: { value: 'C:\\temp\\draft.md' } });
    fireEvent.click(screen.getByLabelText('先预览'));

    expect(screen.getByRole('button', { name: '写入待确认' })).toBeDisabled();
    expect(screen.getByText('写入前需要勾选确认。')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('我确认写入'));
    expect(screen.getByRole('button', { name: '写入待确认' })).not.toBeDisabled();

    vi.mocked(createWikiImportMarkdown).mockResolvedValue({
      enabled: true,
      dry_run: false,
      confirm_write: true,
      imported: 1,
      skipped: 0,
      errored: 0,
      pages: [
        {
          source_path: 'notes/draft.md',
          import_source_hash: 'a'.repeat(64),
          source_hash: 'b'.repeat(64),
          content_hash: 'c'.repeat(64),
          ref_id: 'wiki:synthesis/synthesis-draft-note.md',
          chunk_id: 'wiki:synthesis/synthesis-draft-note.md#chunk-0',
          read_endpoint: '/api/agent-bridge/resource/wiki:synthesis/synthesis-draft-note.md',
          span_start: 0,
          span_end: 32,
          title: 'Draft Note',
          kind: 'synthesis',
          status: 'draft',
          slug: 'synthesis-draft-note',
          path: 'synthesis/synthesis-draft-note.md',
          action: 'created',
          review_item_id: 'import-synthesis-draft-note',
          runtime_session_id: 'session_1',
          runtime_job_id: 'job_1',
          runtime_approval_id: 'approval_1',
          warnings: [],
          error: '',
        },
      ],
      warnings: [],
    });

    fireEvent.click(screen.getByRole('button', { name: '写入待确认' }));

    await waitFor(() => expect(screen.getByText('已写入待确认')).toBeInTheDocument());
    expect(screen.getByText('引用信息')).toBeInTheDocument();
    expect(screen.getByText('导入时已保留定位')).toBeInTheDocument();
    expect(screen.queryByText('ref: wiki:synthesis/synthesis-draft-note.md')).not.toBeInTheDocument();
    expect(screen.queryByText('chunk: wiki:synthesis/synthesis-draft-note.md#chunk-0')).not.toBeInTheDocument();
    expect(screen.queryByText('/api/agent-bridge/resource/wiki:synthesis/synthesis-draft-note.md')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '复制引用信息' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('ref_id=wiki:synthesis/synthesis-draft-note.md')));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('chunk_id=wiki:synthesis/synthesis-draft-note.md#chunk-0'));
    expect(screen.getByRole('button', { name: '复制引用信息' })).toHaveTextContent('已复制');
    expect(vi.mocked(createWikiImportMarkdown)).toHaveBeenCalledWith(
      {
        source_paths: ['C:\\temp\\draft.md'],
        dry_run: false,
        confirm_write: true,
        overwrite: false,
        kind: 'synthesis',
        status: 'review',
      },
      45000,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('uses the native open dialog to add a markdown path when available', async () => {
    const openDialog = vi.fn(async () => 'C:\\notes\\selected.md');
    Object.defineProperty(window, 'pywebview', {
      value: { api: { open_dialog: openDialog } },
      configurable: true,
      writable: true,
    });

    render(<WikiImportMarkdownPanel isWikiEnabled reviewQueueCount={1} />);

    fireEvent.click(screen.getByRole('button', { name: '选择文件' }));

    await waitFor(() => expect(openDialog).toHaveBeenCalled());
    expect(screen.getByDisplayValue('C:\\notes\\selected.md')).toBeInTheDocument();
  });
});
