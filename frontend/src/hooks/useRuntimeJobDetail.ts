import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  formatWritingRuntimeError,
  sanitizeRuntimeVisibleText,
} from '@/components/writing/writingRuntimeDisplay';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type {
  JobEventSnapshot,
  JobStatus,
  WritingArtifact,
  WritingEvent,
} from '@/types/runtime';

const EVENT_PAGE_SIZE = 50;
const MAX_VISIBLE_EVENTS = 40;
const MAX_VISIBLE_ARTIFACTS = 12;
const DEFAULT_POLL_INTERVAL_MS = 1200;
const DEFAULT_MAX_POLL_INTERVAL_MS = 5000;
const POLL_BACKOFF_MULTIPLIER = 1.5;
const SNAPSHOT_ERROR_FALLBACK = '任务运行详情暂不可用，请稍后重试。';
const ARTIFACT_ERROR_FALLBACK = '任务产物暂不可用，请稍后重试。';

const JOB_STATUSES = new Set<JobStatus>([
  'created',
  'queued',
  'started',
  'paused',
  'in_progress',
  'approval_pending',
  'approval_rejected',
  'completed',
  'failed',
  'cancelled',
]);

const TERMINAL_STATUSES = new Set<JobStatus>([
  'approval_rejected',
  'completed',
  'failed',
  'cancelled',
]);

const ARTIFACT_EVENT_TYPES = new Set([
  'artifact_created',
  'artifact_updated',
]);

export interface RuntimeJobDetailEvent {
  eventId: string;
  eventType: string;
  sequence: number;
  timestamp: string;
  stage: string | null;
  message: string | null;
  percent: number | null;
  recoveryRecorded: boolean;
}

export interface RuntimeJobArtifactSummary {
  artifactId: string;
  artifactType: string;
  createdAt: string;
}

export interface RuntimeJobDetailState {
  jobId: string | null;
  status: JobStatus | null;
  progress: number | null;
  stage: string | null;
  message: string | null;
  latestSequence: number;
  events: RuntimeJobDetailEvent[];
  artifacts: RuntimeJobArtifactSummary[];
  artifactCount: number;
  recoveryRecorded: boolean;
  loading: boolean;
  errorMessage: string | null;
  artifactErrorMessage: string | null;
}

interface UseRuntimeJobDetailOptions {
  jobId: string | null;
  enabled?: boolean;
  pollIntervalMs?: number;
  maxPollIntervalMs?: number;
}

export interface UseRuntimeJobDetailResult {
  detail: RuntimeJobDetailState;
  retry: () => void;
}

