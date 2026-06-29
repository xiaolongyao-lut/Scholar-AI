import { useEffect, useMemo, useRef } from 'react';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import { useWriting, type JobTimelineState } from '@/contexts/WritingContext';
import { formatWritingRuntimeError, sanitizeRuntimeVisibleText } from '@/components/writing/writingRuntimeDisplay';
import type { JobStatus, JobStatusDetail, WritingEvent } from '@/types/runtime';

type TerminalEventHandler = (payload: {
  jobId: string;
  sessionId: string;
  statusDetail: JobStatusDetail;
}) => void | Promise<void>;

interface UseJobEventPollingOptions {
  jobId: string | null;
  sessionId: string | null;
  enabled?: boolean;
  pollIntervalMs?: number;
  maxPollIntervalMs?: number;
  backoffMultiplier?: number;
  onTerminalState?: TerminalEventHandler;
}

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
  'completed',
  'failed',
  'cancelled',
]);

const MAX_EVENT_BATCH_SIZE = 100;
const JOB_STATUS_ERROR_FALLBACK = '动作执行失败，请稍后重试。';
const JOB_POLLING_ERROR_FALLBACK = '事件轮询失败，请稍后重试。';

const normalizeJobStatus = (status: JobStatusDetail['status'] | null | undefined): JobStatus | null => {
  if (!status) {
    return null;
  }

  const normalized = status as JobStatus;
  return JOB_STATUSES.has(normalized) ? normalized : null;
};

const readEventSequence = (event: WritingEvent): number | null => {
  const sequence = Number(event.sequence);
  return Number.isSafeInteger(sequence) && sequence > 0 ? sequence : null;
};

export function useJobEventPolling({
  jobId,
  sessionId,
  enabled = true,
  pollIntervalMs = 1000,
  maxPollIntervalMs = 5000,
  backoffMultiplier = 1.5,
  onTerminalState,
}: UseJobEventPollingOptions): void {
  const { setActiveJobTimeline } = useWriting();
  const runtimeClient = useMemo(() => getWritingRuntimeClient(), []);
  const terminalHandlerRef = useRef(onTerminalState);

  useEffect(() => {
    terminalHandlerRef.current = onTerminalState;
  }, [onTerminalState]);

  useEffect(() => {
    if (!enabled || !jobId || !sessionId) {
      return;
    }

    let cancelled = false;
    let pollInFlight = false;
    let terminalHandled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let currentPollIntervalMs = pollIntervalMs;
    const seenEventIds = new Set<string>();
    let cursorTimestamp: string | null = null;
    let cursorEventId: string | null = null;
    let cursorSequence: number | null = null;
    let timeline: JobTimelineState = {
      jobId,
      sessionId,
      events: [],
      lastEventId: null,
      lastTimestamp: null,
      lastSequence: null,
      status: null,
      errorMessage: null,
    };

    setActiveJobTimeline(timeline);

    const scheduleNextPoll = () => {
      if (cancelled || terminalHandled) {
        return;
      }

      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      pollTimer = setTimeout(() => {
        void pollOnce();
      }, currentPollIntervalMs);
    };

    const setFastPoll = () => {
      currentPollIntervalMs = pollIntervalMs;
    };

    const increasePollInterval = () => {
      currentPollIntervalMs = Math.min(
        Math.round(currentPollIntervalMs * backoffMultiplier),
        maxPollIntervalMs
      );
    };

    const updateIntervalByStatus = (status: JobStatus | null, hasFreshEvents: boolean) => {
      if (hasFreshEvents) {
        setFastPoll();
        return;
      }

      if (!status) {
        increasePollInterval();
        return;
      }

      if (status === 'in_progress' || status === 'started') {
        setFastPoll();
        return;
      }

      increasePollInterval();
    };

    const commitTimeline = (statusDetail: JobStatusDetail, freshEvents: WritingEvent[]) => {
      const normalizedStatus = normalizeJobStatus(statusDetail.status);

      timeline = {
        ...timeline,
        events: [...timeline.events, ...freshEvents],
        lastTimestamp: cursorTimestamp,
        lastEventId: cursorEventId,
        lastSequence: cursorSequence,
        status: normalizedStatus,
        errorMessage: statusDetail.error
          ? sanitizeRuntimeVisibleText(statusDetail.error, JOB_STATUS_ERROR_FALLBACK)
          : null,
      };
      setActiveJobTimeline(timeline);
    };

    const pollOnce = async () => {
      if (cancelled || pollInFlight || terminalHandled) {
        return;
      }
      // Skip scheduled polls while the tab is hidden — visibilitychange
      // triggers an immediate catch-up poll on regain, so a hidden tick
      // would only burn a request the user can't see.
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        scheduleNextPoll();
        return;
      }

      pollInFlight = true;
      try {
        const snapshot = await runtimeClient.getJobEventSnapshot(jobId, {
          sinceTimestamp: cursorSequence === null ? cursorTimestamp : null,
          afterEventId: cursorSequence === null ? cursorEventId : null,
          afterSequence: cursorSequence,
          limit: MAX_EVENT_BATCH_SIZE,
        });
        const statusDetail = snapshot.status;
        const events = snapshot.events;

        const freshEvents = events.filter((event) => {
          if (seenEventIds.has(event.event_id)) {
            return false;
          }

          seenEventIds.add(event.event_id);
          return true;
        });

        if (freshEvents.length > 0) {
          const latestEvent = freshEvents[freshEvents.length - 1];
          cursorTimestamp = latestEvent.timestamp;
          cursorEventId = latestEvent.event_id;
          cursorSequence = readEventSequence(latestEvent) ?? cursorSequence;
        }

        commitTimeline(statusDetail, freshEvents);

        const normalizedStatus = normalizeJobStatus(statusDetail.status);
        updateIntervalByStatus(normalizedStatus, freshEvents.length > 0);

        if (normalizedStatus && TERMINAL_STATUSES.has(normalizedStatus)) {
          terminalHandled = true;
          if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
          }

          await terminalHandlerRef.current?.({
            jobId,
            sessionId,
            statusDetail,
          });
          return;
        }

        scheduleNextPoll();
      } catch (error) {
        timeline = {
          ...timeline,
          errorMessage: formatWritingRuntimeError(error, JOB_POLLING_ERROR_FALLBACK),
        };
        setActiveJobTimeline(timeline);
        increasePollInterval();
        scheduleNextPoll();
      } finally {
        pollInFlight = false;
      }
    };

    void pollOnce();

    // Visibility sensitivity: a hidden tab/window gains nothing from 1s job
    // polling. Pause while hidden, and poll immediately on regain so the
    // timeline catches up without waiting for the next scheduled tick.
    const handleVisibilityChange = () => {
      if (cancelled || terminalHandled) return;
      if (typeof document === 'undefined') return;
      if (document.visibilityState === 'visible') {
        void pollOnce();
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }

    return () => {
      cancelled = true;
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
      if (pollTimer) {
        clearTimeout(pollTimer);
      }
    };
  }, [
    backoffMultiplier,
    enabled,
    jobId,
    maxPollIntervalMs,
    pollIntervalMs,
    runtimeClient,
    sessionId,
    setActiveJobTimeline,
  ]);
}
