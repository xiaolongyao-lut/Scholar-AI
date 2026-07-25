import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { UploadBatchSummary } from './UploadBatchSummaryView';

describe('UploadBatchSummary', () => {
  it('renders queued uploads as accepted background work, not completed success', () => {
    render(
      <UploadBatchSummary
        result={{
          accepted_files: 2,
          completed_files: 0,
          queued_files: 2,
          duplicate_files: 1,
          skipped_files: 1,
          failed_files: 0,
          total_chunks: 0,
        }}
      />,
    );

    expect(screen.getByLabelText('后台处理中')).toHaveClass('animate-spin');
    expect(screen.getByText('已接收 2')).toBeInTheDocument();
    expect(screen.getByText('后台处理中 2')).toBeInTheDocument();
    expect(screen.getByText('已完成 0')).toBeInTheDocument();
    expect(screen.getByText('重复跳过 1')).toBeInTheDocument();
    expect(screen.getByText('已跳过 1')).toBeInTheDocument();
    expect(screen.getByText('失败 0')).toBeInTheDocument();
    expect(screen.getByText('片段数 0')).toBeInTheDocument();
    expect(screen.queryByText('成功 2')).not.toBeInTheDocument();
  });
});
