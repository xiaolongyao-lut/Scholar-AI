/**
 * Inspiration Service
 * HTTP client for the inspiration/spark API endpoints
 */

import axios, { AxiosInstance } from "axios";
import { getApiBaseUrl } from "./apiBaseUrl";
import type { InspirationSpark, ContinuationContext } from "@/types/writing";

interface GenerateSparksResponse {
  sparks: InspirationSpark[];
  total: number;
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

class InspirationService {
  private http: AxiosInstance;

  constructor(baseURL?: string) {
    this.http = axios.create({
      baseURL: baseURL || getApiBaseUrl(),
      timeout: 30_000,
      headers: { "Content-Type": "application/json" },
    });
  }

  /** 生成启发点 */
  async generateSparks(query: string, limit = 10, projectId?: string): Promise<InspirationSpark[]> {
    const { data } = await this.http.post<GenerateSparksResponse>(
      "/inspiration/generate",
      { query, limit, project_id: projectId ?? null }
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

export type { InspirationService, GenerateSparksResponse, AgentDispatchResponse, AgentToolsResponse };