function createDetailState(jobId: string | null, loading = false): RuntimeJobDetailState {
  return {
    jobId,
    status: null,
    progress: null,
    stage: null,
    message: null,
    latestSequence: 0,
    events: [],
    artifacts: [],
    artifactCount: 0,
    recoveryRecorded: false,
    loading,
    errorMessage: null,
    artifactErrorMessage: null,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function safeVisibleText(value: unknown): string | null {
  const visible = sanitizeRuntimeVisibleText(value, '');
  return visible || null;
}

function readFirstVisibleText(
  source: Record<string, unknown>,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const visible = safeVisibleText(source[key]);
    if (visible) return visible;
  }
  return null;
}

function readPercent(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function readSequence(value: unknown): number {
  const sequence = Number(value);
  return Number.isSafeInteger(sequence) && sequence >= 0 ? sequence : 0;
}

function normalizeJobStatus(value: unknown): JobStatus | null {
  if (typeof value !== 'string') return null;
  const normalized = value as JobStatus;
  return JOB_STATUSES.has(normalized) ? normalized : null;
}

function hasSafeRecoveryMarker(event: WritingEvent): boolean {
  const sources = [event.data, event.metadata].filter(isRecord);
  return sources.some((source) => {
    if (source.recovery_recorded === true) return true;
    return ['checkpoint_label', 'recovery_label', 'resume_label', 'snapshot_label']
      .some((key) => Boolean(safeVisibleText(source[key])));
  });
}

function projectEvent(event: WritingEvent): RuntimeJobDetailEvent {
  const data = isRecord(event.data) ? event.data : {};
  const eventType = typeof event.event_type === 'string' && event.event_type.trim()
    ? event.event_type.trim()
    : 'job_progress';

  const isProgressEvent = eventType === 'job_progress';
  return {
    eventId: String(event.event_id ?? ''),
    eventType,
    sequence: readSequence(event.sequence),
    timestamp: typeof event.timestamp === 'string' ? event.timestamp : '',
    stage: isProgressEvent ? readFirstVisibleText(data, ['phase_label', 'stage', 'phase', 'label']) : null,
    message: isProgressEvent ? readFirstVisibleText(data, ['message']) : null,
    percent: isProgressEvent ? readPercent(data.progress ?? data.percent) : null,
    recoveryRecorded: hasSafeRecoveryMarker(event),
  };
}

function projectArtifacts(artifacts: WritingArtifact[]): {
  items: RuntimeJobArtifactSummary[];
  totalCount: number;
} {
  const items = artifacts
    .map((artifact) => ({
      artifactId: String(artifact.artifact_id ?? ''),
      artifactType: typeof artifact.artifact_type === 'string' ? artifact.artifact_type : '',
      createdAt: typeof artifact.created_at === 'string' ? artifact.created_at : '',
    }))
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
    .slice(0, MAX_VISIBLE_ARTIFACTS);
  return { items, totalCount: artifacts.length };
}

function mergeEvents(
  existing: RuntimeJobDetailEvent[],
  incoming: WritingEvent[],
): RuntimeJobDetailEvent[] {
  const byId = new Map<string, RuntimeJobDetailEvent>();
  for (const event of existing) {
    if (event.eventId) byId.set(event.eventId, event);
  }
  for (const event of incoming.map(projectEvent)) {
    if (event.eventId) byId.set(event.eventId, event);
  }
  return [...byId.values()]
    .sort((left, right) => (
      left.sequence - right.sequence || left.timestamp.localeCompare(right.timestamp)
    ))
    .slice(-MAX_VISIBLE_EVENTS);
}

function latestEventValue<T>(
  events: RuntimeJobDetailEvent[],
  read: (event: RuntimeJobDetailEvent) => T | null,
): T | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const value = read(events[index]);
    if (value !== null) return value;
  }
  return null;
}

function latestAttemptBoundary(events: RuntimeJobDetailEvent[]): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index].eventType === 'job_started') {
      return events[index].sequence;
    }
  }
  return null;
}

function latestIncomingAttemptBoundary(events: WritingEvent[]): number | null {
  let latest: number | null = null;
  for (const event of events) {
    if (event.event_type !== 'job_started') continue;
    const sequence = readSequence(event.sequence);
    if (sequence > 0 && (latest === null || sequence > latest)) {
      latest = sequence;
    }
  }
  return latest;
}

function currentAttemptEvents(
  events: RuntimeJobDetailEvent[],
  startSequence: number | null,
): RuntimeJobDetailEvent[] {
  if (startSequence === null) return events;
  return events.filter((event) => event.sequence >= startSequence);
}

function hasFreshSnapshotEvents(
  current: RuntimeJobDetailState,
  snapshot: JobEventSnapshot,
): boolean {
  const knownIds = new Set(current.events.map((event) => event.eventId).filter(Boolean));
  const knownSequences = new Set(current.events.map((event) => event.sequence).filter((sequence) => sequence > 0));
  const incomingEvents = Array.isArray(snapshot.events) ? snapshot.events : [];
  return incomingEvents.some((event) => {
    const eventId = String(event.event_id ?? '');
    if (eventId) return !knownIds.has(eventId);
    const sequence = readSequence(event.sequence);
    return sequence > 0 && !knownSequences.has(sequence);
  });
}

interface AppliedSnapshot {
  detail: RuntimeJobDetailState;
  attemptBoundary: number | null;
}

function readSnapshotMetadata(snapshot: JobEventSnapshot): Record<string, unknown> {
  return isRecord(snapshot.status.metadata) ? snapshot.status.metadata : {};
}

