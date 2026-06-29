import { renderHook, act } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

import { useJobEventPolling } from './useJobEventPolling';
import type { JobEventSnapshot, JobStatus, JobStatusDetail } from '@/types/runtime';

const mocks = vi.hoisted(() => ({
  setActiveJobTimeline: vi.fn(),
  getWritingRuntimeClient: vi.fn(),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: () => ({
    setActiveJobTimeline: mocks.setActiveJobTimeline,
  }),
}));

vi.mock('@/services/runtimeClient', () => ({
  getWritingRuntimeClient: mocks.getWritingRuntimeClient,
}));

function setDocumentVisibility(value: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => value,
  });
}

function makeSnapshot(status: JobStatus = 'in_progress'): JobEventSnapshot {
  const statusDetail = {
    job_id: 'job_1',
    session_id: 'session_1',
    status,
    error: null,
  } as unknown as JobStatusDetail;

  return {
    job_id: 'job_1',
    session_id: 'session_1',
    job: {
      job_id: 'job_1',
      session_id: 'session_1',
      status,
    },
    status: statusDetail,
    events: [],
    latest_sequence: 0,
    has_more: false,
  } as unknown as JobEventSnapshot;
}

function renderPollingHook(): ReturnType<typeof renderHook<void, unknown>> {
  return renderHook(() =>
    useJobEventPolling({
      jobId: 'job_1',
      sessionId: 'session_1',
      pollIntervalMs: 50,
      maxPollIntervalMs: 50,
      backoffMultiplier: 1,
    }),
  );
}

describe('useJobEventPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setDocumentVisibility('visible');
    mocks.setActiveJobTimeline.mockReset();
    mocks.getWritingRuntimeClient.mockReset();
  });

  afterEach(() => {
    setDocumentVisibility('visible');
    vi.useRealTimers();
  });

  it('polls immediately while visible', async () => {
    const getJobEventSnapshot = vi.fn(async () => makeSnapshot());
    mocks.getWritingRuntimeClient.mockReturnValue({ getJobEventSnapshot });

    renderPollingHook();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);
    expect(getJobEventSnapshot).toHaveBeenCalledWith('job_1', expect.objectContaining({
      limit: 100,
    }));
  });

  it('does not start polling while hidden until visibility returns', async () => {
    const getJobEventSnapshot = vi.fn(async () => makeSnapshot());
    mocks.getWritingRuntimeClient.mockReturnValue({ getJobEventSnapshot });
    setDocumentVisibility('hidden');

    renderPollingHook();

    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).not.toHaveBeenCalled();

    setDocumentVisibility('visible');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);
  });

  it('pauses scheduled polling while hidden and resumes on visibilitychange', async () => {
    const getJobEventSnapshot = vi.fn(async () => makeSnapshot());
    mocks.getWritingRuntimeClient.mockReturnValue({ getJobEventSnapshot });

    renderPollingHook();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);

    setDocumentVisibility('hidden');
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);

    setDocumentVisibility('visible');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);
  });

  it('does not keep an old hidden timer after visibility resumes', async () => {
    const getJobEventSnapshot = vi.fn(async () => makeSnapshot());
    mocks.getWritingRuntimeClient.mockReturnValue({ getJobEventSnapshot });

    renderPollingHook();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);

    setDocumentVisibility('hidden');
    await act(async () => {
      vi.advanceTimersByTime(50);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(1);

    setDocumentVisibility('visible');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(49);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJobEventSnapshot).toHaveBeenCalledTimes(3);
  });
});
