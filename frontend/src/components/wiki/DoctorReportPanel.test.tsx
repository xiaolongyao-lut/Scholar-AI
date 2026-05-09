import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { WikiDoctorModel } from '@/types/wiki';

import { DoctorReportPanel } from './DoctorReportPanel';

const doctor: WikiDoctorModel = {
  enabled: true,
  report: {},
  warnings: ['graph index 需要重建'],
  structuredReport: {
    ok: false,
    status: 'warning',
    counts: {
      pages: 12,
      checks: 2,
    },
    checks: [
      {
        id: 'graph',
        label: 'Graph index',
        status: 'warning',
        summary: 'graph.json 与页面数量不一致。',
        detail: 'expected 12 nodes, found 10 nodes',
        metrics: { expected_nodes: 12, actual_nodes: 10 },
        actions: [
          {
            command: 'wiki doctor --repair graph',
            description: '重建 graph JSON/SQLite。',
            safe_auto_repair: true,
          },
          {
            command: 'wiki compile --save',
            description: '需要人工确认后才可写入页面。',
            safe_auto_repair: false,
          },
        ],
      },
    ],
  },
};

describe('DoctorReportPanel', () => {
  it('renders warnings, structured checks, metrics, and safe/manual action hints', () => {
    const onRefresh = vi.fn();
    render(<DoctorReportPanel doctor={doctor} isLoading={false} error={null} onRefresh={onRefresh} />);

    expect(screen.getByRole('heading', { name: '健康诊断只读面' })).toBeInTheDocument();
    expect(screen.getByText('graph index 需要重建')).toBeInTheDocument();
    expect(screen.getByText('overall')).toBeInTheDocument();
    expect(screen.getByText('Graph index')).toBeInTheDocument();
    expect(screen.getByText('expected 12 nodes, found 10 nodes')).toBeInTheDocument();
    expect(screen.getByText('expected_nodes')).toBeInTheDocument();
    expect(screen.getByText('wiki doctor --repair graph')).toBeInTheDocument();
    expect(screen.getByText('safe auto repair')).toBeInTheDocument();
    expect(screen.getByText('manual only')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /刷新 doctor/i }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
