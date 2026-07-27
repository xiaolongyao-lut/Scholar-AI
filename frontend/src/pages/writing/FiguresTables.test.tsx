import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FiguresTables } from './FiguresTables';
import { getWritingBackendService } from '@/services/writingBackend';
import type { CreateFigureAssetRequest } from '@/types/resources';

vi.mock('@/contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string, values?: Record<string, number>) => {
      if (key === 'writing.figures.title') return '图表';
      if (key === 'writing.figures.subtitle') {
        return `图 ${values?.figures ?? 0} · 表 ${values?.tables ?? 0}`;
      }
      return key;
    },
  }),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: () => ({ activeProjectId: 'project-h9' }),
}));

vi.mock('@/services/backgroundJobRunner', () => ({
  startBackgroundJob: vi.fn(async () => ({
    job: {
      job_id: 'job-h9-load',
      kind: 'figure_load',
      status: 'completed',
      metadata: {
        project_id: 'project-h9',
        figure_loader_version: 3,
      },
    },
  })),
  findLatestArtifact: vi.fn((artifacts: unknown[]) => artifacts[0] ?? null),
  artifactContentRecord: vi.fn(() => ({
    figure_loader_version: 3,
    assets: [],
    candidates: [
      {
        id: 'candidate-pdf-points',
        kind: 'figure',
        label: '图 2',
        caption: '图 2：显微组织区域',
        material_id: 'material-h9',
        material_title: '显微组织研究.pdf',
        page: 5,
        chunk_id: 'chunk-pdf-points',
        chunk_index: 4,
        bbox: [12, 24, 120, 80],
        bbox_unit: 'pdf_points',
        asset_path: 'figures/candidate-pdf-points.png',
        source: 'chunk_image',
      },
      {
        id: 'candidate-legacy-unitless',
        kind: 'figure',
        label: '图 3',
        caption: '图 3：旧缓存无单位区域',
        material_id: 'material-h9',
        material_title: '显微组织研究.pdf',
        page: 6,
        chunk_id: 'chunk-legacy-unitless',
        chunk_index: 5,
        bbox: [0.1, 0.2, 0.3, 0.4],
        asset_path: 'figures/candidate-legacy-unitless.png',
        source: 'chunk_image',
      },
    ],
  })),
}));

vi.mock('@/services/runtimeClient', () => ({
  getWritingRuntimeClient: () => ({
    listJobs: vi.fn(async () => []),
    getJobStatus: vi.fn(async () => ({
      job_id: 'job-h9-load',
      status: 'completed',
      metadata: { figure_loader_version: 3 },
    })),
    getJobArtifacts: vi.fn(async () => [{ artifact_id: 'artifact-h9' }]),
  }),
}));

vi.mock('@/services/writingBackend', () => ({
  buildFigureAssetFileUrl: (projectId: string, assetPath: string) => `/api/writing/figures/file?project_id=${projectId}&path=${assetPath}`,
  getWritingBackendService: vi.fn(),
}));

const mockedGetWritingBackendService = vi.mocked(getWritingBackendService);
const createFigureAsset = vi.fn(async (request: CreateFigureAssetRequest) => ({
  asset_id: 'fig_h9_registered',
  project_id: request.project_id,
  kind: request.kind,
  caption: request.caption,
  numbering: request.numbering,
  material_id: request.material_id ?? null,
  source_page: request.source_page ?? null,
  bbox: request.bbox ?? null,
  bbox_unit: request.bbox_unit ?? null,
  asset_path: request.asset_path,
  width: request.width ?? null,
  height: request.height ?? null,
  format: request.format ?? null,
  created_at: '2026-06-05T00:00:00Z',
  updated_at: '2026-06-05T00:00:00Z',
}));
const generateFigureAssets = vi.fn(async () => ({
  project_id: 'project-h9',
  generated_count: 1,
  generated_assets: [
    {
      asset_id: 'fig_h9_generated',
      project_id: 'project-h9',
      kind: 'figure',
      caption: '图 1：本地生成的像素图',
      numbering: '图 1',
      material_id: 'material-h9',
      source_page: 2,
      bbox: [0.1, 0.2, 0.3, 0.4],
      asset_path: 'figures/h9-generated.png',
      width: null,
      height: null,
      format: 'png',
      created_at: '2026-06-05T00:00:00Z',
      updated_at: '2026-06-05T00:00:00Z',
    },
  ],
  skipped_candidate_ids: [],
  message: 'ok',
}));

describe('FiguresTables', () => {
  beforeEach(() => {
    generateFigureAssets.mockClear();
    createFigureAsset.mockClear();
    mockedGetWritingBackendService.mockReturnValue({
      generateFigureAssets,
      createFigureAsset,
      updateFigureAsset: vi.fn(),
      deleteFigureAsset: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);
  });

  it('generates local figure assets from the toolbar action', async () => {
    render(<FiguresTables />);

    const generateButton = await screen.findByRole('button', { name: '生成' });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(generateFigureAssets).toHaveBeenCalledWith({
        project_id: 'project-h9',
        max_items: 6,
      });
    });
    expect(await screen.findByText('图 1：本地生成的像素图')).toBeInTheDocument();
  });

  it('keeps the candidate bbox unit when registering an asset', async () => {
    render(<FiguresTables />);

    const saveButtons = await screen.findAllByRole('button', { name: '保存到图表库' });
    const enabledSaveButton = saveButtons.find((button) => !button.hasAttribute('disabled'));
    expect(enabledSaveButton).toBeDefined();
    fireEvent.click(enabledSaveButton as HTMLButtonElement);

    await waitFor(() => {
      expect(createFigureAsset).toHaveBeenCalledWith(expect.objectContaining({
        bbox: [12, 24, 120, 80],
        bbox_unit: 'pdf_points',
      }));
    });
  });

  it('omits both bbox fields when a legacy candidate has no unit', async () => {
    render(<FiguresTables />);

    const saveButtons = await screen.findAllByRole('button', { name: '保存到图表库' });
    const enabledSaveButtons = saveButtons.filter((button) => !button.hasAttribute('disabled'));
    expect(enabledSaveButtons).toHaveLength(2);
    fireEvent.click(enabledSaveButtons[1]);

    await waitFor(() => expect(createFigureAsset).toHaveBeenCalledTimes(1));
    const request = createFigureAsset.mock.calls[0]?.[0];
    expect(request).not.toHaveProperty('bbox');
    expect(request).not.toHaveProperty('bbox_unit');
  });
});
