import axios from 'axios';

const API_BASE = '/api/discussion';

export interface AgentRole {
  value: 'proponent' | 'opponent' | 'reviewer' | 'moderator';
}

export interface CreateDiscussionRequest {
  topic: string;
  roles: string[];
  max_turns?: number;
}

export interface CreateDiscussionResponse {
  session_id: string;
  topic: string;
  roles: string[];
  max_turns: number;
}

export interface DiscussionMessage {
  id: string;
  role: string;
  message_type: string;
  content: string;
  timestamp: string;
  metadata: Record<string, any>;
}

export interface DiscussionStatusResponse {
  session_id: string;
  topic: string;
  status: string;
  current_turn: number;
  total_messages: number;
  synthesis: string | null;
}

export interface DiscussionHistoryResponse {
  session_id: string;
  messages: DiscussionMessage[];
}

export interface RunTurnResponse {
  session_id: string;
  turn_number: number;
  messages: DiscussionMessage[];
  status: string;
}

export const discussionApi = {
  async createDiscussion(req: CreateDiscussionRequest): Promise<CreateDiscussionResponse> {
    const response = await axios.post(`${API_BASE}/create`, req);
    return response.data;
  },

  async getStatus(sessionId: string): Promise<DiscussionStatusResponse> {
    const response = await axios.get(`${API_BASE}/${sessionId}/status`);
    return response.data;
  },

  async getHistory(sessionId: string): Promise<DiscussionHistoryResponse> {
    const response = await axios.get(`${API_BASE}/${sessionId}/history`);
    return response.data;
  },

  async runTurn(sessionId: string): Promise<RunTurnResponse> {
    const response = await axios.post(`${API_BASE}/${sessionId}/run`);
    return response.data;
  },
};
