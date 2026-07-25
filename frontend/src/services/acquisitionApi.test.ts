import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acquisitionErrorMessage,
  controlAcquisitionDownload,
  getAcquisitionImportReceipt,
  getAcquisitionStatus,
  importAcquisitionArtifact,
  parseImportReceipt,
  queueAcquisitionDownload,
  resolveAcquisitionGate,
  runAcquisitionDownload,
  searchAcquisition,
  type DownloadJob,
  type HumanAccessGate,
  type ImportPublicationEvidence,
  type ImportReceipt,
  type SearchRun,
} from './acquisitionApi';

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    isAxiosError: vi.fn(),
  },
}));

const mockedGet = vi.mocked(axios.get);
const mockedPost = vi.mocked(axios.post);
const mockedIsAxiosError = vi.mocked(axios.isAxiosError);
const timestamp = '2026-07-16T08:00:00Z';
const sourceFingerprint = `sha256:${'a'.repeat(64)}`;

const searchRun: SearchRun = {
  run_id: 'run-1',
  query: {
    project_id: 'project-1',
    query: 'retrieval augmented generation',
    sources: ['arxiv'],
    max_results: 20,
    year_from: 2020,
    year_to: 2026,
  },
  status: 'completed',
  requested_sources: ['arxiv'],
  attempted_sources: ['arxiv'],
  candidates: [],
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
  access_evidence_id: 'evidence-1',
  source_platform: 'arxiv',
  source_url: 'https://arxiv.org/pdf/1234.5678',
  artifact_path: 'workspace_artifacts/runtime_state/acquisition/job-1.part',
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

const openGate: HumanAccessGate = {
  gate_id: 'gate-1',
  project_id: 'project-1',
  job_id: 'job-1',
  platform: 'arxiv',
  gate_type: 'captcha',
  url: 'https://arxiv.org/',
  message: 'Complete the source challenge.',
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

describe('acquisitionApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedIsAxiosError.mockReturnValue(false);
  });

  it('normalizes a search request and parses the shared search-run contract', async () => {
    mockedPost.mockResolvedValueOnce({ data: searchRun });

    const result = await searchAcquisition({
      projectId: ' project-1 ',
      query: ' retrieval augmented generation ',
      sources: ['arxiv', ' arxiv ', ''],
      maxResults: 20,
      yearFrom: 2020,
      yearTo: 2026,
    });

    expect(result).toEqual(searchRun);
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/acquisition/search',
      {
        project_id: 'project-1',
        query: 'retrieval augmented generation',
        sources: ['arxiv'],
        max_results: 20,
        year_from: 2020,
        year_to: 2026,
      },
    );
  });

  it('rejects invalid search and status bounds before issuing HTTP requests', async () => {
    await expect(searchAcquisition({
      projectId: 'project-1',
      query: 'query',
      sources: [],
    })).rejects.toMatchObject({ code: 'invalid_request' });
    await expect(searchAcquisition({
      projectId: 'project-1',
      query: 'query',
      sources: ['arxiv'],
      yearFrom: 2026,
      yearTo: 2020,
    })).rejects.toMatchObject({ code: 'invalid_request' });
    await expect(getAcquisitionStatus('project-1', 501)).rejects.toMatchObject({ code: 'invalid_request' });

    expect(mockedGet).not.toHaveBeenCalled();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it('uses distinct queue, run, control, gate, import, and receipt endpoints', async () => {
    mockedPost
      .mockResolvedValueOnce({ data: queuedJob })
      .mockResolvedValueOnce({ data: { ...queuedJob, status: 'running', attempts: 1 } })
      .mockResolvedValueOnce({ data: { ...queuedJob, status: 'paused' } })
      .mockResolvedValueOnce({
        data: {
          gate: { ...openGate, status: 'resolved', resolved_at: timestamp },
          download_job: queuedJob,
        },
      })
      .mockResolvedValueOnce({ data: importReceipt });
    mockedGet.mockResolvedValueOnce({ data: importReceipt });

    await queueAcquisitionDownload('project-1', 'candidate-1', 'evidence-1');
    await runAcquisitionDownload('job/1');
    await controlAcquisitionDownload('job-1', 'pause');
    const resolution = await resolveAcquisitionGate('gate/1');
    const imported = await importAcquisitionArtifact('artifact/1');
    const refreshed = await getAcquisitionImportReceipt('receipt/1');

    expect(mockedPost.mock.calls).toEqual([
      [
        '/api/acquisition/downloads',
        {
          project_id: 'project-1',
          candidate_id: 'candidate-1',
          access_evidence_id: 'evidence-1',
        },
      ],
      ['/api/acquisition/downloads/job%2F1/run'],
      ['/api/acquisition/downloads/job-1/control', { action: 'pause' }],
      ['/api/acquisition/gates/gate%2F1/resolve'],
      ['/api/acquisition/artifacts/artifact%2F1/import'],
    ]);
    expect(mockedGet).toHaveBeenCalledWith(
      '/api/acquisition/receipts/receipt%2F1',
    );
    expect(resolution.download_job?.status).toBe('queued');
    expect(resolution.gate.status).toBe('resolved');
    expect(imported).toEqual(importReceipt);
    expect(refreshed).toEqual(importReceipt);
  });

  it('preserves publication proof and rejects impossible receipt state combinations', () => {
    expect(parseImportReceipt(importReceipt)).toEqual(importReceipt);

    const publicationPending = parseImportReceipt({
      ...importReceipt,
      publication_state: 'pending',
      publication_evidence: null,
      error_message: 'Material publication verification is pending',
    });
    expect(publicationPending.status).toBe('completed');
    expect(publicationPending.publication_state).toBe('pending');
    expect(publicationPending.publication_evidence).toBeNull();

    const legacy = parseImportReceipt({
      ...importReceipt,
      receipt_schema_version: 'scholar-ai-import-receipt/v1',
      publication_state: 'unverified_legacy',
      publication_evidence: null,
    });
    expect(legacy.publication_state).toBe('unverified_legacy');
    expect(legacy.publication_evidence).toBeNull();

    expect(() => parseImportReceipt({
      ...importReceipt,
      publication_evidence: null,
    })).toThrow(/mismatched publication evidence/);
    expect(() => parseImportReceipt({
      ...importReceipt,
      publication_evidence: { ...publicationEvidence, project_id: 'project-other' },
    })).toThrow(/mismatched publication evidence/);
    expect(() => parseImportReceipt({
      ...importReceipt,
      status: 'failed',
      publication_state: 'pending',
      publication_evidence: null,
    })).toThrow(/status does not match publication state/);
  });

  it('does not surface secrets, URLs, or local paths from backend errors', async () => {
    mockedIsAxiosError.mockReturnValue(true);
    mockedPost.mockRejectedValueOnce({
      response: {
        status: 500,
        data: {
          detail: {
            code: 'internal_failure',
            message: 'Bearer secret-token at C:\\Users\\xiao\\private.sqlite https://internal.invalid',
          },
        },
      },
    });

    let caught: unknown;
    try {
      await queueAcquisitionDownload('project-1', 'candidate-1', 'evidence-1');
    } catch (error: unknown) {
      caught = error;
    }

    const message = acquisitionErrorMessage(caught);
    expect(message).toBe('下载任务创建失败。');
    expect(message).not.toMatch(/Bearer|secret-token|private\.sqlite|internal\.invalid/);
  });
});
