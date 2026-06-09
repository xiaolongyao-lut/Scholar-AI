/**
 * Inspiration Service
 * HTTP client for the inspiration/spark API endpoints
 */

import axios, { AxiosInstance } from "axios";
import { getApiBaseUrl } from "./apiBaseUrl";
import { toBackendLLMConfig } from "./chatApi";
import { getLLMConfig } from "./settingsStore";
import type { InspirationSpark, ContinuationContext } from "@/types/writing";
import { isPdfBboxUnit, readPdfBbox, type PdfBboxUnit } from "@/lib/pdfAnchor";

interface InspirationEvidenceRef {
  ref_id?: string;
  chunk_id: string;
  material_id: string;
  text: string;
  compressed_text?: string;
  quote?: string;
  label?: string;
  score?: number | null;
  page?: number | null;
  source?: string | null;
  source_label?: string | null;
  source_labels: string[];
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  created_at?: string;
  updated_at?: string;
}

interface InspirationEvidenceRefsResponse {
  refs: InspirationEvidenceRef[];
  total: number;
  filtered_by_labels: string[];
}

interface ListEvidenceRefsOptions {
  sourceLabels?: readonly string[];
  page?: number;
  pageSize?: number;
}

type EvidenceRefsExportFormat = "json" | "csv";

interface ExportEvidenceRefsOptions {
  format?: EvidenceRefsExportFormat;
  materialId?: string;
  sourceLabels?: readonly string[];
}

interface ExportEvidenceRefsResult {
  blob: Blob;
  filename: string;
  format: EvidenceRefsExportFormat;
}

interface GenerateSparksResponse {
  sparks: InspirationSpark[];
  total: number;
}

interface GenerateSparksOptions {
  projectReasoningBiasEnabled?: boolean;
  signal?: AbortSignal;
}

interface AgentDispatchResponse {
  query: string;
  tool_calls: Array<{ tool: string; input: Record<string, unknown>; status: string; error?: string }>;
  results: unknown[];
  summary: string;
}

interface AgentToolsResponse {
  tools: Array<{ name: string; description: string; parameters: Record<string, string> }>;
  llm_available: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readNullableString(value: unknown): string | null | undefined {
  if (value === null) return null;
  return typeof value === "string" ? value : undefined;
}

function readNullableNumber(value: unknown): number | null | undefined {
  if (value === null) return null;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function readNumberArray(value: unknown): number[] | null | undefined {
  if (value === null) return null;
  const bbox = readPdfBbox(value);
  return bbox ? [...bbox] : undefined;
}

function readNullableBboxUnit(value: unknown): PdfBboxUnit | null | undefined {
  if (value === null) return null;
  return isPdfBboxUnit(value) ? value : undefined;
}

function normalizePositiveInt(value: number | undefined, fallback: number, min: number, max: number): number {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`Expected integer in range ${min}-${max}`);
  }
  return value;
}

function parseAttachmentFilename(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const match = value.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const rawFilename = match?.[1] ?? match?.[2];
  if (!rawFilename) return fallback;
  try {
    const decoded = decodeURIComponent(rawFilename.trim());
    return decoded && !decoded.includes("/") && !decoded.includes("\\") ? decoded : fallback;
  } catch {
    const trimmed = rawFilename.trim();
    return trimmed && !trimmed.includes("/") && !trimmed.includes("\\") ? trimmed : fallback;
  }
}

function parseEvidenceRef(value: unknown): InspirationEvidenceRef | null {
  if (!isRecord(value)) return null;
  const chunkId = readString(value.chunk_id).trim();
  const materialId = readString(value.material_id).trim();
  const text = readString(value.text).trim();
  if (!chunkId || !materialId) return null;

  const ref: InspirationEvidenceRef = {
    ref_id: readOptionalString(value.ref_id),
    chunk_id: chunkId,
    material_id: materialId,
    text,
    compressed_text: readOptionalString(value.compressed_text),
    quote: readOptionalString(value.quote),
    label: readOptionalString(value.label),
    score: readNullableNumber(value.score),
    page: readNullableNumber(value.page),
    source: readNullableString(value.source),
    source_label: readNullableString(value.source_label),
    source_labels: readStringArray(value.source_labels),
    bbox: readNumberArray(value.bbox),
    bbox_unit: readNullableBboxUnit(value.bbox_unit),
    created_at: readOptionalString(value.created_at),
    updated_at: readOptionalString(value.updated_at),
  };
  return ref;
}

