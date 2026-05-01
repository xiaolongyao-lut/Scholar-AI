import test from 'node:test';
import assert from 'node:assert/strict';

import { buildSamplingSaveRequest } from './samplingPayload.ts';

test('buildSamplingSaveRequest keeps only defined sampling fields in put payloads', () => {
  const request = buildSamplingSaveRequest('chat', {
    temperature: 0.7,
    top_p: undefined,
    top_k: 42,
    max_tokens: undefined,
  });

  assert.deepEqual(request, {
    type: 'put',
    payload: {
      chat: {
        temperature: 0.7,
        top_k: 42,
      },
    },
  });
});

test('buildSamplingSaveRequest turns blank overrides into a delete request', () => {
  const request = buildSamplingSaveRequest('chat', {
    temperature: undefined,
    top_p: undefined,
    top_k: undefined,
    max_tokens: undefined,
  });

  assert.deepEqual(request, {
    type: 'delete',
    task: 'chat',
  });
});
