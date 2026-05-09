import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('axios', () => {
  const calls: Array<Record<string, unknown>> = [];
  const instance: {
    get: (url: string, config?: any) => Promise<{ data: any }>;
    post: (url: string, body?: any) => Promise<{ data: any }>;
    put: (url: string, body?: any) => Promise<{ data: any }>;
    delete: (url: string) => Promise<{ data: any }>;
    __calls: Array<Record<string, unknown>>;
    __nextResponse: unknown;
  } = {
    get: vi.fn(async (url: string, config?: any) => {
      calls.push({ method: 'GET', url, config });
      return { data: instance.__nextResponse ?? [] };
    }),
    post: vi.fn(async (url: string, body?: any) => {
      calls.push({ method: 'POST', url, body });
      return { data: instance.__nextResponse ?? {} };
    }),
    put: vi.fn(async (url: string, body?: any) => {
      calls.push({ method: 'PUT', url, body });
      return { data: instance.__nextResponse ?? {} };
    }),
    delete: vi.fn(async (url: string) => {
      calls.push({ method: 'DELETE', url });
      return { data: { deleted: true } };
    }),
    __calls: calls,
    __nextResponse: undefined,
  };
  return {
    default: { create: () => instance },
  };
});

import axios from 'axios';
import {
  createCredential,
  deleteCredential,
  getCredential,
  listCredentials,
  testCredential,
  updateCredential,
} from '@/services/credentialsApi';

function getMock() {
  return (axios as any).create();
}

describe('credentialsApi', () => {
  beforeEach(() => {
    const m = getMock();
    m.__calls.length = 0;
    m.__nextResponse = undefined;
  });

  it('listCredentials calls GET /api/credentials with no params by default', async () => {
    const m = getMock();
    m.__nextResponse = [
      {
        credential_id: 'cred_1',
        category: 'generation',
        provider: 'OpenAI',
        model: 'gpt-4o',
        base_url: 'https://api.openai.com/v1',
        protocol: 'openai_chat_completions',
        enabled: true,
        priority: 100,
        tags: [],
        strategy_hint: 'default',
        trust_source: 'official_provider',
        notes: '',
        api_key_masked: 'sk-a...CDEF',
        has_api_key: true,
        fingerprint: 'abcd0123',
        fingerprint_version: 'v1',
        created_at: '2026-05-08T01:00:00+00:00',
        updated_at: '2026-05-08T01:00:00+00:00',
      },
    ];
    const out = await listCredentials();
    expect(out).toHaveLength(1);
    expect(out[0].api_key_masked).toBe('sk-a...CDEF');
    const last = m.__calls[m.__calls.length - 1];
    expect(last.method).toBe('GET');
    expect(last.url).toBe('/api/credentials');
    expect(last.config?.params).toEqual({});
  });

  it('listCredentials forwards category/enabledOnly as params', async () => {
    const m = getMock();
    m.__nextResponse = [];
    await listCredentials({ category: 'embedding', enabledOnly: true });
    const last = m.__calls[m.__calls.length - 1];
    expect(last.config.params).toEqual({ category: 'embedding', enabled_only: true });
  });

  it('createCredential POSTs the body unchanged', async () => {
    const m = getMock();
    m.__nextResponse = { credential_id: 'cred_x' };
    await createCredential({
      category: 'generation',
      provider: 'OpenAI',
      model: 'gpt-4o',
      base_url: 'https://api.openai.com/v1',
      protocol: 'openai_chat_completions',
      api_key: 'sk-test',
    });
    const last = m.__calls[m.__calls.length - 1];
    expect(last.method).toBe('POST');
    expect(last.url).toBe('/api/credentials');
    expect(last.body.api_key).toBe('sk-test');
  });

  it('getCredential URL-encodes the credential_id', async () => {
    const m = getMock();
    m.__nextResponse = { credential_id: 'cred 1' };
    await getCredential('cred 1');
    const last = m.__calls[m.__calls.length - 1];
    expect(last.url).toBe('/api/credentials/cred%201');
  });

  it('updateCredential PUTs with optional rotation', async () => {
    const m = getMock();
    m.__nextResponse = {};
    await updateCredential('cred_1', { api_key: 'sk-new', enabled: false });
    const last = m.__calls[m.__calls.length - 1];
    expect(last.method).toBe('PUT');
    expect(last.url).toBe('/api/credentials/cred_1');
    expect(last.body).toEqual({ api_key: 'sk-new', enabled: false });
  });

  it('deleteCredential issues DELETE', async () => {
    const m = getMock();
    await deleteCredential('cred_1');
    const last = m.__calls[m.__calls.length - 1];
    expect(last.method).toBe('DELETE');
    expect(last.url).toBe('/api/credentials/cred_1');
  });

  it('testCredential forwards trustSourceOverride to body', async () => {
    const m = getMock();
    m.__nextResponse = {
      credential_id: 'cred_1',
      status: 'ok',
      decision: {
        allowed: true, reason: 'ok', trust_source: 'runtime_user_confirmed',
        scheme: 'https', host: 'api.openai.com', port: null, path: '/v1',
        resolved_ips: ['104.18.6.192'], rejected_ips: [], skipped_network: false,
      },
      probed: true,
    };
    const out = await testCredential('cred_1', { trustSourceOverride: 'runtime_user_confirmed' });
    expect(out.status).toBe('ok');
    const last = m.__calls[m.__calls.length - 1];
    expect(last.method).toBe('POST');
    expect(last.url).toBe('/api/credentials/cred_1/test');
    expect(last.body).toEqual({ trust_source_override: 'runtime_user_confirmed' });
  });
});
