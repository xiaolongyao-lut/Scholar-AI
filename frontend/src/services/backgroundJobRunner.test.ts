import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the runtime client BEFORE importing the runner.
const getJobStatus = vi.fn();
const getJobEventSnapshot = vi.fn();
const cancelJob = vi.fn(async () => undefined);
const getJobArtifacts = vi.fn(async () => []);
const createJob = vi.fn();
const startJob = vi.fn(async () => undefined);
const createSession = vi.fn();
const getSession = vi.fn();

vi.mock('@/services/runtimeClient', () => ({
  getWritingRuntimeClient: () => ({
    getJobStatus,
    getJobEventSnapshot,
    cancelJob,
    getJobArtifacts,
    createJob,
    startJob,
    createSession,
    getSession,
  }),
}));

import {
  runBackgroundJob,
  waitForRuntimeJobTerminalState,
} from '@/services/backgroundJobRunner';
import type { CreateJobRequest } from '@/types/runtime';

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('waitForRuntimeJobTerminalState — failed path', () => {
  it('returns FAILED status without waiting for the 1800s timeout', async () => {
    // The runtime says the job failed almost immediately (post D-fix).
    getJobStatus.mockResolvedValueOnce({
      status: 'failed',
      error: 'HTTP 400: provider endpoint rejected: dns_resolved_to_unsafe_ip',
    });

    const detail = await waitForRuntimeJobTerminalState('job_x', {
      pollIntervalMs: 50,
      timeoutMs: 30 * 60 * 1000,
    });

    expect(detail.status).toBe('failed');
    expect(detail.error).toContain('dns_resolved_to_unsafe_ip');
    expect(getJobStatus).toHaveBeenCalledTimes(1);
    // Critical: failed status must NOT trigger a cancel — that path is for abort.
    expect(cancelJob).not.toHaveBeenCalled();
  });

  it('keeps polling while IN_PROGRESS, exits on FAILED', async () => {
    getJobStatus
      .mockResolvedValueOnce({ status: 'in_progress' })
      .mockResolvedValueOnce({ status: 'in_progress' })
      .mockResolvedValueOnce({ status: 'failed', error: 'upstream 502' });

    const promise = waitForRuntimeJobTerminalState('job_y', {
      pollIntervalMs: 100,
      timeoutMs: 30 * 60 * 1000,
    });

    // advance timers past 2 poll cycles
    await vi.advanceTimersByTimeAsync(250);
    const detail = await promise;
    expect(detail.status).toBe('failed');
    expect(detail.error).toContain('502');
    expect(getJobStatus).toHaveBeenCalledTimes(3);
  });

  it('returns completed status normally', async () => {
    getJobStatus.mockResolvedValueOnce({ status: 'completed' });

    const detail = await waitForRuntimeJobTerminalState('job_z', {
      pollIntervalMs: 50,
      timeoutMs: 30 * 60 * 1000,
    });

    expect(detail.status).toBe('completed');
  });

  it('treats a JOB_FAILED snapshot event as terminal even when status is stale', async () => {
    getJobEventSnapshot.mockResolvedValueOnce({
      status: { status: 'in_progress', error: null },
      events: [
        {
          event_id: 'evt_failed',
          job_id: 'job_event_failed',
          session_id: 'sess_event_failed',
          event_type: 'job_failed',
          timestamp: '2026-07-02T01:00:00.000Z',
          sequence: 3,
          data: { error: 'provider rejected request' },
          metadata: {},
        },
      ],
      latest_sequence: 3,
    });

    const detail = await waitForRuntimeJobTerminalState('job_event_failed', {
      pollIntervalMs: 50,
      timeoutMs: 30 * 60 * 1000,
    });

    expect(detail.status).toBe('failed');
    expect(detail.error).toContain('provider rejected request');
    expect(getJobStatus).not.toHaveBeenCalled();
    expect(cancelJob).not.toHaveBeenCalled();
  });
});

describe('runBackgroundJob — surfaces failed status to caller', () => {
  it('returns the FAILED status object instead of swallowing it', async () => {
    createSession.mockResolvedValue({ session_id: 'sess_a' });
    createJob.mockResolvedValue({ job_id: 'job_fail' });
    getJobStatus.mockResolvedValueOnce({
      status: 'failed',
      error: 'HTTP 400: provider endpoint rejected: dns_resolved_to_unsafe_ip',
    });

    const onJobCreated = vi.fn();
    const request = {
      kind: 'smart_read',
      input_text: 'q',
    } satisfies Omit<CreateJobRequest, 'session_id'>;
    const result = await runBackgroundJob({
      request,
      sessionTitle: 't',
      pollIntervalMs: 50,
      timeoutMs: 30 * 60 * 1000,
      onJobCreated,
    });

    expect(result.status.status).toBe('failed');
    expect(result.status.error).toContain('dns_resolved_to_unsafe_ip');
    expect(onJobCreated).toHaveBeenCalledOnce();
    expect(startJob).toHaveBeenCalledWith('job_fail');
    // After D-fix the runner returns within first poll; this is the contract
    // Dialog.tsx relies on to break out of "AI 思考中" state.
  });
});
