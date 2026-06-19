/**
 * Writing Backend Service
 * HTTP client for consuming writing resources API.
 *
 * Provides typed interface to backend resource layer:
 * - Projects: create, get, list, update status
 * - Sections: create, get, list
 * - Drafts: create, get, list, save
 * - Revisions: get, list, restore
 */

import type { AxiosInstance, AxiosRequestConfig } from "axios";
import { getApiBaseUrl } from "./apiBaseUrl";
import { createApiClient } from "./httpClient";
import {
  WritingProject,
  WritingSection,
  WritingMaterialResource,
  ProjectDocumentResource,
  ProjectChunksResponse,
  MaterialChunksResponse,
  FigureTableCandidateResource,
  FigureAssetResource,
  CreateFigureAssetRequest,
  UpdateFigureAssetRequest,
  CitationSourceResource,
  CitationSourceUpdate,
  CitationSuggestionResource,
  SuggestCitationsRequest,
  WritingDraft,
  WritingRevision,
  BuildAssociationRequest,
  WritingAssociationBundle,
  CreateProjectRequest,
  CreateSectionRequest,
  CreateMaterialRequest,
  CreateDraftRequest,
  SaveDraftRequest,
  OutlineResource,
  GenerateOutlineRequest,
  ProjectStatus,
  WritingActionResource,
  ProjectExportFormat,
  ProjectExportResponseEnvelope,
  AcademicWritingLintRequest,
  AcademicWritingLintResponse,
  JournalStyleSpecConfirmResponse,
  JournalStyleSpecDraftResponse,
  SubmitForReviewRequest,
  SubmissionResponseResource,
  ProjectStats,
  GlobalStats,
  VolumeSummary,
  VolumeAnalysisResult,
  BatchDeleteResult,
  UpdateProjectRequest,
  UpdateSectionRequest,
  ModelInfo,
} from "../types/resources";
import {
  CreateJobRequest,
  WritingArtifact,
  WritingJob,
} from "../types/runtime";

export const WRITING_EXPORT_FORMATS = [
  "markdown",
  "json",
  "word",
  "latex",
  "pdf",
] as const;

export type WritingExportFormat = (typeof WRITING_EXPORT_FORMATS)[number];

export const WRITING_DOCUMENT_EXPORT_FORMATS = [
  "latex",
  "markdown",
  "word",
] as const satisfies readonly WritingExportFormat[];

export type WritingDocumentExportFormat = (typeof WRITING_DOCUMENT_EXPORT_FORMATS)[number];

const EXPORT_MIME_BY_FORMAT: Record<WritingExportFormat, string> = {
  markdown: "text/markdown;charset=utf-8",
  json: "application/json;charset=utf-8",
  word: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  latex: "application/x-tex;charset=utf-8",
  pdf: "application/pdf",
};

const EXPORT_EXTENSION_BY_FORMAT: Record<WritingExportFormat, string> = {
  markdown: "md",
  json: "json",
  word: "docx",
  latex: "tex",
  pdf: "pdf",
};

function isWritingExportFormat(value: string): value is WritingExportFormat {
  return WRITING_EXPORT_FORMATS.includes(value as WritingExportFormat);
}

function resolveExportFormat(
  result: ProjectExportResponseEnvelope,
  requestedFormat?: WritingExportFormat,
): WritingExportFormat {
  if (requestedFormat && isWritingExportFormat(requestedFormat)) {
    return requestedFormat;
  }
  if (isWritingExportFormat(String(result.format))) {
    return result.format as WritingExportFormat;
  }
  throw new Error(`Unsupported export format: ${String(result.format)}`);
}

function normalizeExportFilename(filename: string | null | undefined, extension: string): string {
  if (!extension.trim()) {
    throw new Error("export extension is required");
  }
  const safeExtension = extension.replace(/^\.+/, "");
  const fallback = `project-export.${safeExtension}`;
  const trimmed = typeof filename === "string" ? filename.trim() : "";
  if (!trimmed) {
    return fallback;
  }
  if (new RegExp(`\\.${safeExtension}$`, "i").test(trimmed)) {
    return trimmed;
  }
  return `${trimmed.replace(/\.[A-Za-z0-9]{1,8}$/, "")}.${safeExtension}`;
}

