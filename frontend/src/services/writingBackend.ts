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
import {
  WritingProject,
  WritingSection,
  WritingDraft,
  WritingRevision,
  BuildAssociationRequest,
  WritingAssociationBundle,
  CreateProjectRequest,
  CreateSectionRequest,
  CreateDraftRequest,
  SaveDraftRequest,
  ProjectStatus,
} from "../types/resources";

export class WritingBackendService {
  private readonly client: AxiosInstance;

  constructor(baseURL: string = "http://localhost:8000") {
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
    const params: any = { project_id: projectId };
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

  async listWritingActions(): Promise<any[]> {
    const response = await this.client.get("/skills");
    return response.data;
  }

  async runWritingAction(payload: any): Promise<any> {
    const response = await this.client.post("/runtime/job", payload);
    return response.data;
  }

  async getTransformResult(jobId: string): Promise<any> {
    const response = await this.client.get(`/runtime/job/${jobId}/artifacts`);
    return response.data;
  }

  // =========================================================================
  // Material Operations (Knowledge Base)
  // =========================================================================

  async listMaterials(projectId: string): Promise<any[]> {
    const response = await this.client.get("/resources/materials", {
      params: { project_id: projectId },
    });
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
