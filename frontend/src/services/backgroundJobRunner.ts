import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type {
  ArtifactType,
  CreateJobRequest,
  JobStatusDetail,
  WritingArtifact,
  WritingEvent,
  WritingJob,
  WritingSession,
} from '@/types/runtime';

const DEFAULT_POLL_INTERVAL_MS = 1200;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

/**
 * Sanitize a free-form backend event payload field into a short, single-line
 * UI string. Backend writes structured payloads but the progress callback only
 * needs a one-liner; everything else is dropped to keep the message bubble
 * stable. Never echoes raw JSON or stack traces.
 */
function eventPayloadToProgressText(event: WritingEvent): string | null {
  const payload = (event.data ?? {}) as Record<string, unknown>;
  const candidates = [
    payload.phase_label,
    payload.label,
    payload.message,
    payload.stage,
    payload.phase,
    payload.detail,
    payload.description,
  ];
  for (const cand of candidates) {
    if (typeof cand === 'string' && cand.trim()) {
      return cand.trim().slice(0, 120);
    }
  }
  // Fallback to event_type — readable for debug but better than nothing.
  if (typeof event.event_type === 'string' && event.event_type) {
    return event.event_type;
  }
  return null;
}

export interface JobProgressTick {
  /** Job's current top-level state — `running` / `paused` / etc. */
  status: string;
  /** One-liner derived from the latest non-terminal event for the UI bubble. */
  label: string | null;
  /** Server-side progress percentage if backend included it, else null. */
  percent: number | null;
  /** Latest event seen this tick (caller may inspect for richer UI). */
  latestEvent: WritingEvent | null;
}

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
  /**
   * B12 (2026-06-13): Fires every poll tick with the latest job phase/label so
   * the chat bubble can render "AI 正在做：[阶段名]" instead of stale
   * "AI 思考中" while a 2-minute RAG job runs. Backend already emits
   * JOB_PROGRESS / JOB_PHASE — this just surfaces them.
   */
  onProgress?: (tick: JobProgressTick) => void;
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
    onProgress?: (tick: JobProgressTick) => void;
  } = {},
): Promise<JobStatusDetail> {
  const client = getWritingRuntimeClient();
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const onProgress = options.onProgress;
  const startedAt = now();

  if (options.signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }

  const abortError = () => new DOMException('Aborted', 'AbortError');
  // Sequence cursor for incremental events — backend supports after_sequence so
  // we only get NEW events on each tick. Avoids re-emitting the same phase
  // label to onProgress on every poll.
  let afterSequence: number | undefined;
  let lastLabel: string | null = null;

  while (now() - startedAt <= timeoutMs) {
    if (options.signal?.aborted) {
      await client.cancelJob(jobId).catch(() => undefined);
      throw abortError();
    }
    // B12: use snapshot to fetch status + incremental events in ONE round-trip
    // instead of polling /status alone. Falls back to /status if snapshot fails.
    let status: JobStatusDetail;
    let latestEvent: WritingEvent | null = null;
    let labelForTick: string | null = lastLabel;
    let percentForTick: number | null = null;
    try {
      const snapshot = await client.getJobEventSnapshot(jobId, {
        afterSequence,
      });
      status = snapshot.status;
      const events = Array.isArray(snapshot.events) ? snapshot.events : [];
      if (events.length > 0) {
        latestEvent = events[events.length - 1];
        const newLabel = eventPayloadToProgressText(latestEvent);
        if (newLabel) {
          labelForTick = newLabel;
          lastLabel = newLabel;
        }
        const rawPercent = (latestEvent.data as Record<string, unknown> | undefined)?.percent;
        if (typeof rawPercent === 'number' && Number.isFinite(rawPercent)) {
          percentForTick = Math.max(0, Math.min(100, rawPercent));
        }
      }
      if (typeof snapshot.latest_sequence === 'number') {
        afterSequence = snapshot.latest_sequence;
      }
    } catch {
      // Snapshot endpoint may be missing on older backends — fall back to
      // status-only polling. The user still gets a stable bubble, just no
      // per-phase label.
      status = await client.getJobStatus(jobId);
    }

    if (onProgress) {
      try {
        onProgress({
          status: String(status.status ?? ''),
          label: labelForTick,
          percent: percentForTick,
          latestEvent,
        });
      } catch {
        // Callback must never break the polling loop.
      }
    }

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
  onProgress,
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
    onProgress,
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
