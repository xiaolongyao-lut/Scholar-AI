import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WritingProvider } from '@/contexts/WritingContext';
import {
  controlAcquisitionDownload,
  getAcquisitionImportReceipt,
  getAcquisitionStatus,
  importAcquisitionArtifact,
  queueAcquisitionDownload,
  resolveAcquisitionGate,
  runAcquisitionDownload,
  searchAcquisition,
  type AccessEvidence,
  type AcquisitionStatus,
  type CandidateManifest,
  type DownloadJob,
  type HumanAccessGate,
  type ImportPublicationEvidence,
  type ImportReceipt,
  type SearchRun,
  type SourcePolicy,
} from '@/services/acquisitionApi';
import { getWritingBackendService } from '@/services/writingBackend';

import { LiteratureAcquisition } from './LiteratureAcquisition';

vi.mock('@/services/acquisitionApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/acquisitionApi')>();
  return {
    ...actual,
    controlAcquisitionDownload: vi.fn(),
    getAcquisitionImportReceipt: vi.fn(),
    getAcquisitionStatus: vi.fn(),
    importAcquisitionArtifact: vi.fn(),
    queueAcquisitionDownload: vi.fn(),
    resolveAcquisitionGate: vi.fn(),
    runAcquisitionDownload: vi.fn(),
    searchAcquisition: vi.fn(),
  };
});

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: vi.fn(),
}));

const mockedGetStatus = vi.mocked(getAcquisitionStatus);
const mockedSearch = vi.mocked(searchAcquisition);
const mockedQueue = vi.mocked(queueAcquisitionDownload);
const mockedRun = vi.mocked(runAcquisitionDownload);
const mockedControl = vi.mocked(controlAcquisitionDownload);
const mockedResolveGate = vi.mocked(resolveAcquisitionGate);
const mockedImport = vi.mocked(importAcquisitionArtifact);
const mockedReceiptRefresh = vi.mocked(getAcquisitionImportReceipt);
const mockedGetWritingBackendService = vi.mocked(getWritingBackendService);

const timestamp = '2026-07-16T08:00:00Z';
const sourceFingerprint = `sha256:${'a'.repeat(64)}`;

const source: SourcePolicy = {
  source_id: 'arxiv',
  capabilities: ['search', 'download'],
  metadata_hosts: ['export.arxiv.org'],
  download_hosts: ['arxiv.org'],
  evidence_kinds: ['official_repository'],
  requires_authentication: false,
  enabled: true,
  min_interval_seconds: 1,
  max_results_per_query: 50,
  terms_url: 'https://info.arxiv.org/help/api/tou.html',
};

const oaEvidence: AccessEvidence = {
  evidence_id: 'evidence-oa',
  candidate_id: 'candidate-1',
  source_platform: 'arxiv',
  kind: 'official_repository',
  access_route: 'open_access',
  pdf_url: 'https://arxiv.org/pdf/1234.5678',
  statement: 'arXiv provides the public full-text record.',
  license: 'CC BY 4.0',
  observed_at: timestamp,
};

const manualEvidence: AccessEvidence = {
  evidence_id: 'evidence-manual',
  candidate_id: 'candidate-1',
  source_platform: 'publisher',
  kind: 'manual_review',
  access_route: 'manual_review',
  pdf_url: 'https://publisher.invalid/article.pdf',
  statement: 'Bearer secret-token at C:\\Users\\example-user\\private.sqlite',
  license: null,
  observed_at: timestamp,
};

const candidate: CandidateManifest = {
  candidate_id: 'candidate-1',
  run_id: 'run-1',
  project_id: 'project-1',
  title: 'Retrieval-Augmented Generation for Research Assistants',
  authors: ['Ada Researcher', 'Lin Scholar'],
  year: 2025,
  published_date: '2025-06-01',
  abstract: 'A local fixture candidate used to exercise acquisition UI states.',
  doi: '10.1000/fixture',
  arxiv_id: '1234.5678',
  source_platforms: ['arxiv', 'crossref'],
  landing_urls: ['https://arxiv.org/abs/1234.5678'],
  pdf_candidates: [
    { pdf_url: oaEvidence.pdf_url, source_platform: 'arxiv', access_evidence: oaEvidence },
    { pdf_url: manualEvidence.pdf_url, source_platform: 'publisher', access_evidence: manualEvidence },
  ],
  merged_from_candidate_ids: ['candidate-crossref-1'],
  created_at: timestamp,
  updated_at: timestamp,
};

