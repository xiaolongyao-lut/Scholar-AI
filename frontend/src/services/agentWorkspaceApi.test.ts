import { beforeEach, describe, expect, it, vi } from 'vitest';

interface ApiRequestConfig {
  params?: Record<string, string | number | boolean | null | undefined>;
}

type MockGet = (url: string, config?: ApiRequestConfig) => Promise<{ data: unknown }>;

const get = vi.hoisted(() => vi.fn<Parameters<MockGet>, ReturnType<MockGet>>());

vi.mock('./httpClient', () => ({
  createDefaultApiClient: () => ({
    get,
  }),
}));

import {
  getAgentHandoffCard,
  getEvidenceIntegrityGate,
  getWorkflowPassport,
} from './agentWorkspaceApi';

const workflowPassportResponse = {
  schema_version: 'scholar_ai_workflow_passport_v1',
  generated_at: '2026-06-25T00:00:00Z',
  scope: {},
  stages: [],
  current_stage_id: null,
  gate_summary: {},
  provenance: {},
};

const evidenceIntegrityGateResponse = {
  schema_version: 'scholar_ai_evidence_integrity_gate_v1',
  generated_at: '2026-06-25T00:00:00Z',
  scope: {},
  status: 'pass',
  signals: [],
  summary: {},
  blockers: [],
  unresolved: [],
  provenance: {},
};

const agentHandoffCardResponse = {
  schema_version: 'scholar_ai_agent_handoff_card_v1',
  generated_at: '2026-06-25T00:00:00Z',
  request_id: null,
  job_id: 'job-42',
  session_id: 'session-42',
  project_id: null,
  status: 'completed',
  agent_host: null,
  intent: null,
  current_stage_id: null,
  completed_evidence: [],
  blockers: [],
  unresolved: [],
  resource_refs: [],
  artifacts: [],
  resume_probes: [],
  forbidden_actions: [],
  resume_prompt: '',
  provenance: {},
};

beforeEach(() => {
  get.mockReset();
});

describe('agentWorkspaceApi runtime recovery routes', () => {
  it('uses the backend kebab-case runtime REST contract for passport, gate, and handoff card reads', async () => {
    get
      .mockResolvedValueOnce({ data: workflowPassportResponse })
      .mockResolvedValueOnce({ data: evidenceIntegrityGateResponse })
      .mockResolvedValueOnce({ data: agentHandoffCardResponse });

    await getWorkflowPassport({
      sessionId: 'session-42',
      jobId: 'job-42',
      projectId: 'project-42',
      limit: 7,
    });
    await getEvidenceIntegrityGate({
      sessionId: 'session-42',
      jobId: 'job-42',
      projectId: 'project-42',
      limit: 9,
    });
    await getAgentHandoffCard('job-42');

    const calledUrls = get.mock.calls.map((call) => call[0]);

    expect(calledUrls).toEqual([
      '/runtime/workflow-passport',
      '/runtime/evidence-integrity-gate',
      '/runtime/job/job-42/agent-handoff-card',
    ]);
    expect(calledUrls).not.toContain('/runtime/workflow_passport');
    expect(calledUrls).not.toContain('/runtime/evidence_integrity_gate');
    expect(calledUrls).not.toContain('/runtime/agent_handoff_card');
    expect(calledUrls.every((url) => !url.includes('_'))).toBe(true);
    expect(get).toHaveBeenNthCalledWith(1, '/runtime/workflow-passport', {
      params: {
        session_id: 'session-42',
        job_id: 'job-42',
        project_id: 'project-42',
        limit: 7,
      },
    });
    expect(get).toHaveBeenNthCalledWith(2, '/runtime/evidence-integrity-gate', {
      params: {
        session_id: 'session-42',
        job_id: 'job-42',
        project_id: 'project-42',
        limit: 9,
      },
    });
    expect(get).toHaveBeenNthCalledWith(3, '/runtime/job/job-42/agent-handoff-card');
  });
});
