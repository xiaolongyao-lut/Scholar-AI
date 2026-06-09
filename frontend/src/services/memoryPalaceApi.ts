import { createApiClient } from './httpClient.ts';

const PATH = '/api/memory_palace';

let _client: ReturnType<typeof createApiClient> | null = null;
function client(): ReturnType<typeof createApiClient> {
  if (!_client) {
    _client = createApiClient();
  }
  return _client;
}

export interface MemoryRecordPayload {
  memory_id: string;
  text: string;
  wing: string;
  room: string;
  source_file: string;
  metadata: Record<string, unknown>;
}

export interface MemoryListPayload {
  available: boolean;
  memories: MemoryRecordPayload[];
}

export interface ListMemoryPalaceMemoriesOptions {
  wing?: string;
  room?: string;
  limit?: number;
}

export async function listMemoryPalaceMemories(
  opts: ListMemoryPalaceMemoriesOptions = {},
): Promise<MemoryListPayload> {
  const params: Record<string, string | number> = {
    limit: opts.limit ?? 6,
  };
  if (opts.wing?.trim()) params.wing = opts.wing.trim();
  if (opts.room?.trim()) params.room = opts.room.trim();

  const resp = await client().get<MemoryListPayload>(`${PATH}/memories`, {
    params,
  });
  return resp.data;
}
