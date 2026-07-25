import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { __test, SmartReadProvider, smartReadDialogScope, useSmartRead } from './SmartReadContext';

vi.mock('@/services/intelligentChatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/intelligentChatApi')>();
  return {
    ...actual,
    resumeChatSession: vi.fn(async () => ({
      session_id: 'session-resumed-123',
      messages: [
        {
          id: 'u-backend-1',
          role: 'user',
          content: 'backend question',
          timestamp: '2026-05-25T02:00:00.000Z',
        },
        {
          id: 'a-backend-1',
          role: 'assistant',
          content: 'backend restored answer',
          timestamp: '2026-05-25T02:01:00.000Z',
          tier_used: 'balanced',
          context_metadata: { chunks: [], truncated: false },
          tokens_used: { prompt: 1, completion: 2, total: 3 },
          evidence_refs: [],
        },
      ],
    })),
    streamIntelligentChatMessage: vi.fn(async (request, opts) => {
      opts.onEvent({
        event: 'metadata',
        session_id: request.session_id || 'session-created-by-backend',
        context_chunks_used: 0,
        tier_used: request.tier || 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        actual_sampling_params: null,
      });
      opts.onEvent({ event: 'text_delta', delta: 'backend answer' });
      opts.onEvent({ event: 'done', response: 'backend answer', session_id: request.session_id || 'session-created-by-backend' });
    }),
  };
});