const searchRun: SearchRun = {
  run_id: 'run-1',
  query: {
    project_id: 'project-1',
    query: 'retrieval augmented generation',
    sources: ['arxiv'],
    max_results: 20,
    year_from: null,
    year_to: null,
  },
  status: 'completed',
  requested_sources: ['arxiv'],
  attempted_sources: ['arxiv'],
  candidates: [candidate],
  source_errors: [],
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
  completed_at: timestamp,
};

const queuedJob: DownloadJob = {
  job_id: 'job-1',
  project_id: 'project-1',
  candidate_id: 'candidate-1',
  access_evidence_id: 'evidence-oa',
  source_platform: 'arxiv',
  source_url: oaEvidence.pdf_url,
  artifact_path: 'C:\\Users\\example-user\\secret-downloads\\job-1.part',
  status: 'queued',
  attempts: 0,
  bytes_downloaded: 0,
  max_bytes: 50_000_000,
  version: 1,
  error_code: null,
  error_message: null,
  gate_id: null,
  artifact_id: null,
  created_at: timestamp,
  updated_at: timestamp,
  started_at: null,
  completed_at: null,
};

const completedJob: DownloadJob = {
  ...queuedJob,
  status: 'completed',
  attempts: 1,
  bytes_downloaded: 4096,
  artifact_id: 'artifact-1',
  completed_at: timestamp,
};

const projectBJob: DownloadJob = {
  ...queuedJob,
  job_id: 'job-2',
  project_id: 'project-2',
  candidate_id: 'candidate-2',
  access_evidence_id: 'evidence-2',
  source_platform: 'pubmed',
  source_url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
  artifact_path: 'C:\\Users\\example-user\\secret-downloads\\job-2.part',
};

const openGate: HumanAccessGate = {
  gate_id: 'gate-1',
  project_id: 'project-1',
  job_id: 'job-1',
  platform: 'publisher',
  gate_type: 'captcha',
  url: 'https://publisher.invalid/challenge',
  message: 'Authorization Bearer secret-token is required.',
  status: 'open',
  resume_status: 'queued',
  next_action: 'open_source',
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
  resolved_at: null,
};

const publicationEvidence: ImportPublicationEvidence = {
  schema_version: 'scholar-ai-import-publication-evidence/v1',
  verifier_version: 'scholar-ai-material-publication-verifier/v1',
  project_id: 'project-1',
  material_id: 'material-1',
  source_fingerprint: sourceFingerprint,
  source_size_bytes: 4096,
  document_content_sha256: `sha256:${'b'.repeat(64)}`,
  chunk_manifest_version: 2,
  chunk_manifest_sha256: `sha256:${'c'.repeat(64)}`,
  chunk_hash_version: 'scholar-ai-chunk-hash/v1',
  material_chunk_file_sha256: `sha256:${'d'.repeat(64)}`,
  material_chunk_count: 1,
  material_chunk_root_sha256: `sha256:${'e'.repeat(64)}`,
  chunk_store_version: 'f'.repeat(64),
  fts_schema_version: 'scholar-ai-chunk-fts5-index/v1',
  fts_chunk_store_version: 'f'.repeat(64),
  fts_indexed_count: 1,
  fts_skipped_count: 0,
  fts_material_indexed_count: 1,
  revision_fingerprint: `sha256:${'1'.repeat(64)}`,
  revision_receipt_id: 'revision-1',
  revision_applied_at: timestamp,
  verified_at: timestamp,
  evidence_fingerprint: `sha256:${'2'.repeat(64)}`,
};