function decodeBase64ToBytes(value: string): Uint8Array {
  if (!value.trim()) {
    throw new Error("content_base64 is empty");
  }
  const binary = globalThis.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function blobToBase64(blob: Blob): Promise<string> {
  if (!(blob instanceof Blob)) {
    throw new TypeError("blob must be a Blob");
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read export blob"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Export blob reader returned a non-string result"));
        return;
      }
      const [, base64 = ""] = result.split(",", 2);
      if (!base64) {
        reject(new Error("Export blob reader returned empty base64 content"));
        return;
      }
      resolve(base64);
    };
    reader.readAsDataURL(blob);
  });
}

export function buildProjectExportBlob(
  result: ProjectExportResponseEnvelope,
  requestedFormat?: WritingExportFormat,
): { blob: Blob; filename: string } {
  const normalizedFormat = resolveExportFormat(result, requestedFormat);
  const resultFormat = isWritingExportFormat(String(result.format))
    ? result.format as WritingExportFormat
    : null;
  const mediaType = resultFormat === normalizedFormat && result.media_type
    ? result.media_type
    : EXPORT_MIME_BY_FORMAT[normalizedFormat];
  const extension = EXPORT_EXTENSION_BY_FORMAT[normalizedFormat];
  const filename = normalizeExportFilename(result.filename, extension);
  const canUseEncodedPayload = Boolean(result.content_base64)
    && (resultFormat === null || resultFormat === normalizedFormat);
  if (canUseEncodedPayload && result.content_base64) {
    return {
      blob: new Blob([decodeBase64ToBytes(result.content_base64)], { type: mediaType }),
      filename,
    };
  }
  if (resultFormat && resultFormat !== normalizedFormat && normalizedFormat !== "json") {
    throw new Error(`Cannot build ${normalizedFormat} export from ${resultFormat} payload`);
  }
  const content = normalizedFormat === "json"
    ? JSON.stringify(result, null, 2)
    : result.content || "";
  return {
    blob: new Blob([content], { type: mediaType }),
    filename,
  };
}

