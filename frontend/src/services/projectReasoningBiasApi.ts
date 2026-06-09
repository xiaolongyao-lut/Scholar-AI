import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type {
  ProjectReasoningBiasOptimizeRequest,
  ProjectReasoningBiasOptimizeResponse,
  ProjectReasoningBiasPayload,
  ProjectReasoningBiasScopes,
  ProjectReasoningBiasUpdateRequest,
} from '@/types/resources';

const defaultScopes: ProjectReasoningBiasScopes = {
  analysis_chain: true,
  chat_generation: false,
  project_wide: false,
  discussion_agent_ids: [],
};

export const emptyProjectReasoningBias = (): ProjectReasoningBiasPayload => ({
  version: 1,
  human_bias: '',
  scopes: { ...defaultScopes, discussion_agent_ids: [] },
  language: 'auto',
  updated_at: '',
  updated_by: 'user',
});

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseScopes(value: unknown): ProjectReasoningBiasScopes {
  if (!isObject(value)) return { ...defaultScopes, discussion_agent_ids: [] };
  const rawIds = value.discussion_agent_ids;
  const discussionAgentIds = Array.isArray(rawIds)
    ? rawIds
      .map((item) => String(item ?? '').trim())
      .filter((item, index, list) => item.length > 0 && list.indexOf(item) === index)
      .slice(0, 16)
    : [];
  return {
    analysis_chain: typeof value.analysis_chain === 'boolean' ? value.analysis_chain : true,
    chat_generation: typeof value.chat_generation === 'boolean' ? value.chat_generation : false,
    project_wide: typeof value.project_wide === 'boolean' ? value.project_wide : false,
    discussion_agent_ids: discussionAgentIds,
  };
}

function parseLanguage(value: unknown): ProjectReasoningBiasPayload['language'] {
  return value === 'zh' || value === 'en' || value === 'auto' ? value : 'auto';
}

function parseUpdatedBy(value: unknown): ProjectReasoningBiasPayload['updated_by'] {
  return value === 'ai_optimize' || value === 'migration' || value === 'user' ? value : 'user';
}

export function parseProjectReasoningBias(value: unknown): ProjectReasoningBiasPayload {
  if (!isObject(value)) return emptyProjectReasoningBias();
  return {
    version: 1,
    human_bias: typeof value.human_bias === 'string' ? value.human_bias : '',
    scopes: parseScopes(value.scopes),
    language: parseLanguage(value.language),
    updated_at: typeof value.updated_at === 'string' ? value.updated_at : '',
    updated_by: parseUpdatedBy(value.updated_by),
  };
}

function parseFieldSuggestions(value: unknown): ProjectReasoningBiasOptimizeResponse['field_suggestions'] {
  const obj = isObject(value) ? value : {};
  return {
    observation: typeof obj.observation === 'string' ? obj.observation : '',
    mechanism: typeof obj.mechanism === 'string' ? obj.mechanism : '',
    evidence: typeof obj.evidence === 'string' ? obj.evidence : '',
    boundary: typeof obj.boundary === 'string' ? obj.boundary : '',
    counter_evidence: typeof obj.counter_evidence === 'string' ? obj.counter_evidence : '',
    next_action: typeof obj.next_action === 'string' ? obj.next_action : '',
  };
}

export function parseProjectReasoningBiasOptimization(
  value: unknown,
): ProjectReasoningBiasOptimizeResponse {
  const obj = isObject(value) ? value : {};
  const rawNotes = obj.safety_notes;
  return {
    original_bias: typeof obj.original_bias === 'string' ? obj.original_bias : '',
    optimized_bias: typeof obj.optimized_bias === 'string' ? obj.optimized_bias : '',
    field_suggestions: parseFieldSuggestions(obj.field_suggestions),
    safety_notes: Array.isArray(rawNotes)
      ? rawNotes.map((item) => String(item ?? '').trim()).filter(Boolean).slice(0, 8)
      : [],
    language: obj.language === 'en' ? 'en' : 'zh',
  };
}

function assertProjectId(projectId: string): void {
  if (typeof projectId !== 'string' || projectId.trim().length === 0) {
    throw new Error('projectId is required');
  }
}

export async function getProjectReasoningBias(projectId: string): Promise<ProjectReasoningBiasPayload> {
  assertProjectId(projectId);
  const { data } = await axios.get<unknown>(
    `${getApiBaseUrl()}/resources/project/${encodeURIComponent(projectId)}/reasoning-bias`,
    { timeout: 8000 },
  );
  return parseProjectReasoningBias(data);
}

export async function saveProjectReasoningBias(
  projectId: string,
  request: ProjectReasoningBiasUpdateRequest,
): Promise<ProjectReasoningBiasPayload> {
  assertProjectId(projectId);
  const { data } = await axios.put<unknown>(
    `${getApiBaseUrl()}/resources/project/${encodeURIComponent(projectId)}/reasoning-bias`,
    request,
    { timeout: 10000 },
  );
  return parseProjectReasoningBias(data);
}

export async function optimizeProjectReasoningBias(
  projectId: string,
  request: ProjectReasoningBiasOptimizeRequest,
  options: { signal?: AbortSignal } = {},
): Promise<ProjectReasoningBiasOptimizeResponse> {
  assertProjectId(projectId);
  const { data } = await axios.post<unknown>(
    `${getApiBaseUrl()}/resources/project/${encodeURIComponent(projectId)}/reasoning-bias/optimize`,
    request,
    { timeout: 30000, signal: options.signal },
  );
  return parseProjectReasoningBiasOptimization(data);
}

export function isProjectReasoningBiasRequestCanceled(error: unknown): boolean {
  if (axios.isCancel(error)) return true;
  if (!isObject(error)) return false;
  return error.name === 'AbortError' || error.code === 'ERR_CANCELED';
}