const { resumeChatSession, streamIntelligentChatMessage } = await import('@/services/intelligentChatApi');
const resumeMock = vi.mocked(resumeChatSession);
const streamMock = vi.mocked(streamIntelligentChatMessage);

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
} {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function seedLocalStorage(entries: Record<string, string>): Storage {
  window.localStorage.clear();
  for (const [key, value] of Object.entries(entries)) {
    window.localStorage.setItem(key, value);
  }
  return window.localStorage;
}

function wrapper({ children }: { children: ReactNode }) {
  return <SmartReadProvider>{children}</SmartReadProvider>;
}

const OBSERVATION_OUTPUT_SHA = `sha256:${'c'.repeat(64)}`;

function visualObservationReference(turnId: string) {
  return {
    schema_version: 'scholar-ai-visual-observation-ref/v1' as const,
    candidate_id: `candidate-${turnId}`,
    turn_id: turnId,
    route: 'vision_aux_mcp' as const,
    generation_status: 'succeeded' as const,
    review_status: 'candidate' as const,
    selection_ids: [`selection-${turnId}`],
    output_sha256: OBSERVATION_OUTPUT_SHA,
    cache_status: 'miss' as const,
    read_endpoint: `/api/chat/visual-observations/candidate-${turnId}`,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resumeMock.mockClear();
  resumeMock.mockResolvedValue({
    session_id: 'session-resumed-123',
    messages: [
      {
        id: 'u-backend-1',
        role: 'user',
        content: 'backend question',
        timestamp: '2026-05-25T02:00:00.000Z',
      },
      {
        id: 'a-backend-1',
        role: 'assistant',
        content: 'backend restored answer',
        timestamp: '2026-05-25T02:01:00.000Z',
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        tokens_used: { prompt: 1, completion: 2, total: 3 },
        evidence_refs: [],
      },
    ],
  });
  streamMock.mockClear();
});

describe('SmartReadContext legacy Dialog migration', () => {
  it('maps unified and mode-scoped legacy Dialog messages into one smart-read scope', () => {
    const storage = seedLocalStorage({
      'dialog-messages_project-a': JSON.stringify([
        {
          id: 'u1',
          role: 'user',
          content: '材料问题',
          timestamp: '2026-05-25T01:00:00.000Z',
        },
      ]),
      'dialog-messages_project-a_direct': JSON.stringify([
        {
          id: 'a1',
          role: 'assistant',
          content: '回答 [chunk-aa]',
          timestamp: '2026-05-25T01:01:00.000Z',
          tierUsed: 'balanced',
          contextMetadata: {
            chunks: [
              {
                index: 1,
                source: 'paper.pdf',
                content: 'quote',
                relevance_score: 0.8,
              },
            ],
          },
          evidenceRefs: [
            {
              chunk_id: 'chunk-aa',
              material_id: 'mat-1',
              source: 'paper.pdf',
              text: 'quote',
              quote: 'quote',
              page: '3',
            },
          ],
        },
      ]),
    });

    const migrated = __test.migrateLegacyDialogMessages(storage);
    const scope = smartReadDialogScope('project-a');
    expect(migrated[scope]?.messages).toHaveLength(2);
    expect(migrated[scope]?.messages[1].metadata?.diagnostics?.tier).toBe('balanced');
    expect(migrated[scope]?.messages[1].metadata?.diagnostics?.chunkRefs).toEqual(['chunk-aa']);
    expect(migrated[scope]?.messages[1].evidence?.[0].page).toBe(3);
    expect(storage.getItem('dialog-messages_project-a_direct')).not.toBeNull();
  });

  it('is idempotent and does not duplicate messages after the flag is written', () => {
    const storage = seedLocalStorage({
      'dialog-messages_default_literature_qa': JSON.stringify([
        {
          id: 'u1',
          role: 'user',
          content: 'hello',
          timestamp: '2026-05-25T01:00:00.000Z',
        },
      ]),
    });

    const first = __test.migrateLegacyDialogMessages(storage);
    const second = __test.migrateLegacyDialogMessages(storage);
    const scope = smartReadDialogScope('default');

    expect(first[scope]?.messages).toHaveLength(1);
    expect(second[scope]?.messages).toHaveLength(1);
    expect(storage.getItem(__test.LEGACY_DIALOG_MIGRATION_KEY)).toContain('dialog-messages_default_literature_qa');
  });

  it('keeps existing smart-read messages and de-duplicates matching legacy ids', () => {
    const scope = smartReadDialogScope('project-b');
    const storage = seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          updatedAt: 1,
          messages: [
            {
              id: 'u1',
              role: 'user',
              content: 'existing',
              timestamp: '2026-05-25T01:00:00.000Z',
            },
          ],
        },
      }),
      'dialog-messages_project-b_inspiration': JSON.stringify([
        {
          id: 'u1',
          role: 'user',
          content: 'existing',
          timestamp: '2026-05-25T01:00:00.000Z',
        },
        {
          id: 'a1',
          role: 'assistant',
          content: 'new answer',
          timestamp: '2026-05-25T01:01:00.000Z',
        },
      ]),
    });

    const migrated = __test.migrateLegacyDialogMessages(storage);

    expect(migrated[scope]?.messages.map((message) => message.id)).toEqual(['u1', 'a1']);
  });

  it('validates durable research selections when restoring localStorage', () => {
    const scope = smartReadDialogScope('selection-storage-project');
    const storage = seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          updatedAt: 1,
          messages: [{
            id: 'u-selection-storage',
            role: 'user',
            content: '解释选区',
            timestamp: '2026-07-15T01:00:00.000Z',
            turnId: 'turn-selection-storage',
            researchSelections: [{
              schema_version: 'scholar-ai-research-selection/v1',
              selection_id: 'selection-storage-1',
              turn_id: 'turn-selection-storage',
              group_id: 'group-selection-storage',
              order: 0,
              material_id: 'material-storage',
              kind: 'figure',
              page: 3,
              bbox: [0.1, 0.2, 0.4, 0.3],
              bbox_unit: 'normalized_ratio',
              image_index: 2,
              data_b64: 'must-not-survive',
            }, {
              schema_version: 'unknown-version',
              selection_id: 'selection-invalid',
              turn_id: 'turn-selection-storage',
              group_id: 'group-selection-storage',
              order: 1,
              material_id: 'material-storage',
              kind: 'text',
              page: 4,
              text: 'invalid version',
            }],
          }],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    expect(result.current.getConversation(scope).messages[0]).toMatchObject({
      turnId: 'turn-selection-storage',
      researchSelections: [{
        selection_id: 'selection-storage-1',
        group_id: 'group-selection-storage',
        order: 0,
        kind: 'figure',
      }],
    });
    expect(JSON.stringify(result.current.getConversation(scope).messages)).not.toContain('image_index');
    expect(JSON.stringify(result.current.getConversation(scope).messages)).not.toContain('data_b64');
    expect(storage.getItem(__test.STORAGE_KEY)).not.toContain('must-not-survive');
  });

  it('validates visual observation references when restoring localStorage', () => {
    const scope = smartReadDialogScope('visual-observation-storage-project');
    const reference = visualObservationReference('turn-observation-storage');
    const storage = seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          updatedAt: 1,
          messages: [{
            id: 'assistant-observation-storage',
            role: 'assistant',
            content: 'Stored answer.',
            timestamp: '2026-07-16T01:00:00.000Z',
            turnId: 'turn-observation-storage',
            visualObservationRefs: [
              reference,
              { ...reference, candidate_id: 'unsafe-candidate', data_b64: 'must-not-survive' },
            ],
          }],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    expect(result.current.getConversation(scope).messages[0]?.visualObservationRefs).toEqual([reference]);
    expect(JSON.stringify(result.current.getConversation(scope).messages)).not.toContain('data_b64');
    expect(storage.getItem(__test.STORAGE_KEY)).not.toContain('must-not-survive');
  });

  it('attaches an ordered research-selection snapshot to provider-owned user turns', async () => {
    const scope = smartReadDialogScope('provider-selection-project');
    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await act(async () => {
      await result.current.sendMessage(scope, '解释这段文字', {
        projectId: 'provider-selection-project',
        materialId: 'material-provider-selection',
        currentPdfContext: {
          material_id: 'material-provider-selection',
          page: 5,
          selection: {
            kind: 'text',
            page: 5,
            text: 'Selected paragraph [3].',
            bbox: [0.1, 0.3, 0.7, 0.08],
            bbox_unit: 'normalized_ratio',
          },
          selections: [{
            kind: 'text',
            page: 5,
            text: 'Selected paragraph [3].',
            bbox: [0.1, 0.3, 0.7, 0.08],
            bbox_unit: 'normalized_ratio',
          }],
          context_kind: 'selection',
        },
      });
    });

    const userMessage = result.current.getConversation(scope).messages[0];
    expect(userMessage.turnId).toBeTruthy();
    expect(userMessage.researchSelections).toEqual([
      expect.objectContaining({
        turn_id: userMessage.turnId,
        order: 0,
        material_id: 'material-provider-selection',
        kind: 'text',
        text: 'Selected paragraph [3].',
      }),
    ]);
    expect(streamMock).toHaveBeenCalledWith(
      expect.objectContaining({
        turn_id: userMessage.turnId,
        research_selections: userMessage.researchSelections,
      }),
      expect.any(Object),
    );
  });

  it('persists backend session id and reuses it on the next provider-owned stream turn', async () => {
    const scope = smartReadDialogScope('project-session');
    const storage = seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-resumed-123',
          updatedAt: 1,
          messages: [
            {
              id: 'u1',
              role: 'user',
              content: 'existing question',
              timestamp: '2026-05-25T01:00:00.000Z',
            },
          ],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    expect(result.current.getConversation(scope).sessionId).toBe('session-resumed-123');
    await act(async () => {
      await result.current.sendMessage(scope, 'follow up', {
        projectId: 'project-session',
        materialId: 'mat-current',
        currentPdfContext: {
          material_id: 'mat-current',
          page: 5,
          selected_text: 'current PDF selected text',
          bbox: [0.1, 0.2, 0.3, 0.1],
          bbox_unit: 'normalized_ratio',
          context_kind: 'selection',
        },
      });
    });

    expect(streamMock).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: 'session-resumed-123',
        material_id: 'mat-current',
        current_pdf_context: expect.objectContaining({
          material_id: 'mat-current',
          page: 5,
          selected_text: 'current PDF selected text',
        }),
      }),
      expect.any(Object),
    );
    const persisted = JSON.parse(storage.getItem(__test.STORAGE_KEY) || '{}') as Record<string, { sessionId?: string }>;
    expect(persisted[scope]?.sessionId).toBe('session-resumed-123');
  });

  it('attaches streamed analysis-chain summaries to the final assistant message', async () => {
    const scope = smartReadDialogScope('analysis-chain-project');
    streamMock.mockImplementationOnce(async (request, opts) => {
      const sessionId = request.session_id || 'session-analysis-chain';
      opts.onEvent({
        event: 'metadata',
        session_id: sessionId,
        context_chunks_used: 0,
        tier_used: request.tier || 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        actual_sampling_params: null,
      });
      opts.onEvent({ event: 'text_delta', delta: 'backend answer' });
      opts.onEvent({
        event: 'analysis_chain_done',
        session_id: sessionId,
        analysis_chain: {
          observation: '观察到材料问题',
          mechanism: '证据支持该解释',
          evidence: ['证据片段'],
          boundary: '仅限当前资料',
          counter_evidence: [],
          next_action: '继续检索',
        },
      });
      opts.onEvent({ event: 'done', response: 'backend answer', session_id: sessionId });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, 'hi', { projectId: 'analysis-chain-project' });
    });

    const assistant = result.current.getConversation(scope).messages.at(-1);
    expect(assistant?.status).toBe('done');
    expect(assistant?.analysis_chain).toMatchObject({
      observation: '观察到材料问题',
      evidence: ['证据片段'],
      next_action: '继续检索',
    });
  });

  it('uses final done-event visual refs when the answer cites an additional figure', async () => {
    const scope = smartReadDialogScope('final-visual-refs-project');
    const fig14 = {
      chunk_id: 'fig-14',
      material_id: 'mat-cui',
      source: 'Cui 2022.pdf',
      text: 'Fig. 14. Joint strength.',
      quote: 'Fig. 14. Joint strength.',
      figure_candidate: 'Fig. 14',
      figure_candidate_detail: { kind: 'figure', label: 'Fig. 14' },
      image_paths: ['figure_assets/extracted/cui/p0011_img001.png'],
    };
    const fig6 = {
      chunk_id: 'fig-6',
      material_id: 'mat-cui',
      source: 'Cui 2022.pdf',
      text: 'Fig. 6. Macrostructure.',
      quote: 'Fig. 6. Macrostructure.',
      figure_candidate: 'Fig. 6',
      figure_candidate_detail: { kind: 'figure', label: 'Fig. 6' },
      image_paths: ['figure_assets/extracted/cui/p0006_img001.png'],
    };
    streamMock.mockImplementationOnce(async (request, opts) => {
      const sessionId = request.session_id || 'session-final-visual-refs';
      opts.onEvent({
        event: 'metadata',
        session_id: sessionId,
        context_chunks_used: 1,
        tier_used: request.tier || 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        visual_evidence_refs: [fig14],
        actual_sampling_params: null,
      });
      opts.onEvent({ event: 'text_delta', delta: 'Fig. 6 与 Fig. 14 共同解释该趋势。' });
      opts.onEvent({
        event: 'done',
        response: 'Fig. 6 与 Fig. 14 共同解释该趋势。',
        session_id: sessionId,
        visual_evidence_refs: [fig6, fig14],
      });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, '解释两张图', { projectId: 'final-visual-refs-project' });
    });

    const assistant = result.current.getConversation(scope).messages.at(-1);
    expect(assistant?.status).toBe('done');
    expect(assistant?.relatedFigures?.map((figure) => figure.asset_path)).toEqual([
      'figure_assets/extracted/cui/p0006_img001.png',
      'figure_assets/extracted/cui/p0011_img001.png',
    ]);
  });

  it('persists done-event visual observation references without promoting them to evidence', async () => {
    const scope = smartReadDialogScope('visual-observation-stream-project');
    streamMock.mockImplementationOnce(async (request, opts) => {
      const turnId = request.turn_id ?? 'missing-turn';
      opts.onEvent({ event: 'text_delta', delta: 'Visual answer.' });
      opts.onEvent({
        event: 'done',
        response: 'Visual answer.',
        session_id: 'session-visual-observation-stream',
        visual_observation_refs: [visualObservationReference(turnId)],
      });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, '解释图表', { projectId: 'visual-observation-stream-project' });
    });

    const assistant = result.current.getConversation(scope).messages.at(-1);
    expect(assistant?.visualObservationRefs).toEqual([
      visualObservationReference(assistant?.turnId ?? 'missing-turn'),
    ]);
    expect(assistant?.evidence).toBeUndefined();
    expect(assistant?.relatedFigures).toEqual([]);
    expect(window.localStorage.getItem(__test.STORAGE_KEY)).toContain('visualObservationRefs');
    expect(window.localStorage.getItem(__test.STORAGE_KEY)).not.toContain('output_text');
  });

  it('restores visual observation references from the backend session', async () => {
    const scope = smartReadDialogScope('visual-observation-resume-project');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-visual-observation-resume',
          updatedAt: 1,
          messages: [{
            id: 'assistant-local-before-resume',
            role: 'assistant',
            content: 'Local answer.',
            timestamp: '2026-07-16T00:00:00.000Z',
          }],
        },
      }),
    });
    const reference = visualObservationReference('turn-observation-resume');
    resumeMock.mockResolvedValueOnce({
      session_id: 'session-visual-observation-resume',
      messages: [{
        id: 'assistant-observation-resume',
        role: 'assistant',
        content: 'Backend visual answer.',
        timestamp: '2026-07-16T01:00:00.000Z',
        turn_id: 'turn-observation-resume',
        visual_observation_refs: [reference],
      }],
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await waitFor(() => {
      expect(result.current.getConversation(scope).messages[0]?.content).toBe('Backend visual answer.');
    });
    expect(result.current.getConversation(scope).messages[0]?.visualObservationRefs).toEqual([reference]);
  });

  it('preserves evidence roles from streamed metadata on the assistant message', async () => {
    const scope = smartReadDialogScope('role-stream-project');
    streamMock.mockImplementationOnce(async (request, opts) => {
      const sessionId = request.session_id || 'session-role-stream';
      opts.onEvent({
        event: 'metadata',
        session_id: sessionId,
        context_chunks_used: 1,
        tier_used: request.tier || 'balanced',
        context_metadata: {
          chunks: [{
            index: 1,
            source: 'Referenced paper.pdf',
            content: 'Referenced evidence.',
            evidence_role: 'cited_project_material',
          }],
          truncated: false,
        },
        evidence_refs: [{
          chunk_id: 'chunk-cited-1',
          material_id: 'mat-cited',
          source: 'Referenced paper.pdf',
          text: 'Referenced evidence.',
          quote: 'Referenced evidence.',
          evidence_role: 'cited_project_material',
        }],
        actual_sampling_params: null,
      });
      opts.onEvent({ event: 'text_delta', delta: 'answer' });
      opts.onEvent({ event: 'done', response: 'answer', session_id: sessionId });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, 'question', { projectId: 'role-stream-project' });
    });

    const assistant = result.current.getConversation(scope).messages.at(-1);
    expect(assistant?.evidence?.[0]?.evidence_role).toBe('cited_project_material');
    expect(assistant?.metadata?.diagnostics?.context?.chunks?.[0]?.evidence_role).toBe('cited_project_material');
  });

  it('falls back unknown streamed evidence roles to project context', async () => {
    const scope = smartReadDialogScope('invalid-role-stream-project');
    streamMock.mockImplementationOnce(async (request, opts) => {
      const sessionId = request.session_id || 'session-invalid-role-stream';
      opts.onEvent({
        event: 'metadata',
        session_id: sessionId,
        context_chunks_used: 1,
        tier_used: request.tier || 'balanced',
        context_metadata: {
          chunks: [{
            index: 1,
            source: 'Unknown role.pdf',
            content: 'Fallback evidence.',
            evidence_role: 'unexpected_role' as 'project_context',
          }],
          truncated: false,
        },
        evidence_refs: [{
          chunk_id: 'chunk-invalid-role',
          source: 'Unknown role.pdf',
          text: 'Fallback evidence.',
          quote: 'Fallback evidence.',
          evidence_role: 'unexpected_role' as 'project_context',
        }],
        actual_sampling_params: null,
      });
      opts.onEvent({ event: 'done', response: 'answer', session_id: sessionId });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, 'question', { projectId: 'invalid-role-stream-project' });
    });

    const assistant = result.current.getConversation(scope).messages.at(-1);
    expect(assistant?.evidence?.[0]?.evidence_role).toBe('project_context');
    expect(assistant?.metadata?.diagnostics?.context?.chunks?.[0]?.evidence_role).toBe('project_context');
  });

  it('preserves evidence roles when hydrating a resumed backend session', async () => {
    const scope = smartReadDialogScope('role-resume-project');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-role-resume',
          updatedAt: 1,
          messages: [],
        },
      }),
    });
    resumeMock.mockResolvedValueOnce({
      session_id: 'session-role-resume',
      messages: [{
        id: 'a-role-resume',
        role: 'assistant',
        content: 'restored role answer',
        timestamp: '2026-07-14T00:00:00.000Z',
        tier_used: 'balanced',
        context_metadata: {
          chunks: [{
            index: 1,
            source: 'Current paper.pdf',
            content: 'Current material evidence.',
            evidence_role: 'current_material',
          }],
          truncated: false,
        },
        evidence_refs: [{
          chunk_id: 'chunk-current-1',
          material_id: 'mat-current',
          source: 'Current paper.pdf',
          text: 'Current material evidence.',
          quote: 'Current material evidence.',
          evidence_role: 'current_material',
        }],
      }],
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const assistant = result.current.getConversation(scope).messages[0];
    expect(assistant?.evidence?.[0]?.evidence_role).toBe('current_material');
    expect(assistant?.metadata?.diagnostics?.context?.chunks?.[0]?.evidence_role).toBe('current_material');
  });

  it('falls back unknown resumed evidence roles to project context', async () => {
    const scope = smartReadDialogScope('invalid-role-resume-project');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-invalid-role-resume',
          updatedAt: 1,
          messages: [],
        },
      }),
    });
    resumeMock.mockResolvedValueOnce({
      session_id: 'session-invalid-role-resume',
      messages: [{
        id: 'a-invalid-role-resume',
        role: 'assistant',
        content: 'restored fallback answer',
        timestamp: '2026-07-14T00:00:00.000Z',
        tier_used: 'balanced',
        context_metadata: {
          chunks: [{
            index: 1,
            source: 'Unknown role.pdf',
            content: 'Fallback evidence.',
            evidence_role: 'unexpected_role' as 'project_context',
          }],
          truncated: false,
        },
        evidence_refs: [{
          chunk_id: 'chunk-invalid-role-resume',
          source: 'Unknown role.pdf',
          text: 'Fallback evidence.',
          quote: 'Fallback evidence.',
          evidence_role: 'unexpected_role' as 'project_context',
        }],
      }],
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const assistant = result.current.getConversation(scope).messages[0];
    expect(assistant?.evidence?.[0]?.evidence_role).toBe('project_context');
    expect(assistant?.metadata?.diagnostics?.context?.chunks?.[0]?.evidence_role).toBe('project_context');
  });

  it('passes external-agent answer origin into SmartRead stream requests', async () => {
    const scope = smartReadDialogScope('external-agent-project');
    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await act(async () => {
      await result.current.sendMessage(scope, 'prepare evidence', {
        projectId: 'external-agent-project',
        answerOrigin: 'external_agent',
      });
    });

    expect(streamMock).toHaveBeenCalledWith(
      expect.objectContaining({
        query: 'prepare evidence',
        project_id: 'external-agent-project',
        answer_origin: 'external_agent',
      }),
      expect.any(Object),
    );
  });

  it('hydrates persisted backend sessions into the provider store on mount', async () => {
    const scope = smartReadDialogScope('project-session');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-resumed-123',
          updatedAt: 1,
          messages: [
            {
              id: 'u-local-stale',
              role: 'user',
              content: 'stale local question',
              timestamp: '2026-05-25T01:00:00.000Z',
            },
          ],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(resumeMock).toHaveBeenCalledWith({ session_id: 'session-resumed-123', limit: 100 });
    expect(result.current.getConversation(scope).messages.map((message) => message.id)).toEqual([
      'u-backend-1',
      'a-backend-1',
    ]);
    expect(result.current.getConversation(scope).messages[1].content).toBe('backend restored answer');
  });

  it('does not hydrate over a restored streaming assistant draft', async () => {
    const scope = smartReadDialogScope('project-streaming');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-resumed-123',
          updatedAt: 1,
          messages: [
            {
              id: 'u-local-stream',
              role: 'user',
              content: 'hi',
              timestamp: '2026-05-25T01:00:00.000Z',
            },
            {
              id: 'a-local-stream',
              role: 'assistant',
              content: '',
              timestamp: '2026-05-25T01:00:01.000Z',
              status: 'streaming',
            },
          ],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(resumeMock).not.toHaveBeenCalled();
    expect(result.current.getConversation(scope).messages.at(-1)).toEqual(expect.objectContaining({
      id: 'a-local-stream',
      status: 'streaming',
    }));
  });

  it('keeps a streaming assistant draft when backend hydration resolves late', async () => {
    const scope = smartReadDialogScope('project-hydration-race');
    const pendingResume = deferred<Awaited<ReturnType<typeof resumeChatSession>>>();
    resumeMock.mockImplementationOnce(async () => pendingResume.promise);
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-resumed-123',
          updatedAt: 1,
          messages: [
            {
              id: 'u-local-stale',
              role: 'user',
              content: 'stale local question',
              timestamp: '2026-05-25T01:00:00.000Z',
            },
          ],
        },
      }),
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      result.current.setConversation(scope, [
        {
          id: 'u-local-stream',
          role: 'user',
          content: 'hi',
          timestamp: '2026-05-25T01:00:00.000Z',
        },
        {
          id: 'a-local-stream',
          role: 'assistant',
          content: '',
          timestamp: '2026-05-25T01:00:01.000Z',
          status: 'streaming',
        },
      ], { sessionId: 'session-resumed-123' });
    });
    await act(async () => {
      pendingResume.resolve({
        session_id: 'session-resumed-123',
        messages: [
          {
            id: 'u-backend-late',
            role: 'user',
            content: 'backend stale question',
            timestamp: '2026-05-25T02:00:00.000Z',
          },
          {
            id: 'a-backend-late',
            role: 'assistant',
            content: 'backend stale answer',
            timestamp: '2026-05-25T02:01:00.000Z',
            tier_used: 'balanced',
            context_metadata: { chunks: [], truncated: false },
            tokens_used: { prompt: 1, completion: 2, total: 3 },
            evidence_refs: [],
          },
        ],
      });
      await pendingResume.promise;
      await Promise.resolve();
    });

    const conversation = result.current.getConversation(scope);
    expect(conversation.messages.map((message) => message.id)).toEqual([
      'u-local-stream',
      'a-local-stream',
    ]);
    expect(conversation.messages.at(-1)?.status).toBe('streaming');
  });

  it('stops an in-flight provider-owned stream for a scope', async () => {
    const scope = smartReadDialogScope('abort-project');
    const pendingStream = deferred<void>();
    streamMock.mockImplementationOnce(async (_request, opts) => {
      opts.signal?.addEventListener('abort', () => {
        pendingStream.reject(new DOMException('The operation was aborted.', 'AbortError'));
      }, { once: true });
      opts.onEvent({
        event: 'metadata',
        session_id: 'session-created-by-backend',
        context_chunks_used: 0,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        actual_sampling_params: null,
      });
      return pendingStream.promise;
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    let sendPromise!: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage(scope, 'hi', { projectId: 'abort-project' });
      await Promise.resolve();
    });

    expect(result.current.getConversation(scope).pending).toBe(true);
    await act(async () => {
      result.current.stopMessage(scope);
      await sendPromise;
    });

    const conversation = result.current.getConversation(scope);
    expect(conversation.pending).toBe(false);
    expect(conversation.messages.at(-1)?.content).toBe('已停止生成。');
    expect(conversation.messages.at(-1)?.status).toBe('done');
  });

  it('redacts technical backend failures before writing them into chat content', async () => {
    const scope = smartReadDialogScope('error-redaction-project');
    streamMock.mockImplementationOnce(async () => {
      throw new Error('env=VISION_PROVIDER {"detail":"server_id=srv-1"} C:\\secret\\runtime.json');
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, 'hi', { projectId: 'error-redaction-project' });
    });

    const message = result.current.getConversation(scope).messages.at(-1);
    expect(message?.status).toBe('error');
    expect(message?.content).toBe('回答失败：访问凭证不可用，请在 API 配置中检查后重试。');
    expect(message?.content).not.toContain('env=VISION_PROVIDER');
    expect(message?.content).not.toContain('server_id');
  });

  it('keeps streamed text, quote, anchor identity, and hashes while dropping a unitless bbox', async () => {
    const scope = smartReadDialogScope('evidence-integrity-stream');
    streamMock.mockImplementationOnce(async (request, opts) => {
      const sessionId = request.session_id || 'session-evidence-integrity-stream';
      opts.onEvent({
        event: 'metadata',
        session_id: sessionId,
        context_chunks_used: 1,
        tier_used: request.tier || 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [{
          chunk_id: 'chunk-evidence-stream',
          material_id: 'material-evidence-stream',
          source: 'Evidence stream.pdf',
          text: 'Full chunk text.',
          quote: 'Exact streamed sentence.',
          anchor_kind: 'text',
          bbox: [0.1, 0.2, 0.4, 0.1],
          content_hash: 'a'.repeat(64),
          locator_hash: 'b'.repeat(64),
          chunk_hash: 'c'.repeat(64),
          embedding_input_hash: 'd'.repeat(64),
          hash_version: 'scholar-ai-chunk-hash/v2',
        }],
      });
      opts.onEvent({ event: 'done', response: 'Evidence answer.', session_id: sessionId });
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await act(async () => {
      await result.current.sendMessage(scope, 'Show evidence.', { projectId: 'evidence-integrity-stream' });
    });

    expect(result.current.getConversation(scope).messages.at(-1)?.evidence?.[0]).toMatchObject({
      text: 'Full chunk text.',
      quote: 'Exact streamed sentence.',
      anchor_kind: 'text',
      bbox: null,
      bbox_unit: null,
      content_hash: 'a'.repeat(64),
      locator_hash: 'b'.repeat(64),
      chunk_hash: 'c'.repeat(64),
      embedding_input_hash: 'd'.repeat(64),
      hash_version: 'scholar-ai-chunk-hash/v2',
    });
  });

  it('restores the same evidence identity without relabeling pdf_points', async () => {
    const scope = smartReadDialogScope('evidence-integrity-resume');
    seedLocalStorage({
      [__test.STORAGE_KEY]: JSON.stringify({
        [scope]: {
          sessionId: 'session-evidence-integrity-resume',
          updatedAt: 1,
          messages: [],
        },
      }),
    });
    resumeMock.mockResolvedValueOnce({
      session_id: 'session-evidence-integrity-resume',
      messages: [{
        id: 'assistant-evidence-resume',
        role: 'assistant',
        content: 'Restored evidence answer.',
        timestamp: '2026-07-22T12:00:00.000Z',
        evidence_refs: [{
          chunk_id: 'chunk-evidence-resume',
          material_id: 'material-evidence-resume',
          source: 'Evidence resume.pdf',
          text: 'Restored full chunk text.',
          quote: 'Restored exact sentence.',
          anchor_kind: 'text',
          bbox: [72, 144, 180, 36],
          bbox_unit: 'pdf_points',
          content_hash: 'e'.repeat(64),
          locator_hash: 'f'.repeat(64),
          chunk_hash: '1'.repeat(64),
          embedding_input_hash: '2'.repeat(64),
          hash_version: 'scholar-ai-chunk-hash/v2',
        }],
      }],
    });

    const { result } = renderHook(() => useSmartRead(), { wrapper });
    await waitFor(() => {
      expect(result.current.getConversation(scope).messages[0]?.id).toBe('assistant-evidence-resume');
    });

    expect(result.current.getConversation(scope).messages[0]?.evidence?.[0]).toMatchObject({
      text: 'Restored full chunk text.',
      quote: 'Restored exact sentence.',
      anchor_kind: 'text',
      bbox: [72, 144, 180, 36],
      bbox_unit: 'pdf_points',
      content_hash: 'e'.repeat(64),
      locator_hash: 'f'.repeat(64),
      chunk_hash: '1'.repeat(64),
      embedding_input_hash: '2'.repeat(64),
      hash_version: 'scholar-ai-chunk-hash/v2',
    });
  });
});
