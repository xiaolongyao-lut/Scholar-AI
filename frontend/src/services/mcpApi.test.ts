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
      return { data: {} };
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
  createMcpServer,
  deleteMcpServer,
  getMcpServer,
  listMcpServers,
  listMcpServerTools,
  testMcpServer,
  updateMcpServer,
} from '@/services/mcpApi';

function getMock() {
  return (axios as any).create();
}

describe('mcpApi', () => {
  beforeEach(() => {
    const m = getMock();
    m.__calls.length = 0;
    m.__nextResponse = undefined;
  });

  it('listMcpServers without filter posts no params', async () => {
    const m = getMock();
    m.__nextResponse = [];
    await listMcpServers();
    expect(m.__calls).toHaveLength(1);
    expect(m.__calls[0]).toMatchObject({ method: 'GET', url: '/api/mcp/servers' });
    expect((m.__calls[0] as any).config?.params).toEqual({});
  });

  it('listMcpServers passes approval_state filter', async () => {
    const m = getMock();
    await listMcpServers({ approvalState: 'enabled_for_session' });
    expect((m.__calls[0] as any).config.params).toEqual({ approval_state: 'enabled_for_session' });
  });

  it('createMcpServer POSTs body verbatim', async () => {
    const m = getMock();
    m.__nextResponse = { server_id: 'mcp_xyz' };
    const result = await createMcpServer({
      name: 'Demo',
      server_slug: 'demo',
      transport: 'stdio',
      stdio: { command: 'python', args: ['-m', 'srv'], env: { K: 'v' } },
    });
    expect(result.server_id).toBe('mcp_xyz');
    const call = m.__calls[0] as any;
    expect(call.method).toBe('POST');
    expect(call.url).toBe('/api/mcp/servers');
    expect(call.body.transport).toBe('stdio');
    expect(call.body.stdio.command).toBe('python');
  });

  it('getMcpServer hits /api/mcp/servers/{id}', async () => {
    const m = getMock();
    m.__nextResponse = { server_id: 'mcp_abc' };
    await getMcpServer('mcp_abc');
    expect((m.__calls[0] as any).url).toBe('/api/mcp/servers/mcp_abc');
  });

  it('updateMcpServer issues PUT with body', async () => {
    const m = getMock();
    await updateMcpServer('mcp_abc', { approval_state: 'catalog_reviewed' });
    expect(m.__calls[0]).toMatchObject({
      method: 'PUT',
      url: '/api/mcp/servers/mcp_abc',
      body: { approval_state: 'catalog_reviewed' },
    });
  });

  it('deleteMcpServer issues DELETE', async () => {
    const m = getMock();
    await deleteMcpServer('mcp_abc');
    expect(m.__calls[0]).toMatchObject({ method: 'DELETE', url: '/api/mcp/servers/mcp_abc' });
  });

  it('testMcpServer issues POST to /test', async () => {
    const m = getMock();
    m.__nextResponse = { server_id: 'mcp_abc', status: 'ok', probed: true };
    const result = await testMcpServer('mcp_abc');
    expect(result.status).toBe('ok');
    expect((m.__calls[0] as any).url).toBe('/api/mcp/servers/mcp_abc/test');
  });

  it('listMcpServerTools issues GET to /tools', async () => {
    const m = getMock();
    m.__nextResponse = [];
    await listMcpServerTools('mcp_abc');
    expect((m.__calls[0] as any).url).toBe('/api/mcp/servers/mcp_abc/tools');
  });

  it('encodes server id for path safety', async () => {
    const m = getMock();
    await getMcpServer('mcp slash/abc');
    expect((m.__calls[0] as any).url).toBe('/api/mcp/servers/mcp%20slash%2Fabc');
  });
});