const importReceipt: ImportReceipt = {
  receipt_id: 'receipt-1',
  artifact_id: 'artifact-1',
  project_id: 'project-1',
  candidate_id: 'candidate-1',
  material_id: 'material-1',
  status: 'completed',
  source_fingerprint: sourceFingerprint,
  receipt_schema_version: 'scholar-ai-import-receipt/v2',
  publication_state: 'verified',
  publication_evidence: publicationEvidence,
  runtime_session_id: 'session-1',
  runtime_job_id: 'runtime-job-1',
  open_url: '/workbench/paper/material-1',
  error_message: null,
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

function statusWith(
  downloadJobs: DownloadJob[] = [],
  gates: HumanAccessGate[] = [],
): AcquisitionStatus {
  return { sources: [source], download_jobs: downloadJobs, gates };
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve: ((value: T) => void) | undefined;
  let reject: ((reason?: unknown) => void) | undefined;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return {
    promise,
    resolve: (value: T): void => {
      if (!resolve) throw new Error('Deferred promise was not initialized');
      resolve(value);
    },
    reject: (reason?: unknown): void => {
      if (!reject) throw new Error('Deferred promise was not initialized');
      reject(reason);
    },
  };
}

interface RenderPageOptions {
  initialEntry?: string;
  strictMode?: boolean;
}

function renderPage({
  initialEntry = '/acquisition?project_id=project-1',
  strictMode = false,
}: RenderPageOptions = {}): void {
  const page = (
    <MemoryRouter initialEntries={[initialEntry]}>
      <WritingProvider>
        <LiteratureAcquisition />
      </WritingProvider>
    </MemoryRouter>
  );
  render(strictMode ? <StrictMode>{page}</StrictMode> : page);
}

describe('LiteratureAcquisition', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockedGetWritingBackendService.mockReturnValue({
      listProjects: vi.fn(async () => [{ project_id: 'project-1', title: '研究项目 A' }]),
    } as unknown as ReturnType<typeof getWritingBackendService>);
    mockedGetStatus.mockResolvedValue(statusWith());
    mockedSearch.mockResolvedValue(searchRun);
    mockedQueue.mockResolvedValue(queuedJob);
    mockedRun.mockResolvedValue(completedJob);
    mockedControl.mockResolvedValue(queuedJob);
    mockedResolveGate.mockResolvedValue({
      gate: { ...openGate, status: 'resolved', resolved_at: timestamp },
      download_job: queuedJob,
    });
    mockedImport.mockResolvedValue(importReceipt);
    mockedReceiptRefresh.mockResolvedValue(importReceipt);
  });

  it('allows only verified OA evidence, then keeps queue, run, and import explicit', async () => {
    renderPage();

    const queryInput = await screen.findByPlaceholderText('标题、主题、作者或 DOI');
    fireEvent.change(queryInput, { target: { value: 'retrieval augmented generation' } });
    const searchButton = screen.getByRole('button', { name: '显式检索' });
    await waitFor(() => expect(searchButton).toBeEnabled());
    fireEvent.click(searchButton);

    expect(await screen.findByText(candidate.title)).toBeInTheDocument();
    const queueButtons = screen.getAllByRole('button', { name: '加入下载队列' });
    expect(queueButtons).toHaveLength(2);
    expect(queueButtons[0]).toBeEnabled();
    expect(queueButtons[1]).toBeDisabled();
    expect(screen.getByText('该下载地址具有可核验的开放获取依据。')).toBeInTheDocument();
    expect(screen.queryByText(/secret-token|private\.sqlite/)).not.toBeInTheDocument();

    fireEvent.click(queueButtons[1]);
    expect(mockedQueue).not.toHaveBeenCalled();

    fireEvent.click(queueButtons[0]);
    await waitFor(() => {
      expect(mockedQueue).toHaveBeenCalledWith('project-1', 'candidate-1', 'evidence-oa');
    });
    expect(mockedRun).not.toHaveBeenCalled();
    expect(await screen.findByText(/下载不会自动开始/)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: '开始' }));
    await waitFor(() => expect(mockedRun).toHaveBeenCalledWith('job-1'));
    expect(mockedImport).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole('button', { name: '导入项目' }));
    await waitFor(() => expect(mockedImport).toHaveBeenCalledWith('artifact-1'));
    expect(await screen.findByText('已导入项目（已核验）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开文献' })).toBeEnabled();
    expect(document.body.textContent).not.toContain('secret-downloads');
  });

  it('does not present a completed legacy receipt as verified or openable', async () => {
    mockedImport.mockResolvedValue({
      ...importReceipt,
      receipt_schema_version: 'scholar-ai-import-receipt/v1',
      publication_state: 'unverified_legacy',
      publication_evidence: null,
    });
    renderPage();

    fireEvent.change(await screen.findByPlaceholderText('标题、主题、作者或 DOI'), {
      target: { value: 'retrieval augmented generation' },
    });
    fireEvent.click(screen.getByRole('button', { name: '显式检索' }));
    fireEvent.click((await screen.findAllByRole('button', { name: '加入下载队列' }))[0]);
    fireEvent.click(await screen.findByRole('button', { name: '开始' }));
    fireEvent.click(await screen.findByRole('button', { name: '导入项目' }));

    expect(await screen.findByText('旧回执未核验')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开文献' })).not.toBeInTheDocument();
    expect(screen.queryByText('已导入项目（已核验）')).not.toBeInTheDocument();
  });

  it.each(['completed', 'duplicate'] as const)('offers publication verification retry for a %s pending receipt', async (receiptStatus) => {
    const pendingReceipt: ImportReceipt = {
      ...importReceipt,
      status: receiptStatus,
      publication_state: 'pending',
      publication_evidence: null,
      error_message: 'Material publication verification is pending',
    };
    mockedImport.mockResolvedValue(pendingReceipt);
    mockedReceiptRefresh.mockResolvedValue({ ...importReceipt, status: receiptStatus });

    renderPage();
    fireEvent.change(await screen.findByPlaceholderText('标题、主题、作者或 DOI'), {
      target: { value: 'retrieval augmented generation' },
    });
    fireEvent.click(screen.getByRole('button', { name: '显式检索' }));
    fireEvent.click((await screen.findAllByRole('button', { name: '加入下载队列' }))[0]);
    fireEvent.click(await screen.findByRole('button', { name: '开始' }));
    fireEvent.click(await screen.findByRole('button', { name: '导入项目' }));

    expect(await screen.findByText('发布校验中')).toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: '刷新发布校验' });
    expect(retryButton).toBeEnabled();
    fireEvent.click(retryButton);

    await waitFor(() => expect(mockedReceiptRefresh).toHaveBeenCalledWith('receipt-1'));
    expect(await screen.findByRole('button', { name: '打开文献' })).toBeEnabled();
  });

  it('resolves a human gate only after confirmation and never starts the download automatically', async () => {
    const humanRequiredJob: DownloadJob = {
      ...queuedJob,
      status: 'human_required',
      gate_id: 'gate-1',
      error_message: 'Bearer secret-token at C:\\private\\runtime.sqlite',
    };
    mockedGetStatus.mockResolvedValue(statusWith([humanRequiredJob], [openGate]));

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '处理' }));
    const confirmButton = screen.getByRole('button', { name: '确认完成并恢复到队列' });
    expect(confirmButton).toBeDisabled();
    expect(screen.queryByText(/secret-token|runtime\.sqlite/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: /我确认已在来源页面完成必要步骤/ }));
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() => expect(mockedResolveGate).toHaveBeenCalledWith('gate-1'));
    expect(mockedRun).not.toHaveBeenCalled();
    expect(await screen.findByText(/任务已回到等待状态，不会自动继续下载/)).toBeInTheDocument();
  });

  it('requeues a paused job through the control endpoint without hidden execution', async () => {
    const pausedJob: DownloadJob = { ...queuedJob, status: 'paused', bytes_downloaded: 1024 };
    mockedGetStatus.mockResolvedValue(statusWith([pausedJob]));
    mockedControl.mockResolvedValue({ ...pausedJob, status: 'queued' });

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '恢复到队列' }));

    await waitFor(() => expect(mockedControl).toHaveBeenCalledWith('job-1', 'resume'));
    expect(mockedRun).not.toHaveBeenCalled();
    expect(await screen.findByText(/仍需显式点击“开始”/)).toBeInTheDocument();
  });

  it('exposes a retry control for cancelled cleanup failures without starting a download', async () => {
    const cleanupFailedJob: DownloadJob = {
      ...queuedJob,
      status: 'cancelled',
      error_code: 'cancel_cleanup_failed',
      error_message: 'Download partial cleanup failed at C:\\private\\runtime.sqlite',
    };
    mockedGetStatus.mockResolvedValue(statusWith([cleanupFailedJob]));
    mockedControl.mockResolvedValue({
      ...cleanupFailedJob,
      error_code: null,
      error_message: null,
      updated_at: '2026-07-16T08:01:00Z',
    });

    renderPage();

    expect(await screen.findByText(/取消后的本地文件清理未完成/)).toBeInTheDocument();
    expect(screen.queryByText(/private\\runtime\.sqlite/)).not.toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: '重试清理' });
    expect(retryButton).toBeEnabled();
    fireEvent.click(retryButton);

    await waitFor(() => expect(mockedControl).toHaveBeenCalledWith('job-1', 'cancel'));
    expect(mockedRun).not.toHaveBeenCalled();
    expect(await screen.findByText('取消后的本地文件清理已重试。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重试清理' })).not.toBeInTheDocument();
  });

  it.each([
    {
      action: 'start',
      job: queuedJob,
      buttonName: '开始',
      assertNotCalled: (): void => expect(mockedRun).not.toHaveBeenCalled(),
    },
    {
      action: 'cancel',
      job: queuedJob,
      buttonName: '取消下载',
      assertNotCalled: (): void => expect(mockedControl).not.toHaveBeenCalled(),
    },
    {
      action: 'import',
      job: completedJob,
      buttonName: '导入项目',
      assertNotCalled: (): void => expect(mockedImport).not.toHaveBeenCalled(),
    },
  ])('clears project A immediately and rejects its stale $action action', async ({
    job,
    buttonName,
    assertNotCalled,
  }) => {
    const projectBStatus = deferred<AcquisitionStatus>();
    mockedGetWritingBackendService.mockReturnValue({
      listProjects: vi.fn(async () => [
        { project_id: 'project-1', title: '研究项目 A' },
        { project_id: 'project-2', title: '研究项目 B' },
      ]),
    } as unknown as ReturnType<typeof getWritingBackendService>);
    mockedGetStatus.mockImplementation((projectId) => (
      projectId === 'project-2' ? projectBStatus.promise : Promise.resolve(statusWith([job]))
    ));

    renderPage();
    expect(await screen.findByRole('button', { name: buttonName })).toBeEnabled();

    fireEvent.change(screen.getByRole('combobox', { name: '选择项目' }), {
      target: { value: 'project-2' },
    });

    const staleAction = screen.queryByRole('button', { name: buttonName });
    if (staleAction) fireEvent.click(staleAction);
    assertNotCalled();
    expect(screen.queryByText('arXiv 下载任务')).not.toBeInTheDocument();
  });

  it('keeps project B status when a project A refresh resolves late', async () => {
    const lateProjectAStatus = deferred<AcquisitionStatus>();
    let projectARequests = 0;
    mockedGetWritingBackendService.mockReturnValue({
      listProjects: vi.fn(async () => [
        { project_id: 'project-1', title: '研究项目 A' },
        { project_id: 'project-2', title: '研究项目 B' },
      ]),
    } as unknown as ReturnType<typeof getWritingBackendService>);
    mockedGetStatus.mockImplementation((projectId) => {
      if (projectId === 'project-2') return Promise.resolve(statusWith([projectBJob]));
      projectARequests += 1;
      return projectARequests === 1
        ? Promise.resolve(statusWith([queuedJob]))
        : lateProjectAStatus.promise;
    });

    renderPage();
    expect(await screen.findByText('arXiv 下载任务')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(projectARequests).toBe(2));

    fireEvent.change(screen.getByRole('combobox', { name: '选择项目' }), {
      target: { value: 'project-2' },
    });
    expect(await screen.findByText('PubMed 下载任务')).toBeInTheDocument();

    await act(async () => {
      lateProjectAStatus.resolve(statusWith([queuedJob]));
      await lateProjectAStatus.promise;
    });

    expect(screen.getByText('PubMed 下载任务')).toBeInTheDocument();
    expect(screen.queryByText('arXiv 下载任务')).not.toBeInTheDocument();
  });

  it.each([
    {
      outcome: 'success',
      settle: (request: Deferred<Array<{ project_id: string; title: string }>>): void => {
        request.resolve([{ project_id: 'project-1', title: '旧项目列表' }]);
      },
    },
    {
      outcome: 'failure',
      settle: (request: Deferred<Array<{ project_id: string; title: string }>>): void => {
        request.reject(new Error('stale project load failed'));
      },
    },
  ])('ignores a stale project-list $outcome under StrictMode after a user selects project B', async ({ settle }) => {
    const staleProjects = deferred<Array<{ project_id: string; title: string }>>();
    const currentProjects = [
      { project_id: 'project-1', title: '研究项目 A' },
      { project_id: 'project-2', title: '研究项目 B' },
    ];
    const listProjects = vi.fn(() => Promise.resolve(currentProjects));
    listProjects.mockImplementationOnce(() => staleProjects.promise);
    mockedGetWritingBackendService.mockReturnValue({
      listProjects,
    } as unknown as ReturnType<typeof getWritingBackendService>);
    mockedGetStatus.mockImplementation((projectId) => Promise.resolve(
      projectId === 'project-2' ? statusWith([projectBJob]) : statusWith([queuedJob]),
    ));

    renderPage({ initialEntry: '/acquisition', strictMode: true });

    await waitFor(() => expect(listProjects.mock.calls.length).toBeGreaterThanOrEqual(2));
    const projectSelect = await screen.findByRole('combobox', { name: '选择项目' });
    await waitFor(() => expect(projectSelect).toHaveValue('project-1'));
    fireEvent.change(projectSelect, { target: { value: 'project-2' } });
    expect(await screen.findByText('PubMed 下载任务')).toBeInTheDocument();

    await act(async () => {
      settle(staleProjects);
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByRole('combobox', { name: '选择项目' })).toHaveValue('project-2'));
    expect(screen.getByText('PubMed 下载任务')).toBeInTheDocument();
    expect(screen.queryByText('arXiv 下载任务')).not.toBeInTheDocument();
  });

  it('keeps a queued job when an older status refresh resolves after queue mutation', async () => {
    const staleStatus = deferred<AcquisitionStatus>();
    renderPage();

    fireEvent.change(await screen.findByPlaceholderText('标题、主题、作者或 DOI'), {
      target: { value: 'retrieval augmented generation' },
    });
    fireEvent.click(screen.getByRole('button', { name: '显式检索' }));
    const queueButton = (await screen.findAllByRole('button', { name: '加入下载队列' }))[0];
    mockedGetStatus.mockImplementationOnce(() => staleStatus.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(mockedGetStatus).toHaveBeenCalledTimes(2));

    fireEvent.click(queueButton);
    expect(await screen.findByRole('button', { name: '开始' })).toBeEnabled();

    await act(async () => {
      staleStatus.resolve(statusWith());
      await staleStatus.promise;
    });

    expect(screen.getByRole('button', { name: '开始' })).toBeEnabled();
  });

  it('keeps a completed job when an older status refresh resolves after run mutation', async () => {
    const staleStatus = deferred<AcquisitionStatus>();
    mockedGetStatus.mockResolvedValue(statusWith([queuedJob]));
    renderPage();

    const runButton = await screen.findByRole('button', { name: '开始' });
    mockedGetStatus.mockImplementationOnce(() => staleStatus.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(mockedGetStatus).toHaveBeenCalledTimes(2));

    fireEvent.click(runButton);
    expect(await screen.findByRole('button', { name: '导入项目' })).toBeEnabled();

    await act(async () => {
      staleStatus.resolve(statusWith([queuedJob]));
      await staleStatus.promise;
    });

    expect(screen.getByRole('button', { name: '导入项目' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '开始' })).not.toBeInTheDocument();
  });

  it('keeps a resumed job when an older status refresh resolves after control mutation', async () => {
    const pausedJob: DownloadJob = { ...queuedJob, status: 'paused', bytes_downloaded: 1024 };
    const staleStatus = deferred<AcquisitionStatus>();
    mockedGetStatus.mockResolvedValue(statusWith([pausedJob]));
    mockedControl.mockResolvedValue({ ...pausedJob, status: 'queued' });
    renderPage();

    const resumeButton = await screen.findByRole('button', { name: '恢复到队列' });
    mockedGetStatus.mockImplementationOnce(() => staleStatus.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(mockedGetStatus).toHaveBeenCalledTimes(2));

    fireEvent.click(resumeButton);
    expect(await screen.findByText(/仍需显式点击“开始”/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '恢复到队列' })).not.toBeInTheDocument();

    await act(async () => {
      staleStatus.resolve(statusWith([pausedJob]));
      await staleStatus.promise;
    });

    expect(screen.queryByRole('button', { name: '恢复到队列' })).not.toBeInTheDocument();
  });

  it('keeps a resolved gate when an older status refresh resolves after gate mutation', async () => {
    const humanRequiredJob: DownloadJob = {
      ...queuedJob,
      status: 'human_required',
      gate_id: 'gate-1',
    };
    const staleStatus = deferred<AcquisitionStatus>();
    mockedGetStatus.mockResolvedValue(statusWith([humanRequiredJob], [openGate]));
    renderPage();

    const handleGateButton = await screen.findByRole('button', { name: '处理' });
    mockedGetStatus.mockImplementationOnce(() => staleStatus.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(mockedGetStatus).toHaveBeenCalledTimes(2));

    fireEvent.click(handleGateButton);
    fireEvent.click(screen.getByRole('checkbox', { name: /我确认已在来源页面完成必要步骤/ }));
    fireEvent.click(screen.getByRole('button', { name: '确认完成并恢复到队列' }));
    expect(await screen.findByText(/任务已回到等待状态，不会自动继续下载/)).toBeInTheDocument();

    await act(async () => {
      staleStatus.resolve(statusWith([humanRequiredJob], [openGate]));
      await staleStatus.promise;
    });

    expect(screen.queryByRole('button', { name: '处理' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始' })).toBeEnabled();
  });
});