function parseEvidenceRefsResponse(value: unknown): InspirationEvidenceRefsResponse {
  if (!isRecord(value)) {
    throw new Error("Invalid inspiration evidence refs response");
  }
  const refs = Array.isArray(value.refs)
    ? value.refs.flatMap((item) => {
        const ref = parseEvidenceRef(item);
        return ref ? [ref] : [];
      })
    : [];
  const total = typeof value.total === "number" && Number.isFinite(value.total) ? value.total : refs.length;
  return {
    refs,
    total,
    filtered_by_labels: readStringArray(value.filtered_by_labels),
  };
}

class InspirationService {
  private http: AxiosInstance;

  constructor(baseURL?: string) {
    this.http = axios.create({
      baseURL: baseURL || getApiBaseUrl(),
      timeout: 120_000,
      headers: { "Content-Type": "application/json" },
    });
  }

  /** 生成启发点 */
  async generateSparks(
    query: string,
    limit = 10,
    projectId?: string,
    options: GenerateSparksOptions = {},
  ): Promise<InspirationSpark[]> {
    const { data } = await this.http.post<GenerateSparksResponse>(
      "/inspiration/generate",
      {
        query,
        limit,
        project_id: projectId ?? null,
        project_reasoning_bias_enabled: options.projectReasoningBiasEnabled,
        llm: toBackendLLMConfig(getLLMConfig()),
      },
      { signal: options.signal },
    );
    return data.sparks;
  }

  /** 获取启发点续写上下文 */
  async getSparkContext(sparkId: string): Promise<ContinuationContext> {
    const { data } = await this.http.get<ContinuationContext>(
      `/inspiration/${encodeURIComponent(sparkId)}/context`
    );
    return data;
  }

  /** 重新加载启发引擎 */
  async reloadEngine(): Promise<void> {
    await this.http.post("/inspiration/reload");
  }

  /**
   * Loads the independent Inspiration evidence-ref index.
   *
   * The backend accepts repeated `source_labels` query parameters; labels are
   * trimmed and empty values are dropped before the request is sent.
   */
  async listEvidenceRefs(options: ListEvidenceRefsOptions = {}): Promise<InspirationEvidenceRefsResponse> {
    const page = normalizePositiveInt(options.page, 1, 1, Number.MAX_SAFE_INTEGER);
    const pageSize = normalizePositiveInt(options.pageSize, 12, 1, 100);
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    for (const label of options.sourceLabels ?? []) {
      const normalized = label.trim();
      if (normalized) params.append("source_labels", normalized);
    }
    const { data } = await this.http.get<unknown>(`/api/inspiration/evidence_refs?${params.toString()}`);
    return parseEvidenceRefsResponse(data);
  }

  /**
   * Downloads the canonical evidence-ref export sidecar.
   *
   * The backend owns filtering and serialization; the caller owns object-URL
   * creation so UI tests can verify the download handoff without a browser
   * download manager.
   */
  async exportEvidenceRefs(options: ExportEvidenceRefsOptions = {}): Promise<ExportEvidenceRefsResult> {
    const format = options.format ?? "json";
    const params = new URLSearchParams();
    params.set("format", format);
    const materialId = options.materialId?.trim();
    if (materialId) params.set("material_id", materialId);
    for (const label of options.sourceLabels ?? []) {
      const normalized = label.trim();
      if (normalized) params.append("source_labels", normalized);
    }

    const { data, headers } = await this.http.get<Blob>(
      `/api/evidence_refs/export?${params.toString()}`,
      { responseType: "blob" },
    );
    const fallback = format === "csv" ? "evidence_refs_export.csv" : "evidence_refs_export.json";
    return {
      blob: data,
      filename: parseAttachmentFilename(headers?.["content-disposition"], fallback),
      format,
    };
  }

  /** AI 自由调度 */
  async agentDispatch(query: string): Promise<AgentDispatchResponse> {
    const { data } = await this.http.post<AgentDispatchResponse>(
      "/agent/dispatch",
      { query }
    );
    return data;
  }

  /** 列出 AI 引擎可用工具 */
  async listAgentTools(): Promise<AgentToolsResponse> {
    const { data } = await this.http.get<AgentToolsResponse>("/agent/tools");
    return data;
  }
}

let _instance: InspirationService | null = null;

export function getInspirationService(): InspirationService {
  if (!_instance) {
    _instance = new InspirationService();
  }
  return _instance;
}

export type {
  InspirationService,
  GenerateSparksResponse,
  GenerateSparksOptions,
  AgentDispatchResponse,
  AgentToolsResponse,
  EvidenceRefsExportFormat,
  ExportEvidenceRefsOptions,
  ExportEvidenceRefsResult,
  InspirationEvidenceRef,
  InspirationEvidenceRefsResponse,
  ListEvidenceRefsOptions,
};
