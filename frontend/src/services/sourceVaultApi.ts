import axios from 'axios';

import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export interface SourceVaultSource {
  source_id: string;
  source_type: string;
  title: string;
  source_hash: string;
  original_filename: string;
  stored_path: string;
  file_size: number;
  parser_version: string;
  chunker_version: string;
  storage_status: 'stored' | 'referenced' | 'missing';
  first_seen_at: string;
  last_indexed_at: string;
  project_ids: string[];
}

export interface SourceVaultOverview {
  total_sources: number;
  total_project_links: number;
  fts_enabled: boolean;
  storage_root: string;
  db_path: string;
  sources: SourceVaultSource[];
}

export interface SourceVaultSearchResult {
  chunk_id: string;
  source_id: string;
  source_hash: string;
  title: string;
  chunk_index: number;
  text: string;
  score: number | null;
}

export interface SourceVaultSearchResponse {
  query: string;
  project_id: string | null;
  results: SourceVaultSearchResult[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Invalid Source Vault response: ${field} must be a string`);
  }
  return value;
}

function readNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid Source Vault response: ${field} must be a finite number`);
  }
  return value;
}

function readBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`Invalid Source Vault response: ${field} must be a boolean`);
  }
  return value;
}

function readStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) {
    throw new Error(`Invalid Source Vault response: ${field} must be a string array`);
  }
  return [...value];
}

function readStorageStatus(value: unknown): SourceVaultSource['storage_status'] {
  if (value === 'stored' || value === 'referenced' || value === 'missing') {
    return value;
  }
  throw new Error('Invalid Source Vault response: storage_status is unknown');
}

export function parseSourceVaultSource(value: unknown): SourceVaultSource {
  if (!isRecord(value)) {
    throw new Error('Invalid Source Vault response: source must be an object');
  }
  return {
    source_id: readString(value.source_id, 'source_id'),
    source_type: readString(value.source_type, 'source_type'),
    title: readString(value.title, 'title'),
    source_hash: readString(value.source_hash, 'source_hash'),
    original_filename: readString(value.original_filename, 'original_filename'),
    stored_path: readString(value.stored_path, 'stored_path'),
    file_size: readNumber(value.file_size, 'file_size'),
    parser_version: readString(value.parser_version, 'parser_version'),
    chunker_version: readString(value.chunker_version, 'chunker_version'),
    storage_status: readStorageStatus(value.storage_status),
    first_seen_at: readString(value.first_seen_at, 'first_seen_at'),
    last_indexed_at: readString(value.last_indexed_at, 'last_indexed_at'),
    project_ids: readStringArray(value.project_ids, 'project_ids'),
  };
}

export function parseSourceVaultOverview(value: unknown): SourceVaultOverview {
  if (!isRecord(value)) {
    throw new Error('Invalid Source Vault response: overview must be an object');
  }
  if (!Array.isArray(value.sources)) {
    throw new Error('Invalid Source Vault response: sources must be an array');
  }
  return {
    total_sources: readNumber(value.total_sources, 'total_sources'),
    total_project_links: readNumber(value.total_project_links, 'total_project_links'),
    fts_enabled: readBoolean(value.fts_enabled, 'fts_enabled'),
    storage_root: readString(value.storage_root, 'storage_root'),
    db_path: readString(value.db_path, 'db_path'),
    sources: value.sources.map(parseSourceVaultSource),
  };
}

export function parseSourceVaultSearchResult(value: unknown): SourceVaultSearchResult {
  if (!isRecord(value)) {
    throw new Error('Invalid Source Vault response: search result must be an object');
  }
  const rawScore = value.score;
  return {
    chunk_id: readString(value.chunk_id, 'chunk_id'),
    source_id: readString(value.source_id, 'source_id'),
    source_hash: readString(value.source_hash, 'source_hash'),
    title: readString(value.title, 'title'),
    chunk_index: readNumber(value.chunk_index, 'chunk_index'),
    text: readString(value.text, 'text'),
    score: rawScore === null || rawScore === undefined ? null : readNumber(rawScore, 'score'),
  };
}

export function parseSourceVaultSearchResponse(value: unknown): SourceVaultSearchResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid Source Vault response: search response must be an object');
  }
  if (!Array.isArray(value.results)) {
    throw new Error('Invalid Source Vault response: results must be an array');
  }
  const projectId = value.project_id;
  if (projectId !== null && projectId !== undefined && typeof projectId !== 'string') {
    throw new Error('Invalid Source Vault response: project_id must be a string or null');
  }
  return {
    query: readString(value.query, 'query'),
    project_id: projectId ?? null,
    results: value.results.map(parseSourceVaultSearchResult),
  };
}

export async function getSourceVaultOverview(limit = 50): Promise<SourceVaultOverview> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
    throw new Error('limit must be an integer between 1 and 200');
  }
  const { data } = await axios.get<unknown>(`${API_BASE}/api/knowledge/source-vault`, {
    params: { limit },
  });
  return parseSourceVaultOverview(data);
}

export async function searchSourceVaultChunks(
  query: string,
  options: { projectId?: string | null; limit?: number } = {},
): Promise<SourceVaultSearchResponse> {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    throw new Error('query must not be empty');
  }
  const limit = options.limit ?? 20;
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('limit must be an integer between 1 and 100');
  }
  const projectId = options.projectId?.trim() ?? '';
  const { data } = await axios.get<unknown>(`${API_BASE}/api/knowledge/source-vault/search`, {
    params: {
      q: normalizedQuery,
      limit,
      ...(projectId ? { project_id: projectId } : {}),
    },
  });
  return parseSourceVaultSearchResponse(data);
}
