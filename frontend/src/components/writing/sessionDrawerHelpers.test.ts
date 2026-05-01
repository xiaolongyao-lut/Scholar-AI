/**
 * sessionDrawerHelpers.test.ts — Vitest migration of node:test helpers
 *
 * TASK-180: All session drawer pure-function tests unified under Vitest
 * so `npm run test` covers them in the default suite.
 */
import { describe, it, expect } from 'vitest';
import {
  sortAndLimitSessions,
  shortSessionId,
  sessionPreviewText,
  isForkedSession,
  classifyTimelineEvent,
  resolveNextCursor,
  formatRelativeTimestamp,
  mapTimelineToMessages,
} from './sessionDrawerHelpers';

const baseSession = (overrides: Record<string, unknown> = {}) => ({
  session_id: 'sess-00000000-aaaa',
  user_id: null,
  mode: 'prompt',
  created_at: '2026-04-20T10:00:00Z',
  settings: {},
  tags: [],
  metadata: {},
  ...overrides,
});

describe('sortAndLimitSessions', () => {
  it('orders by metadata.updated_at desc, falls back to created_at', () => {
    const a = baseSession({
      session_id: 'a',
      created_at: '2026-04-20T10:00:00Z',
      metadata: { updated_at: '2026-04-22T12:00:00Z' },
    });
    const b = baseSession({
      session_id: 'b',
      created_at: '2026-04-24T00:00:00Z',
    });
    const c = baseSession({
      session_id: 'c',
      created_at: '2026-04-21T10:00:00Z',
      metadata: { updated_at: '2026-04-23T09:00:00Z' },
    });

    const sorted = sortAndLimitSessions([a, b, c] as never[]);
    expect(sorted.map((s: { session_id: string }) => s.session_id)).toEqual(['b', 'c', 'a']);
  });

  it('caps at `limit` items', () => {
    const many = Array.from({ length: 15 }, (_, i) =>
      baseSession({ session_id: `s${i}`, created_at: `2026-04-${String(10 + i).padStart(2, '0')}T00:00:00Z` }),
    );
    expect(sortAndLimitSessions(many as never[], 5)).toHaveLength(5);
    expect(sortAndLimitSessions(many as never[])).toHaveLength(10); // default
  });

  it('handles invalid timestamps without throwing', () => {
    const junk = baseSession({ session_id: 'junk', created_at: 'not-a-date' });
    const good = baseSession({ session_id: 'good', created_at: '2026-04-20T10:00:00Z' });
    const sorted = sortAndLimitSessions([junk, good] as never[]);
    expect((sorted[0] as { session_id: string }).session_id).toBe('good');
  });
});

describe('shortSessionId', () => {
  it('returns first 8 chars, tolerates empty', () => {
    expect(shortSessionId('abcdef0123456789')).toBe('abcdef01');
    expect(shortSessionId('')).toBe('');
    expect(shortSessionId('abc')).toBe('abc');
  });
});

describe('sessionPreviewText', () => {
  it('prefers title, then first_user_prompt, then empty placeholder', () => {
    expect(sessionPreviewText(baseSession({ metadata: { title: 'Draft outline' } }) as never)).toBe('Draft outline');
    expect(sessionPreviewText(baseSession({ metadata: { first_user_prompt: 'hello' } }) as never)).toBe('hello');
    expect(sessionPreviewText(baseSession() as never)).toBe('(empty session)');
  });

  it('truncates with ellipsis at maxChars', () => {
    const long = 'x'.repeat(80);
    const out = sessionPreviewText(baseSession({ metadata: { title: long } }) as never, 40);
    expect(out.length).toBe(40);
    expect(out.endsWith('…')).toBe(true);
  });
});

describe('isForkedSession', () => {
  it('true only when parent_session_id is a non-empty string', () => {
    expect(isForkedSession(baseSession() as never)).toBe(false);
    expect(isForkedSession(baseSession({ metadata: { parent_session_id: '' } }) as never)).toBe(false);
    expect(isForkedSession(baseSession({ metadata: { parent_session_id: 'abc' } }) as never)).toBe(true);
  });
});

describe('classifyTimelineEvent', () => {
  const make = (event_kind: string) => ({
    event_id: 'e',
    session_id: 's',
    timestamp: '2026-04-20T00:00:00Z',
    workspace_key: 'w',
    payload: {},
    event_kind,
  });

  it('known kinds pass through, unknown fold to "other"', () => {
    expect(classifyTimelineEvent(make('user') as never)).toBe('user');
    expect(classifyTimelineEvent(make('tool_call') as never)).toBe('tool_call');
    expect(classifyTimelineEvent(make('checkpoint') as never)).toBe('checkpoint');
    expect(classifyTimelineEvent(make('mystery') as never)).toBe('other');
  });
});

describe('resolveNextCursor', () => {
  const events = [
    { event_id: 'e1', session_id: 's', event_kind: 'user', timestamp: '', workspace_key: '', payload: {} },
    { event_id: 'e2', session_id: 's', event_kind: 'user', timestamp: '', workspace_key: '', payload: {} },
  ];

  it('prefers explicit next_cursor, falls back to last event id', () => {
    expect(resolveNextCursor(events as never[], 'explicit-xyz')).toBe('explicit-xyz');
    expect(resolveNextCursor(events as never[], null)).toBe('e2');
    expect(resolveNextCursor([], null)).toBeNull();
    expect(resolveNextCursor(events as never[], '')).toBe('e2');
  });
});

describe('formatRelativeTimestamp', () => {
  const now = Date.parse('2026-04-24T12:00:00Z');

  it('seconds / minutes / hours / days / old date', () => {
    expect(formatRelativeTimestamp('2026-04-24T11:59:30Z', now)).toBe('30s');
    expect(formatRelativeTimestamp('2026-04-24T11:55:00Z', now)).toBe('5m');
    expect(formatRelativeTimestamp('2026-04-24T09:00:00Z', now)).toBe('3h');
    expect(formatRelativeTimestamp('2026-04-22T12:00:00Z', now)).toBe('2d');
    expect(formatRelativeTimestamp('2026-03-01T00:00:00Z', now)).toBe('2026-03-01');
  });

  it('future timestamps return raw iso (clock skew guard)', () => {
    expect(formatRelativeTimestamp('2026-04-25T00:00:00Z', now)).toBe('2026-04-25T00:00:00Z');
  });
});

describe('mapTimelineToMessages', () => {
  it('filters out non-chat events and extracts payloads correctly', () => {
    const timeline = [
      { event_id: '1', session_id: 's1', event_kind: 'user', timestamp: '2026-04-20T10:00:00Z', workspace_key: 'wk', payload: { text: 'Hello world' } },
      { event_id: '2', session_id: 's1', event_kind: 'tool_call', timestamp: '2026-04-20T10:00:01Z', workspace_key: 'wk', payload: { tool_name: 'search' } },
      { event_id: '3', session_id: 's1', event_kind: 'assistant', timestamp: '2026-04-20T10:00:02Z', workspace_key: 'wk', payload: { content: 'I found this', usage: { total_tokens: 10 } } },
    ];

    const messages = mapTimelineToMessages(timeline as never[]);
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe('user');
    expect(messages[0].content).toBe('Hello world');
    expect(messages[1].role).toBe('assistant');
    expect(messages[1].content).toBe('I found this');
    expect(messages[1].usage).toEqual({ total_tokens: 10 });
  });

  it('returns empty array for empty timeline', () => {
    expect(mapTimelineToMessages([])).toEqual([]);
  });
});
