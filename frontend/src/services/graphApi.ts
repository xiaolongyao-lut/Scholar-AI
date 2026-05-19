import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { components } from '@/generated/openapi';

// Import wire types directly from the generated OpenAPI bindings so the
// service layer stays independent of any UI helper modules.
export type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];

const API_BASE = getApiBaseUrl();

export interface GraphPayloadQuery {
  scope_kind?: 'question' | 'material' | 'concept';
  scope_ref?: string;
  /** Comma-joined node ids to keep. Empty / undefined returns the full snapshot. */
  filter?: string;
}

export async function getGraphPayload(query: GraphPayloadQuery = {}): Promise<GraphPayloadV0> {
  const { data } = await axios.get<GraphPayloadV0>(`${API_BASE}/api/graph/payload`, {
    params: {
      scope_kind: query.scope_kind ?? 'question',
      scope_ref: query.scope_ref ?? '',
      ...(query.filter ? { filter: query.filter } : {}),
    },
  });
  return data;
}
