import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type {
  ArtifactType,
  CreateJobRequest,
  JobStatusDetail,
  WritingArtifact,
  WritingJob,
  WritingSession,
} from '@/types/runtime';

const DEFAULT_POLL_INTERVAL_MS = 1200;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

interface EnsureSessionOptions {
  title: string;
  metadata?: Record<string, unknown>;
}

interface RunBackgroundJobOptions {
  request: Omit<CreateJobRequest, 'session_id'> & {
    session_id?: string;
  };
  sessionTitle: string;
  sessionMetadata?: Record<string, unknown>;
  pollIntervalMs?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
  onJobCreated?: (job: WritingJob, session: WritingSession) => void;
}

interface RunBackgroundJobResult {
  session: WritingSession;
  job: WritingJob;
  status: JobStatusDetail;
  artifacts: WritingArtifact[];
}

interface StartBackgroundJobOptions {
  request: Omit<CreateJobRequest, 'session_id'> & {
    session_id?: string;
  };
  sessionTitle: string;
  sessionMetadata?: Record<string, unknown>;
  onJobCreated?: (job: WritingJob, session: WritingSession) => void;
}

function now(): number {
  return Date.now();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isTerminal(status: string | null | undefined): boolean {
  return TERMINAL_STATUSES.has(String(status ?? ''));
}

export async function ensureBackgroundRuntimeSession({
  title,
  metadata = {},
}: EnsureSessionOptions): Promise<WritingSession> {
  const client = getWritingRuntimeClient();
  return client.createSession({
    mode: 'prompt',
    title,
    metadata: {
      source: 'background_job',
      ...metadata,
    },
  });
}

export async function waitForRuntimeJobTerminalState(
  jobId: string,
  options: {
    pollIntervalMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<JobStatusDetail> {
  const client = getWritingRuntimeClient();
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const startedAt = now();

  if (options.signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }

  const abortError = () => new DOMException('Aborted', 'AbortError');

  while (now() - startedAt <= timeoutMs) {
    if (options.signal?.aborted) {
      await client.cancelJob(jobId).catch(() => undefined);
      throw abortError();
    }
    const status = await client.getJobStatus(jobId);
    if (isTerminal(status.status)) {
      return status;
    }
    await Promise.race([
      sleep(pollIntervalMs),
      new Promise<void>((_, reject) => {
        const onAbort = () => {
          options.signal?.removeEventListener('abort', onAbort);
          reject(abortError());
        };
        options.signal?.addEventListener('abort', onAbort, { once: true });
      }),
    ]).catch(async (error) => {
      if (error instanceof DOMException && error.name === 'AbortError') {
        await client.cancelJob(jobId).catch(() => undefined);
      }
      throw error;
    });
  }

  throw new Error('后台任务仍在运行，请在任务中心查看进度。');
}

export async function runBackgroundJob({
  request,
  sessionTitle,
  sessionMetadata,
  pollIntervalMs,
  timeoutMs,
  signal,
  onJobCreated,
}: RunBackgroundJobOptions): Promise<RunBackgroundJobResult> {
  const client = getWritingRuntimeClient();
  const session = request.session_id
    ? await client.getSession(request.session_id).catch(() => ensureBackgroundRuntimeSession({
        title: sessionTitle,
        metadata: {
          ...sessionMetadata,
          recovered_from_missing_session_id: request.session_id,
        },
      }))
    : await ensureBackgroundRuntimeSession({
        title: sessionTitle,
        metadata: sessionMetadata,
      });
  const job = await client.createJob({
    ...request,
    session_id: session.session_id,
  });
  onJobCreated?.(job, session);
  await client.startJob(job.job_id);
  const status = await waitForRuntimeJobTerminalState(job.job_id, {
    pollIntervalMs,
    timeoutMs,
    signal,
  });
  const artifacts = await client.getJobArtifacts(job.job_id);
  return { session, job, status, artifacts };
}

export async function startBackgroundJob({
  request,
  sessionTitle,
  sessionMetadata,
  onJobCreated,
}: StartBackgroundJobOptions): Promise<{ session: WritingSession; job: WritingJob }> {
  const client = getWritingRuntimeClient();
  const session = request.session_id
    ? await client.getSession(request.session_id).catch(() => ensureBackgroundRuntimeSession({
        title: sessionTitle,
        metadata: {
          ...sessionMetadata,
          recovered_from_missing_session_id: request.session_id,
        },
      }))
    : await ensureBackgroundRuntimeSession({
        title: sessionTitle,
        metadata: sessionMetadata,
      });
  const job = await client.createJob({
    ...request,
    session_id: session.session_id,
  });
  onJobCreated?.(job, session);
  await client.startJob(job.job_id);
  return { session, job };
}

export function findLatestArtifact(
  artifacts: WritingArtifact[],
  type?: ArtifactType,
): WritingArtifact | null {
  const filtered = type
    ? artifacts.filter((artifact) => artifact.artifact_type === type)
    : artifacts;
  if (filtered.length === 0) return null;
  return [...filtered].sort((left, right) => (
    String(right.created_at).localeCompare(String(left.created_at))
  ))[0] ?? null;
}

export function artifactContentRecord(artifact: WritingArtifact | null): Record<string, unknown> {
  if (!artifact || typeof artifact.content !== 'object' || artifact.content === null || Array.isArray(artifact.content)) {
    return {};
  }
  return artifact.content as Record<string, unknown>;
}