function applySnapshot(
  current: RuntimeJobDetailState,
  snapshot: JobEventSnapshot,
  activeAttemptBoundary: number | null,
): AppliedSnapshot {
  const freshEvents = Array.isArray(snapshot.events) ? snapshot.events : [];
  const events = mergeEvents(current.events, freshEvents);
  const metadata = readSnapshotMetadata(snapshot);
  const retainedAttemptBoundary = latestAttemptBoundary(events);
  const incomingAttemptBoundary = latestIncomingAttemptBoundary(freshEvents);
  const observedAttemptBoundary = retainedAttemptBoundary === null
    ? incomingAttemptBoundary
    : incomingAttemptBoundary === null
      ? retainedAttemptBoundary
      : Math.max(retainedAttemptBoundary, incomingAttemptBoundary);
  const attemptBoundary = observedAttemptBoundary === null
    ? activeAttemptBoundary
    : activeAttemptBoundary === null
      ? observedAttemptBoundary
      : Math.max(activeAttemptBoundary, observedAttemptBoundary);
  const attemptEvents = currentAttemptEvents(events, attemptBoundary);
  const isNewAttempt = attemptBoundary !== null
    && (activeAttemptBoundary === null || attemptBoundary > activeAttemptBoundary);
  const eventProgress = latestEventValue(attemptEvents, (event) => event.percent);
  const eventStage = latestEventValue(attemptEvents, (event) => event.stage);
  const eventMessage = latestEventValue(attemptEvents, (event) => event.message);
  const terminalEventStatus: Partial<Record<string, JobStatus>> = {
    approval_rejected: 'approval_rejected',
    job_completed: 'completed',
    job_failed: 'failed',
    job_cancelled: 'cancelled',
  };
  const latestEvent = events.at(-1) ?? null;
  const status = (latestEvent ? terminalEventStatus[latestEvent.eventType] ?? null : null)
    ?? normalizeJobStatus(snapshot.status.status);
  const latestSequence = readSequence(snapshot.latest_sequence);
  const metadataProgress = attemptBoundary === null ? readPercent(metadata.progress) : null;
  const metadataStage = attemptBoundary === null
    ? readFirstVisibleText(metadata, ['progress_stage', 'stage', 'phase'])
    : null;
  const metadataMessage = attemptBoundary === null
    ? readFirstVisibleText(metadata, ['progress_message', 'message', 'detail'])
    : null;
  const failureMessage = snapshot.status.error
    ? sanitizeRuntimeVisibleText(snapshot.status.error, '任务执行失败，详细诊断已记录到本地日志。')
    : '任务执行失败，详细诊断已记录到本地日志。';

  return {
    attemptBoundary,
    detail: {
      ...current,
      status,
      progress: eventProgress ?? metadataProgress ?? (isNewAttempt ? null : current.progress),
      stage: eventStage ?? metadataStage ?? (isNewAttempt ? null : current.stage),
      message: eventMessage ?? metadataMessage ?? (isNewAttempt ? null : current.message),
      latestSequence: Math.max(current.latestSequence, latestSequence),
      events,
      recoveryRecorded: current.recoveryRecorded || events.some((event) => event.recoveryRecorded),
      loading: false,
      errorMessage: status === 'failed' || status === 'approval_rejected'
        ? failureMessage
        : null,
    },
  };
}

function nextEventCursor(snapshot: JobEventSnapshot, current: number | null): number | null {
  const nextAfterSequence = readSequence(snapshot.next_after_sequence);
  if (nextAfterSequence > 0) {
    return Math.max(current ?? 0, nextAfterSequence);
  }

  const eventSequences = (Array.isArray(snapshot.events) ? snapshot.events : [])
    .map((event) => readSequence(event.sequence))
    .filter((sequence) => sequence > 0);
  if (eventSequences.length > 0) {
    return Math.max(current ?? 0, ...eventSequences);
  }

  if (!snapshot.has_more) {
    const latestSequence = readSequence(snapshot.latest_sequence);
    if (latestSequence > 0) return Math.max(current ?? 0, latestSequence);
  }
  return current;
}

function shouldRefreshArtifacts(snapshot: JobEventSnapshot): boolean {
  const status = normalizeJobStatus(snapshot.status.status);
  if (status && TERMINAL_STATUSES.has(status)) return true;
  return (Array.isArray(snapshot.events) ? snapshot.events : [])
    .some((event) => ARTIFACT_EVENT_TYPES.has(String(event.event_type ?? '')));
}

