/**
 * McpPendingCallPoller — Phase 4 vitest coverage.
 *
 * Uses pollOverride / decideOverride seams so tests don't depend on
 * axios mocking or window timers across the entire app boot.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import React from 'react';
import { McpPendingCallPoller } from './McpPendingCallPoller';
import type {
  PendingMcpToolCall,
} from '@/services/mcpApi';

function makePending(overrides: Partial<PendingMcpToolCall> = {}): PendingMcpToolCall {
  return {
    id: 'pc_1',
    server_id: 'mcp_demo',
    tool_name: 'write_thing',
    capability: 'write',
    args_preview: '{"v":"hi"}',
    created_at: '2026-05-16T00:00:00+00:00',
    ...overrides,
  };
}

describe('McpPendingCallPoller', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders nothing when poll returns empty', async () => {
    const poll = vi.fn().mockResolvedValue([]);
    const { container } = render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[data-testid="mcp-tool-approval-modal"]')).toBeNull();
    expect(poll).toHaveBeenCalled();
  });

  it('backs off empty polls to the idle interval', async () => {
    const poll = vi.fn().mockResolvedValue([]);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={500}
        pollOverride={poll}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(499);
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it('shares the initial in-flight poll across React StrictMode remounts', async () => {
    let resolvePoll: ((value: PendingMcpToolCall[]) => void) | null = null;
    const poll = vi.fn(
      () =>
        new Promise<PendingMcpToolCall[]>((resolve) => {
          resolvePoll = resolve;
        }),
    );
    render(
      <React.StrictMode>
        <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />
      </React.StrictMode>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      if (!resolvePoll) throw new Error('poll resolver was not registered');
      resolvePoll([]);
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it('renders modal when poll returns a pending call', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    render(<McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();
    const text = screen.getByTestId('mcp-tool-approval-modal').textContent ?? '';
    expect(text).toContain('当前 MCP 服务');
    expect(text).toContain('待确认工具');
    expect(text).not.toContain('mcp_demo');
    expect(text).not.toContain('write_thing');
    expect(screen.getByTestId('mcp-approval-capability').textContent).toContain('写入');
  });

  it('pauses network polling while a pending approval is open', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={500}
        pollOverride={poll}
        decideOverride={decide}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();
  });

  it('approve click calls decide with approve + rememberForRun=false', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} decideOverride={decide} />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-approve'));
      await Promise.resolve();
    });
    expect(decide).toHaveBeenCalledWith('pc_1', 'approve', false);
  });

  it('cancel click calls decide with reject', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} decideOverride={decide} />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
    });
    expect(decide).toHaveBeenCalledWith('pc_1', 'reject', false);
  });

  it('remember toggle propagates to decide on approve', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} decideOverride={decide} />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-remember'));
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-approve'));
      await Promise.resolve();
    });
    expect(decide).toHaveBeenCalledWith('pc_1', 'approve', true);
  });

  it('unknown capability still renders modal (ask path)', async () => {
    const poll = vi
      .fn()
      .mockResolvedValue([makePending({ capability: 'unknown', tool_name: 'mystery' })]);
    render(<McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const cap = screen.getByTestId('mcp-approval-capability');
    expect(cap.textContent).toContain('待确认操作');
    // Approve enabled for unknown (modal does NOT auto-disable, backend gates).
    const approveBtn = screen.getByTestId('mcp-approval-approve') as HTMLButtonElement;
    expect(approveBtn.disabled).toBe(false);
  });

  it('destructive defense-in-depth: approve button is disabled', async () => {
    // The backend should never emit a destructive pending call (those are
    // hard-blocked in the runner). If one slips through, the modal must
    // refuse to approve.
    const poll = vi
      .fn()
      .mockResolvedValue([makePending({ capability: 'destructive', tool_name: 'rm_rf' })]);
    render(<McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const approveBtn = screen.getByTestId('mcp-approval-approve') as HTMLButtonElement;
    expect(approveBtn.disabled).toBe(true);
  });

  it('poll failure does not throw; modal stays absent', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const poll = vi.fn().mockRejectedValue(new Error('network down'));
    const { container } = render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('[data-testid="mcp-tool-approval-modal"]')).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(
      '[McpPendingCallPoller] poll failed; retrying without exposing backend detail',
    );
    warnSpy.mockRestore();
  });

  it('decide failure closes modal without logging raw backend detail', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockRejectedValue(new Error('env=VISION_PROVIDER /api/mcp/pending-calls/pc_1'));
    render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} decideOverride={decide} />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(
      '[McpPendingCallPoller] decide failed; closing pending prompt without exposing backend detail',
    );
    expect(warnSpy).not.toHaveBeenCalledWith(expect.any(String), expect.any(Error));
    warnSpy.mockRestore();
  });

  it('after approve, modal disappears (state cleared)', async () => {
    const poll = vi.fn().mockResolvedValue([makePending()]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller pollIntervalMs={50} pollOverride={poll} decideOverride={decide} />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-approve'));
      await Promise.resolve();
      await Promise.resolve();
    });
    // Next poll returns empty so modal stays closed.
    poll.mockResolvedValueOnce([]);
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();
  });

  it('does not re-pop the same call_id after decide (orphan backend entry)', async () => {
    // Backend orphan: the runner was cancelled mid-decision so store.decide()
    // never ran and the same pending call keeps coming back from GET.
    // The poller must de-dup by call_id so the modal doesn't flicker back.
    const orphan = makePending();
    const poll = vi.fn().mockResolvedValue([orphan]);
    const decide = vi.fn().mockResolvedValue(undefined);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={50}
        pollOverride={poll}
        decideOverride={decide}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();

    // Poll still returns the orphan; modal must NOT come back.
    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll.mock.calls.length).toBeGreaterThan(1);
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();
  });

  it('does not re-pop a call_id whose decide returned 404', async () => {
    const orphan = makePending({ id: 'pc_404' });
    const poll = vi.fn().mockResolvedValue([orphan]);
    const decideError = Object.assign(new Error('404'), {
      response: { status: 404 },
    });
    const decide = vi.fn().mockRejectedValue(decideError);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={50}
        pollOverride={poll}
        decideOverride={decide}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();
    warnSpy.mockRestore();
  });

  it('retries the same call_id after a transient decide failure', async () => {
    const pending = makePending({ id: 'pc_500' });
    const poll = vi.fn().mockResolvedValue([pending]);
    const decideError = Object.assign(new Error('500'), {
      response: { status: 500 },
    });
    const decide = vi.fn().mockRejectedValue(decideError);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={50}
        pollOverride={poll}
        decideOverride={decide}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId('mcp-approval-cancel'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByTestId('mcp-tool-approval-modal')).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(80);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId('mcp-tool-approval-modal')).toBeTruthy();
    warnSpy.mockRestore();
  });

  it('skips polls while the document is hidden', async () => {
    const poll = vi.fn().mockResolvedValue([]);
    render(
      <McpPendingCallPoller
        pollIntervalMs={50}
        idlePollIntervalMs={50}
        pollOverride={poll}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const initialCount = poll.mock.calls.length;

    // Hide the tab and advance well past the idle interval.
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll.mock.calls.length).toBe(initialCount);

    // Regain visibility — dispatch the event so the poller catch-ups immediately.
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'visible',
    });
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poll.mock.calls.length).toBeGreaterThan(initialCount);
  });
});