export async function downloadProjectExportBlob(
  result: ProjectExportResponseEnvelope,
  requestedFormat?: WritingExportFormat,
): Promise<string | null> {
  const { blob, filename } = buildProjectExportBlob(result, requestedFormat);
  const nativeSaveBytes = globalThis.window?.pywebview?.api?.save_bytes;
  if (nativeSaveBytes) {
    const contentBase64 = await blobToBase64(blob);
    return (await nativeSaveBytes(filename, contentBase64)) ?? null;
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  return null;
}

export async function resolveProjectExportForDownload(
  currentData: ProjectExportResponseEnvelope,
  requestedFormat: WritingExportFormat,
  projectId: string,
  fetchExport: (projectId: string, format: WritingExportFormat) => Promise<ProjectExportResponseEnvelope>,
): Promise<ProjectExportResponseEnvelope> {
  if (!projectId.trim()) {
    throw new Error("projectId is required to resolve an export download");
  }
  const currentFormat = isWritingExportFormat(String(currentData.format))
    ? currentData.format as WritingExportFormat
    : null;
  if (currentFormat === requestedFormat) {
    return currentData;
  }
  return fetchExport(projectId, requestedFormat);
}

export function buildFigureAssetFileUrl(projectId: string, assetPath: string): string {
  const normalizedProjectId = projectId.trim();
  const normalizedAssetPath = assetPath.trim();
  if (!normalizedProjectId) {
    throw new Error("projectId is required to build a figure asset URL");
  }
  if (!normalizedAssetPath) {
    throw new Error("assetPath is required to build a figure asset URL");
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams({
    project_id: normalizedProjectId,
    path: normalizedAssetPath,
  });
  return `${baseUrl}/api/writing/figures/file?${params.toString()}`;
}

export interface GenerateFigureAssetsRequest {
  project_id: string;
  candidate_ids?: string[];
  max_items?: number;
  kind?: "figure" | "table";
  overwrite_existing?: boolean;
}

export interface GenerateFigureAssetsResponse {
  project_id: string;
  generated_count: number;
  generated_assets: FigureAssetResource[];
  skipped_candidate_ids: string[];
  message: string;
}

export interface DraftJournalStyleSpecRequest {
  project_id: string;
  journal_name: string;
  spec_text: string;
}

export interface ConfirmJournalStyleSpecRequest {
  project_id: string;
  draft_id: string;
  confirmed_by?: string;
}

export class WritingBackendService {
  private readonly client: AxiosInstance;

  constructor(baseURL: string = getApiBaseUrl()) {
    this.client = createApiClient({
      baseURL,
      retry: {
        maxAttempts: 2,
        statuses: [408, 425, 429, 500, 502, 503, 504],
        methods: ["get", "head", "options"],
      },
    });
  }

  // =========================================================================
  // Project Operations
  // =========================================================================

  /**
   * Create a new writing project.
   */
  async createProject(request: CreateProjectRequest): Promise<WritingProject> {
    const response = await this.client.post<WritingProject>(
      "/api/writing/projects",
      request
    );
    return response.data;
  }

  /**
   * Get a project by ID.
   */
  async getProject(projectId: string): Promise<WritingProject> {
    const response = await this.client.get<WritingProject>(
      `/api/writing/projects/${projectId}`
    );
    return response.data;
  }

  /**
   * List all projects, optionally filtered by user.
   */
  async listProjects(userId?: string): Promise<WritingProject[]> {
    const params = userId ? { user_id: userId } : {};
    const response = await this.client.get<WritingProject[]>(
      "/api/writing/projects",
      { params }
    );
    return response.data;
  }

  /**
   * Update project status.
   */
  async updateProjectStatus(
    projectId: string,
    status: ProjectStatus
  ): Promise<WritingProject> {
    const response = await this.client.put<WritingProject>(
      `/api/writing/projects/${projectId}/status`,
      null,
      { params: { status: status } }
    );
    return response.data;
  }

  /**
   * Delete a project and all its associated resources.
   */
  async deleteProject(projectId: string): Promise<void> {
    await this.client.delete(`/api/writing/projects/${projectId}`);
  }

  /**
   * Update the source folder path for a project.
   * Chunks and docs will be stored under {source_folder}/.scholarai/ going forward.
   */
  async updateProjectSourceFolder(projectId: string, sourceFolder: string): Promise<WritingProject> {
    const response = await this.client.put<WritingProject>(
      `/resources/project/${projectId}/source-folder`,
      null,
      { params: { source_folder: sourceFolder } }
    );
    return response.data;
  }

  /**
   * Scan literature files in source_folder with pluggable execution modes.
   * - scanMode: 'fast' | 'legacy'
   * - batchSize/maxWorkers: effective when scanMode='fast'
   */
  async scanProjectFolder(
    projectId: string,
    options?: { scanMode?: 'fast' | 'legacy'; batchSize?: number; maxWorkers?: number; asyncJob?: boolean }
  ): Promise<{
    indexed: number;
    skipped: number;
    failed: number;
    folder: string;
    queued?: number;
    workers?: number;
    scan_mode?: string;
    runtime_job_ref?: {
      session_id: string;
      job_id: string;
      kind: string;
      status: string;
    };
    status_url?: string;
    job_url?: string;
    artifacts_url?: string;
  }> {
    const response = await this.client.post<{
      indexed: number;
      skipped: number;
      failed: number;
      folder: string;
      queued?: number;
      workers?: number;
      scan_mode?: string;
      runtime_job_ref?: {
        session_id: string;
        job_id: string;
        kind: string;
        status: string;
      };
      status_url?: string;
      job_url?: string;
      artifacts_url?: string;
    }>(
      `/resources/project/${projectId}/scan-folder`,
      null,
      {
        params: {
          scan_mode: options?.scanMode,
          batch_size: options?.batchSize,
          max_workers: options?.maxWorkers,
          async_job: options?.asyncJob,
        },
      }
    );
    return response.data;
  }

  // =========================================================================
  // Section Operations
  // =========================================================================

  /**
   * Create a section within a project.
   */
  async createSection(request: CreateSectionRequest): Promise<WritingSection> {
    const response = await this.client.post<WritingSection>(
      "/resources/section",
      request
    );
    return response.data;
  }

  /**
   * Get a section by ID.
   */
  async getSection(sectionId: string): Promise<WritingSection> {
    const response = await this.client.get<WritingSection>(
      `/resources/section/${sectionId}`
    );
    return response.data;
  }

  /**
   * List all sections in a project.
   */
  async listSections(projectId: string): Promise<WritingSection[]> {
    const response = await this.client.get<WritingSection[]>(
      "/resources/sections",
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  /**
   * Get the section-backed outline for a project.
   */
  async getOutline(projectId: string): Promise<OutlineResource> {
    const response = await this.client.get<OutlineResource>(
      "/api/writing/outline",
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  /**
   * Generate and persist outline sections for a project.
   */
  async generateOutline(
    request: GenerateOutlineRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<OutlineResource> {
    const response = await this.client.post<OutlineResource>(
      "/api/writing/outline/generate",
      request,
      { signal: options.signal }
    );
    return response.data;
  }

  /**
   * Persist the ordered section-backed outline for a project.
   */
  async updateOutline(
    projectId: string,
    items: OutlineResource["items"] = []
  ): Promise<OutlineResource> {
    const response = await this.client.put<OutlineResource>(
      "/api/writing/outline",
      items,
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  /**
   * Delete an outline item by its item/section identifier.
   */
  async deleteOutlineItem(itemId: string): Promise<void> {
    await this.client.delete(`/api/writing/outline/${encodeURIComponent(itemId)}`);
  }

  // =========================================================================
  // Draft Operations
  // =========================================================================

  /**
   * Create a new draft.
   */
  async createDraft(request: CreateDraftRequest): Promise<WritingDraft> {
    const response = await this.client.post<WritingDraft>(
      "/resources/draft",
      request
    );
    return response.data;
  }

  /**
   * Get a draft by ID.
   */
  async getDraft(draftId: string): Promise<WritingDraft> {
    const response = await this.client.get<WritingDraft>(
      `/resources/draft/${draftId}`
    );
    return response.data;
  }

  /**
   * List all drafts, optionally filtered by section.
   */
  async listDrafts(
    projectId: string,
    sectionId?: string
  ): Promise<WritingDraft[]> {
    const params: { project_id: string; section_id?: string } = {
      project_id: projectId,
    };
    if (sectionId) {
      params.section_id = sectionId;
    }
    const response = await this.client.get<WritingDraft[]>(
      "/resources/drafts",
      { params }
    );
    return response.data;
  }

  /**
   * Save draft content. Auto-creates a revision.
   */
  async saveDraft(
    draftId: string,
    request: SaveDraftRequest
  ): Promise<WritingDraft> {
    const response = await this.client.put<WritingDraft>(
      `/resources/draft/${draftId}`,
      request
    );
    return response.data;
  }

  // =========================================================================
  // Revision Operations
  // =========================================================================

  /**
   * Get a revision by ID.
   */
  async getRevision(revisionId: string): Promise<WritingRevision> {
    const response = await this.client.get<WritingRevision>(
      `/resources/revision/${revisionId}`
    );
    return response.data;
  }

  /**
   * List all revisions for a draft.
   */
  async listRevisions(draftId: string): Promise<WritingRevision[]> {
    const response = await this.client.get<WritingRevision[]>(
      "/resources/revisions",
      { params: { draft_id: draftId } }
    );
    return response.data;
  }

  /**
   * Restore a draft from a revision.
   */
  async restoreRevision(
    draftId: string,
    revisionId: string
  ): Promise<WritingDraft> {
    const response = await this.client.post<WritingDraft>(
      `/resources/draft/${draftId}/restore`,
      null,
      { params: { revision_id: revisionId } }
    );
    return response.data;
  }

  /**
   * Build associative-writing guidance from project context and memory.
   */
  async buildAssociation(
    request: BuildAssociationRequest
  ): Promise<WritingAssociationBundle> {
    const response = await this.client.post<WritingAssociationBundle>(
      "/resources/association",
      request
    );
    return response.data;
  }

  // =========================================================================
  // Capability & Action Operations
  // =========================================================================

  async listWritingActions(): Promise<WritingActionResource[]> {
    const response = await this.client.get<WritingActionResource[]>("/actions");
    return response.data;
  }

  async runWritingAction(payload: CreateJobRequest): Promise<WritingJob> {
    const response = await this.client.post<WritingJob>("/runtime/job", payload);
    return response.data;
  }

  async getTransformResult(jobId: string): Promise<WritingArtifact[]> {
    const response = await this.client.get<WritingArtifact[]>(
      `/runtime/job/${jobId}/artifacts`
    );
    return response.data;
  }

  // =========================================================================
  // Material Operations (Knowledge Base)
  // =========================================================================

  async createMaterial(
    request: CreateMaterialRequest
  ): Promise<WritingMaterialResource> {
    const response = await this.client.post<WritingMaterialResource>(
      "/resources/material",
      request
    );
    return response.data;
  }

  async listMaterials(projectId: string): Promise<WritingMaterialResource[]> {
    const response = await this.client.get<WritingMaterialResource[]>(
      "/resources/materials",
      {
      params: { project_id: projectId },
      }
    );
    return response.data;
  }

  async listDocuments(projectId: string): Promise<ProjectDocumentResource[]> {
    const response = await this.client.get<ProjectDocumentResource[]>(
      "/resources/documents",
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  async listProjectChunks(
    projectId: string,
    materialId?: string
  ): Promise<ProjectChunksResponse> {
    const response = await this.client.get<ProjectChunksResponse>(
      "/resources/chunks",
      {
        params: {
          project_id: projectId,
          material_id: materialId,
        },
      }
    );
    return response.data;
  }

  async listMaterialChunks(
    projectId: string,
    materialId: string
  ): Promise<MaterialChunksResponse> {
    const response = await this.client.get<MaterialChunksResponse>(
      `/resources/material/${materialId}/chunks`,
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  async listFigureTableCandidates(
    projectId: string,
    limit: number = 96,
    options: { pixelOnly?: boolean; renderPdfFallback?: boolean } = {},
  ): Promise<FigureTableCandidateResource[]> {
    const response = await this.client.get<FigureTableCandidateResource[]>(
      "/api/writing/figures/candidates",
      {
        params: {
          project_id: projectId,
          limit,
          pixel_only: options.pixelOnly,
          render_pdf_fallback: options.renderPdfFallback,
        },
      }
    );
    return response.data;
  }

  async listFigureAssets(projectId: string): Promise<FigureAssetResource[]> {
    const response = await this.client.get<FigureAssetResource[]>(
      "/api/writing/figures",
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  async createFigureAsset(
    request: CreateFigureAssetRequest
  ): Promise<FigureAssetResource> {
    const response = await this.client.post<FigureAssetResource>(
      "/api/writing/figures",
      request
    );
    return response.data;
  }

  async updateFigureAsset(
    assetId: string,
    request: UpdateFigureAssetRequest
  ): Promise<FigureAssetResource> {
    const response = await this.client.put<FigureAssetResource>(
      `/api/writing/figures/${assetId}`,
      request
    );
    return response.data;
  }

  async deleteFigureAsset(assetId: string): Promise<void> {
    await this.client.delete(`/api/writing/figures/${assetId}`);
  }

  async generateFigureAssets(
    request: GenerateFigureAssetsRequest
  ): Promise<GenerateFigureAssetsResponse> {
    const response = await this.client.post<GenerateFigureAssetsResponse>(
      "/api/writing/figures/generate",
      request
    );
    return response.data;
  }

  async listCitationSources(projectId: string): Promise<CitationSourceResource[]> {
    const response = await this.client.get<CitationSourceResource[]>(
      "/api/writing/citations/sources",
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  async updateCitationSource(
    sourceId: string,
    update: CitationSourceUpdate,
  ): Promise<CitationSourceResource> {
    const response = await this.client.put<CitationSourceResource>(
      `/api/writing/citations/sources/${encodeURIComponent(sourceId)}`,
      update,
    );
    return response.data;
  }

  async suggestCitations(
    request: SuggestCitationsRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<CitationSuggestionResource[]> {
    const response = await this.client.post<CitationSuggestionResource[]>(
      "/api/writing/citations/suggest",
      request,
      { signal: options.signal }
    );
    return response.data;
  }

  // =========================================================================
  // Delete Operations
  // =========================================================================

  /**
   * Delete a single material.
   */
  async deleteMaterial(materialId: string): Promise<void> {
    await this.client.delete(`/resources/material/${materialId}`);
  }

  /**
   * Batch delete materials.
   */
  async batchDeleteMaterials(
    materialIds: string[]
  ): Promise<BatchDeleteResult> {
    const response = await this.client.post<BatchDeleteResult>(
      "/resources/materials/batch-delete",
      { material_ids: materialIds }
    );
    return response.data;
  }

  /**
   * Delete a draft.
   */
  async deleteDraft(draftId: string): Promise<void> {
    await this.client.delete(`/resources/draft/${draftId}`);
  }

  /**
   * Delete a section.
   */
  async deleteSection(sectionId: string): Promise<void> {
    await this.client.delete(`/resources/section/${sectionId}`);
  }

  // =========================================================================
  // Update Operations
  // =========================================================================

  /**
   * Update project fields (title, description, tags).
   */
  async updateProject(
    projectId: string,
    request: UpdateProjectRequest
  ): Promise<WritingProject> {
    const response = await this.client.put<WritingProject>(
      `/resources/project/${projectId}`,
      request
    );
    return response.data;
  }

  /**
   * Update section fields (title, description, order).
   */
  async updateSection(
    sectionId: string,
    request: UpdateSectionRequest
  ): Promise<WritingSection> {
    const response = await this.client.put<WritingSection>(
      `/resources/section/${sectionId}`,
      request
    );
    return response.data;
  }

  // =========================================================================
  // Export Operations
  // =========================================================================

  /**
   * Export project content in the given format.
   */
  async exportProject(
    projectId: string,
    format: ProjectExportFormat = "markdown",
    options: { signal?: AbortSignal; styleProfile?: string | null } = {},
  ): Promise<ProjectExportResponseEnvelope> {
    const response = await this.client.post<ProjectExportResponseEnvelope>(
      "/api/writing/export",
      {
        project_id: projectId,
        format,
        include_evidence: true,
        include_citations: true,
        style_profile: options.styleProfile || null,
      },
      { signal: options.signal },
    );
    return response.data;
  }

  /**
   * Create a reviewable journal style profile draft from pasted official requirements.
   */
  async draftJournalStyleSpec(
    request: DraftJournalStyleSpecRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<JournalStyleSpecDraftResponse> {
    const response = await this.client.post<JournalStyleSpecDraftResponse>(
      "/api/export/journal-style-specs/draft",
      request,
      { signal: options.signal },
    );
    return response.data;
  }

  /**
   * Create a reviewable journal style profile draft from a bounded text/Markdown file.
   */
  async uploadJournalStyleSpec(
    projectId: string,
    journalName: string,
    file: File,
    options: { signal?: AbortSignal } = {},
  ): Promise<JournalStyleSpecDraftResponse> {
    const normalizedProjectId = projectId.trim();
    const normalizedJournalName = journalName.trim();
    if (!normalizedProjectId) {
      throw new Error("projectId is required to upload a journal style spec");
    }
    if (!normalizedJournalName) {
      throw new Error("journalName is required to upload a journal style spec");
    }
    if (!(file instanceof File)) {
      throw new TypeError("file must be a File");
    }

    const formData = new FormData();
    formData.append("project_id", normalizedProjectId);
    formData.append("journal_name", normalizedJournalName);
    formData.append("file", file, file.name);
    const response = await this.client.post<JournalStyleSpecDraftResponse>(
      "/api/export/journal-style-specs/upload",
      formData,
      { signal: options.signal },
    );
    return response.data;
  }

  /**
   * Confirm a project-scoped journal style draft for later Word export.
   */
  async confirmJournalStyleSpec(
    request: ConfirmJournalStyleSpecRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<JournalStyleSpecConfirmResponse> {
    const response = await this.client.post<JournalStyleSpecConfirmResponse>(
      "/api/export/journal-style-specs/confirm",
      {
        project_id: request.project_id,
        draft_id: request.draft_id,
        confirmed_by: request.confirmed_by || "frontend-user",
      },
      { signal: options.signal },
    );
    return response.data;
  }

  /**
   * Run the deterministic academic-writing audit gate before AI review/export.
   */
  async lintAcademicWriting(
    request: AcademicWritingLintRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AcademicWritingLintResponse> {
    const text = typeof request.text === "string" ? request.text.trim() : "";
    const html = typeof request.html === "string" ? request.html.trim() : "";
    if (!text && !html) {
      throw new Error("text or html is required to lint academic writing");
    }
    const response = await this.client.post<AcademicWritingLintResponse>(
      "/api/linter/academic-writing",
      request,
      { signal: options.signal },
    );
    return response.data;
  }

  /**
   * Package the active writing project for reviewer handoff.
   */
  async submitForReview(
    request: SubmitForReviewRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<SubmissionResponseResource> {
    const response = await this.client.post<SubmissionResponseResource>(
      "/api/writing/submit",
      request,
      { signal: options.signal },
    );
    return response.data;
  }

  // =========================================================================
  // Statistics Operations
  // =========================================================================

  /**
   * Get statistics for a specific project.
   */
  async getProjectStats(projectId: string): Promise<ProjectStats> {
    const response = await this.client.get<ProjectStats>(
      `/resources/project/${projectId}/stats`
    );
    return response.data;
  }

  /**
   * Get global statistics across all projects.
   */
  async getGlobalStats(): Promise<GlobalStats> {
    const response = await this.client.get<GlobalStats>(
      "/resources/stats/overview"
    );
    return response.data;
  }

  // =========================================================================
  // Volume / Cross-paper Analysis Operations
  // =========================================================================

  async listVolumes(): Promise<{ total: number; volumes: VolumeSummary[] }> {
    const response = await this.client.get<{ total: number; volumes: VolumeSummary[] }>(
      "/volumes"
    );
    return response.data;
  }

  async getVolumeAnalysis(
    volumeKey: string,
    refresh: boolean = false,
    options: { signal?: AbortSignal } = {},
  ): Promise<VolumeAnalysisResult> {
    const response = await this.client.get<VolumeAnalysisResult>(
      `/volumes/${volumeKey}/analysis`,
      { params: { refresh }, signal: options.signal }
    );
    return response.data;
  }

  // =========================================================================
  // Batch Processing Operations
  // =========================================================================

  /**
   * Preview or execute historical dirty-data cleanup.
   */
  async cleanupHistoricalData(dryRun: boolean): Promise<{
    dry_run: boolean;
    preview: {
      duplicate_project_count: number;
      empty_material_count: number;
      duplicate_projects: Array<Record<string, unknown>>;
      empty_materials: Array<Record<string, unknown>>;
    };
    deleted: {
      duplicate_project_count: number;
      empty_material_count: number;
      duplicate_projects: string[];
      empty_materials: string[];
    };
  }> {
    const response = await this.client.post<{
      dry_run: boolean;
      preview: {
        duplicate_project_count: number;
        empty_material_count: number;
        duplicate_projects: Array<Record<string, unknown>>;
        empty_materials: Array<Record<string, unknown>>;
      };
      deleted: {
        duplicate_project_count: number;
        empty_material_count: number;
        duplicate_projects: string[];
        empty_materials: string[];
      };
    }>("/resources/maintenance/cleanup", { dry_run: dryRun });
    return response.data;
  }

  /**
   * Submit a batch PDF processing job.
   * Returns a task_id for polling status.
   */
  async submitBatchProcessing(request: {
    pdf_folder: string;
    output_root: string;
    goal: string;
    batch_size?: number;
  }, options: { signal?: AbortSignal } = {}): Promise<{ task_id: string; status: string }> {
    const response = await this.client.post<{ task_id: string; status: string }>(
      "/pipeline/batch/submit",
      request,
      { signal: options.signal }
    );
    return response.data;
  }

  /**
   * Get status of a batch processing task.
   */
  async getBatchTaskStatus(taskId: string): Promise<{
    task_id: string;
    status: string;
    progress: number;
    stage: string;
    result?: Record<string, unknown>;
    error?: string;
  }> {
    const response = await this.client.get<{
      task_id: string;
      status: string;
      progress: number;
      stage: string;
      result?: Record<string, unknown>;
      error?: string;
    }>(`/pipeline/task/${taskId}`);
    return response.data;
  }

  /**
   * Cancel a queued or running pipeline task.
   */
  async cancelPipelineTask(taskId: string): Promise<{
    task_id: string;
    status: string;
    progress: number;
    stage: string;
    result?: Record<string, unknown>;
    error?: string;
  }> {
    const config: AxiosRequestConfig = {};
    const response = await this.client.post<{
      task_id: string;
      status: string;
      progress: number;
      stage: string;
      result?: Record<string, unknown>;
      error?: string;
    }>(`/pipeline/task/${taskId}/cancel`, null, config);
    return response.data;
  }

  // =========================================================================
  // Chat / Model Operations
  // =========================================================================

  /**
   * List supported LLM models.
   */
  async listModels(): Promise<ModelInfo[]> {
    const response = await this.client.get<ModelInfo[]>("/chat/models");
    return response.data;
  }
}

// Global singleton instance
let instance: WritingBackendService | null = null;

/**
 * Get or create the global WritingBackendService instance.
 */
export function getWritingBackendService(
  baseURL?: string
): WritingBackendService {
  if (!instance) {
    instance = new WritingBackendService(baseURL);
  }
  return instance;
}

// Default export for convenience
export default WritingBackendService;

// =========================================================================
// Session Persistence API re-export
// =========================================================================
// Keep a single import entry point for frontend callers. Session APIs live in
// their own module (`sessionApi.ts`) so the persistence scope stays separate,
// but consumers can still resolve them through `writingBackend`.
export {
  SessionApiService,
  getSessionApi,
} from "./sessionApi";
