import test from 'node:test';
import assert from 'node:assert/strict';

/**
 * sessionDrawerHelpers.test.mjs — pure-function tests for the SessionDrawer.
 *
 * These helper tests intentionally stay on node:test because they do not need
 * a DOM renderer; the frontend also has Vitest + RTL for component coverage.
 */

async function loadModule() {
  try {
    return await import('./sessionDrawerHelpers.ts');
  } catch (error) {
    assert.fail(`sessionDrawerHelpers.ts must load: ${error}`);
  }
}

const baseSession = (overrides = {}) => ({
  session_id: 'sess-00000000-aaaa',
  user_id: null,
  mode: 'prompt',
  created_at: '2026-04-20T10:00:00Z',
  settings: {},
  tags: [],
  metadata: {},
  ...overrides,
});

test('sortAndLimitSessions: orders by metadata.updated_at desc, falls back to created_at', async () => {
  const { sortAndLimitSessions } = await loadModule();

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

  const sorted = sortAndLimitSessions([a, b, c]);
  assert.deepEqual(sorted.map((s) => s.session_id), ['b', 'c', 'a']);
});

test('sortAndLimitSessions: caps at `limit` items', async () => {
  const { sortAndLimitSessions } = await loadModule();
  const many = Array.from({ length: 15 }, (_, i) =>
    baseSession({ session_id: `s${i}`, created_at: `2026-04-${10 + i}T00:00:00Z` }),
  );
  assert.equal(sortAndLimitSessions(many, 5).length, 5);
  assert.equal(sortAndLimitSessions(many).length, 10); // default
});

test('sortAndLimitSessions: handles invalid timestamps without throwing', async () => {
  const { sortAndLimitSessions } = await loadModule();
  const junk = baseSession({ session_id: 'junk', created_at: 'not-a-date' });
  const good = baseSession({ session_id: 'good', created_at: '2026-04-20T10:00:00Z' });
  const sorted = sortAndLimitSessions([junk, good]);
  assert.equal(sorted[0].session_id, 'good');
});

test('shortSessionId: first 8 chars, tolerates empty', async () => {
  const { shortSessionId } = await loadModule();
  assert.equal(shortSessionId('abcdef0123456789'), 'abcdef01');
  assert.equal(shortSessionId(''), '');
  assert.equal(shortSessionId('abc'), 'abc');
});

test('sessionPreviewText: prefers title, then first_user_prompt, then empty placeholder', async () => {
  const { sessionPreviewText } = await loadModule();
  assert.equal(
    sessionPreviewText(baseSession({ metadata: { title: 'Draft outline' } })),
    'Draft outline',
  );
  assert.equal(
    sessionPreviewText(baseSession({ metadata: { first_user_prompt: 'hello' } })),
    'hello',
  );
  assert.equal(sessionPreviewText(baseSession()), '(empty session)');
});

test('sessionPreviewText: truncates with ellipsis at maxChars', async () => {
  const { sessionPreviewText } = await loadModule();
  const long = 'x'.repeat(80);
  const out = sessionPreviewText(baseSession({ metadata: { title: long } }), 40);
  assert.equal(out.length, 40);
  assert.ok(out.endsWith('…'));
});

test('isForkedSession: true only when parent_session_id is a non-empty string', async () => {
  const { isForkedSession } = await loadModule();
  assert.equal(isForkedSession(baseSession()), false);
  assert.equal(
    isForkedSession(baseSession({ metadata: { parent_session_id: '' } })),
    false,
  );
  assert.equal(
    isForkedSession(baseSession({ metadata: { parent_session_id: 'abc' } })),
    true,
  );
});

test('classifyTimelineEvent: known kinds pass through, unknown fold to "other"', async () => {
  const { classifyTimelineEvent } = await loadModule();
  const make = (event_kind) => ({
    event_id: 'e',
    session_id: 's',
    timestamp: '2026-04-20T00:00:00Z',
    workspace_key: 'w',
    payload: {},
    event_kind,
  });
  assert.equal(classifyTimelineEvent(make('user')), 'user');
  assert.equal(classifyTimelineEvent(make('tool_call')), 'tool_call');
  assert.equal(classifyTimelineEvent(make('checkpoint')), 'checkpoint');
  assert.equal(classifyTimelineEvent(make('mystery')), 'other');
});

test('resolveNextCursor: prefers explicit next_cursor, falls back to last event id', async () => {
  const { resolveNextCursor } = await loadModule();
  const events = [
    { event_id: 'e1', session_id: 's', event_kind: 'user', timestamp: '', workspace_key: '', payload: {} },
    { event_id: 'e2', session_id: 's', event_kind: 'user', timestamp: '', workspace_key: '', payload: {} },
  ];
  assert.equal(resolveNextCursor(events, 'explicit-xyz'), 'explicit-xyz');
  assert.equal(resolveNextCursor(events, null), 'e2');
  assert.equal(resolveNextCursor([], null), null);
  assert.equal(resolveNextCursor(events, ''), 'e2'); // empty string treated like null
});

test('formatRelativeTimestamp: seconds / minutes / hours / days / old date', async () => {
  const { formatRelativeTimestamp } = await loadModule();
  const now = Date.parse('2026-04-24T12:00:00Z');
  assert.equal(formatRelativeTimestamp('2026-04-24T11:59:30Z', now), '30s');
  assert.equal(formatRelativeTimestamp('2026-04-24T11:55:00Z', now), '5m');
  assert.equal(formatRelativeTimestamp('2026-04-24T09:00:00Z', now), '3h');
  assert.equal(formatRelativeTimestamp('2026-04-22T12:00:00Z', now), '2d');
  assert.equal(formatRelativeTimestamp('2026-03-01T00:00:00Z', now), '2026-03-01');
});

test('formatRelativeTimestamp: future timestamps return raw iso (clock skew guard)', async () => {
  const { formatRelativeTimestamp } = await loadModule();
  const now = Date.parse('2026-04-24T12:00:00Z');
  assert.equal(
    formatRelativeTimestamp('2026-04-25T00:00:00Z', now),
    '2026-04-25T00:00:00Z',
  );
});

test('mapTimelineToMessages: filters out non-chat events and extracts payloads correctly', async () => {
  const { mapTimelineToMessages } = await loadModule();
  const timeline = [
    {
      event_id: '1',
      session_id: 's1',
      event_kind: 'user',
      timestamp: '2026-04-20T10:00:00Z',
      workspace_key: 'wk',
      payload: { text: 'Hello world' }
    },
    {
      event_id: '2',
      session_id: 's1',
      event_kind: 'tool_call',
      timestamp: '2026-04-20T10:00:01Z',
      workspace_key: 'wk',
      payload: { tool_name: 'search' }
    },
    {
      event_id: '3',
      session_id: 's1',
      event_kind: 'assistant',
      timestamp: '2026-04-20T10:00:02Z',
      workspace_key: 'wk',
      payload: { content: 'I found this', usage: { total_tokens: 10 } }
    }
  ];

  const messages = mapTimelineToMessages(timeline);
  assert.equal(messages.length, 2);
  
  assert.equal(messages[0].role, 'user');
  assert.equal(messages[0].content, 'Hello world');
  assert.equal(messages[0].id, Date.parse('2026-04-20T10:00:00Z'));
  
  assert.equal(messages[1].role, 'assistant');
  assert.equal(messages[1].content, 'I found this');
  assert.deepEqual(messages[1].usage, { total_tokens: 10 });
});
