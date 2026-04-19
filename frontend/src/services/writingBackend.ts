/**
 * Writing Backend Service
 * HTTP client for consuming writing resources API (Phase 3)
 *
 * Provides typed interface to backend resource layer:
 * - Projects: create, get, list, update status
 * - Sections: create, get, list
 * - Drafts: create, get, list, save
 * - Revisions: get, list, restore
 */

import axios, { AxiosInstance } from "axios";
import { getApiBaseUrl } from "./apiBaseUrl";
import {
  WritingProject,
  WritingSection,
  WritingMaterialResource,
  WritingDraft,
  WritingRevision,
  BuildAssociationRequest,
  WritingAssociationBundle,
  CreateProjectRequest,
  CreateSectionRequest,
  CreateMaterialRequest,
  CreateDraftRequest,
  SaveDraftRequest,
  ProjectStatus,
  WritingActionResource,
  ProjectExportFormat,
  ProjectExportResult,
  ProjectStats,
  GlobalStats,
  VolumeSummary,
  VolumeAnalysisResult,
  BatchDeleteRequest,
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

export class WritingBackendService {
  private readonly client: AxiosInstance;

  constructor(baseURL: string = getApiBaseUrl()) {
    this.client = axios.create({
      baseURL,
      headers: {
        "Content-Type": "application/json",
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
      "/resources/project",
      request
    );
    return response.data;
  }

  /**
   * Get a project by ID.
   */
  async getProject(projectId: string): Promise<WritingProject> {
    const response = await this.client.get<WritingProject>(
      `/resources/project/${projectId}`
    );
    return response.data;
  }

  /**
   * List all projects, optionally filtered by user.
   */
  async listProjects(userId?: string): Promise<WritingProject[]> {
    const params = userId ? { user_id: userId } : {};
    const response = await this.client.get<WritingProject[]>(
      "/resources/projects",
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
      `/resources/project/${projectId}/status`,
      null,
      { params: { status: status } }
    );
    return response.data;
  }

  /**
   * Delete a project and all its associated resources.
   */
  async deleteProject(projectId: string): Promise<void> {
    await this.client.delete(`/resources/project/${projectId}`);
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
    options?: { scanMode?: 'fast' | 'legacy'; batchSize?: number; maxWorkers?: number }
  ): Promise<{
    indexed: number;
    skipped: number;
    failed: number;
    folder: string;
    queued?: number;
    workers?: number;
    scan_mode?: string;
  }> {
    const response = await this.client.post<{
      indexed: number;
      skipped: number;
      failed: number;
      folder: string;
      queued?: number;
      workers?: number;
      scan_mode?: string;
    }>(
      `/resources/project/${projectId}/scan-folder`,
      null,
      {
        params: {
          scan_mode: options?.scanMode,
          batch_size: options?.batchSize,
          max_workers: options?.maxWorkers,
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
    format: ProjectExportFormat = "markdown"
  ): Promise<ProjectExportResult> {
    const response = await this.client.get<ProjectExportResult>(
      `/resources/project/${projectId}/export`,
      { params: { format } }
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
    refresh: boolean = false
  ): Promise<VolumeAnalysisResult> {
    const response = await this.client.get<VolumeAnalysisResult>(
      `/volumes/${volumeKey}/analysis`,
      { params: { refresh } }
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
  }): Promise<{ task_id: string; status: string }> {
    const response = await this.client.post<{ task_id: string; status: string }>(
      "/pipeline/batch/submit",
      request
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