export function useRuntimeJobDetail({
  jobId,
  enabled = true,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  maxPollIntervalMs = DEFAULT_MAX_POLL_INTERVAL_MS,
}: UseRuntimeJobDetailOptions): UseRuntimeJobDetailResult {
  const runtimeClient = useMemo(() => getWritingRuntimeClient(), []);
  const [retryToken, setRetryToken] = useState(0);
  const [detail, setDetail] = useState<RuntimeJobDetailState>(() => createDetailState(null));

  const retry = useCallback(() => {
    setRetryToken((current) => current + 1);
  }, []);

  useEffect(() => {
    if (!enabled || !jobId) {
      setDetail(createDetailState(null));
      return;
    }

    let disposed = false;
    let pollInFlight = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let cursor: number | null = null;
    let activeAttemptBoundary: number | null = null;
    let currentPollIntervalMs = pollIntervalMs;
    let current = createDetailState(jobId, true);

    const commit = (next: RuntimeJobDetailState): void => {
      current = next;
      if (!disposed) setDetail(next);
    };

    const clearPollTimer = (): void => {
      if (pollTimer !== null) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
    };

    const scheduleNextPoll = (poll: () => Promise<void>): void => {
      if (disposed) return;
      clearPollTimer();
      pollTimer = setTimeout(() => {
        void poll();
      }, currentPollIntervalMs);
    };

    const readArtifacts = async (): Promise<void> => {
      try {
        const artifacts = await runtimeClient.getJobArtifacts(jobId);
        if (disposed) return;
        const projected = projectArtifacts(Array.isArray(artifacts) ? artifacts : []);
        commit({
          ...current,
          artifacts: projected.items,
          artifactCount: projected.totalCount,
          artifactErrorMessage: null,
        });
      } catch (error) {
        if (disposed) return;
        commit({
          ...current,
          artifactErrorMessage: formatWritingRuntimeError(error, ARTIFACT_ERROR_FALLBACK),
        });
      }
    };

    const pollOnce = async (initial = false): Promise<void> => {
      if (disposed || pollInFlight) return;
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        currentPollIntervalMs = maxPollIntervalMs;
        scheduleNextPoll(() => pollOnce(false));
        return;
      }

      pollInFlight = true;
      try {
        const snapshotPromise = runtimeClient.getJobEventSnapshot(jobId, {
          afterSequence: cursor,
          limit: EVENT_PAGE_SIZE,
        });
        const snapshot = initial
          ? (await Promise.all([snapshotPromise, readArtifacts()]))[0]
          : await snapshotPromise;
        if (disposed) return;

        const hasFreshEvents = hasFreshSnapshotEvents(current, snapshot);
        const applied = applySnapshot(current, snapshot, activeAttemptBoundary);
        activeAttemptBoundary = applied.attemptBoundary;
        commit(applied.detail);
        cursor = nextEventCursor(snapshot, cursor);

        const terminal = current.status !== null && TERMINAL_STATUSES.has(current.status);
        if (!initial && (shouldRefreshArtifacts(snapshot) || terminal) && !snapshot.has_more) {
          await readArtifacts();
          if (disposed) return;
        }
        if (terminal && snapshot.has_more) {
          // A terminal status can arrive with a paginated event tail. Drain the
          // remaining page before stopping so the detail view is complete.
          currentPollIntervalMs = pollIntervalMs;
          scheduleNextPoll(() => pollOnce(false));
          return;
        }
        if (terminal) {
          clearPollTimer();
          return;
        }

        currentPollIntervalMs = hasFreshEvents || snapshot.has_more
          ? pollIntervalMs
          : Math.min(
              Math.round(currentPollIntervalMs * POLL_BACKOFF_MULTIPLIER),
              maxPollIntervalMs,
            );
        scheduleNextPoll(() => pollOnce(false));
      } catch (error) {
        if (disposed) return;
        commit({
          ...current,
          loading: false,
          errorMessage: formatWritingRuntimeError(error, SNAPSHOT_ERROR_FALLBACK),
        });
        currentPollIntervalMs = Math.min(
          Math.round(currentPollIntervalMs * POLL_BACKOFF_MULTIPLIER),
          maxPollIntervalMs,
        );
        scheduleNextPoll(() => pollOnce(false));
      } finally {
        pollInFlight = false;
      }
    };

    commit(current);
    void pollOnce(true);

    const handleVisibilityChange = (): void => {
      if (disposed || typeof document === 'undefined') return;
      if (document.visibilityState === 'visible') {
        clearPollTimer();
        void pollOnce(false);
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }

    return () => {
      disposed = true;
      clearPollTimer();
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
    };
  }, [
    enabled,
    jobId,
    maxPollIntervalMs,
    pollIntervalMs,
    retryToken,
    runtimeClient,
  ]);

  return { detail, retry };
}
