import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  buildDialogCurrentPdfContext,
  buildDialogFormulaCandidatesFromResources,
  Dialog,
  isUnavailableError,
  readDialogErrorText,
  resolveDialogSmartReadChatSessionId,
} from './Dialog';
import type { ChatMessageData } from '@/components/chat/MessageRenderer';
import type { GraphNavigateTarget } from '@/components/graph/GraphPayloadViewer';
import {
  chatAttachmentFingerprint,
  type ChatAttachment,
  type ChatInputHandle,
  type ChatInputSubmitPayload,
  type IdentifiedChatSelectionContext,
} from '@/components/chat/ChatInput';
import type {
  PdfFormulaCandidate,
  PdfRegionCapture,
  PdfSelectedVisualRegion,
  PdfSelectionAnchor,
} from '@/components/PdfViewer/PdfViewer';
import { PdfTabsProvider } from '@/contexts/PdfTabsContext';
import { smartReadDialogScope, useSmartRead } from '@/contexts/SmartReadContext';
import { useWriting } from '@/contexts/WritingContext';
import { getAnnotations } from '@/services/annotationApi';
import { runBackgroundJob } from '@/services/backgroundJobRunner';
import { getAnswerEvidenceGraph } from '@/services/graphApi';
import { locateChunk } from '@/services/resourcesApi';
import {
  createAgentSidebarAnswerRequest,
  readAgentSidebarReceipt,
} from '@/services/agentSidebarApi';
import {
  listChatSessions,
  resumeChatSession,
  restoreChatSession,
  streamIntelligentChatMessage,
  type ChatResumeResponse,
  type ChatSessionSummary,
} from '@/services/intelligentChatApi';
import { getWritingBackendService } from '@/services/writingBackend';
import type { PdfContentSelection } from '@/lib/pdfAnchor';

const pdfReaderShellMockState = vi.hoisted(() => ({
  emitInitialPageChangeOnMount: false,
  initialPageChanges: [] as number[],
}));

type ConversationMockProps = {
  messages: ChatMessageData[];
  projectId?: string | null;
  inputValue?: string;
  emptyState?: React.ReactNode;
  composerContext?: React.ReactNode;
  composerHint?: string;
  responding?: boolean;
  disabled?: boolean;
  enableAttachments?: boolean;
  attachments?: ChatAttachment[];
  onAttachmentsChange?: React.Dispatch<React.SetStateAction<ChatAttachment[]>>;
  pendingAttachmentReads?: number;
  onPendingAttachmentReadsChange?: React.Dispatch<React.SetStateAction<number>>;
  selectionContexts?: readonly IdentifiedChatSelectionContext[];
  onRemoveSelectionContext?: (id: string) => void;
  inputRef?: React.Ref<ChatInputHandle>;
  onSubmit?: (payload: ChatInputSubmitPayload) => void;
  onInputValueChange?: (value: string) => void;
  onStop?: () => void;
  onEditMessage?: (message: ChatMessageData) => void;
  onForkMessage?: (message: ChatMessageData) => void;
  messageFooter?: (message: ChatMessageData) => React.ReactNode;
  onSelectEvidence?: (evidence: NonNullable<ChatMessageData['evidence']>[number]) => void;
  navigateEvidenceAfterSelect?: boolean;
};

const listProjectsMock = vi.fn();
const listMaterialsMock = vi.fn();
const listMaterialChunksMock = vi.fn();
const listFormulaCandidatesMock = vi.fn();
const listFigureTableCandidatesMock = vi.fn();
const manualComposerAttachment: ChatAttachment = {
  mime: 'image/png',
  data_b64: 'bWFudWFsLWltYWdl',
  size: 12,
  name: 'manual-note.png',
};
const lateManualComposerAttachment: ChatAttachment = {
  mime: 'image/png',
  data_b64: 'bGF0ZS1tYW51YWwtaW1hZ2U=',
  size: 17,
  name: 'late-note.png',
};
const replacementComposerAttachments: ChatAttachment[] = Array.from({ length: 6 }, (_, index) => ({
  mime: 'image/png',
  data_b64: `cmVwbGFjZW1lbnQt${index + 1}`,
  size: 20 + index,
  name: `replacement-${index + 1}.png`,
}));
let completePendingAttachmentRead: (() => void) | null = null;
let completePendingRegionCapture: (() => void) | null = null;
const DIALOG_OBSERVATION_OUTPUT_SHA = `sha256:${'d'.repeat(64)}`;

function dialogVisualObservationReference(turnId: string) {
  return {
    schema_version: 'scholar-ai-visual-observation-ref/v1' as const,
    candidate_id: `candidate-${turnId}`,
    turn_id: turnId,
    route: 'vision_aux_mcp' as const,
    generation_status: 'succeeded' as const,
    review_status: 'candidate' as const,
    selection_ids: [`selection-${turnId}`],
    output_sha256: DIALOG_OBSERVATION_OUTPUT_SHA,
    cache_status: 'miss' as const,
    read_endpoint: `/api/chat/visual-observations/candidate-${turnId}`,
  };
}

vi.mock('@/components/chat/Conversation', () => ({
  Conversation: ({
    messages,
    projectId,
    inputValue = '',
    emptyState,
    composerContext,
    composerHint,
    responding = false,
    disabled = false,
    enableAttachments = false,
    attachments: controlledAttachments,
    onAttachmentsChange,
    pendingAttachmentReads = 0,
    onPendingAttachmentReadsChange,
    selectionContexts = [],
    onRemoveSelectionContext,
    inputRef,
    onSubmit,
    onInputValueChange,
    onStop,
    onEditMessage,
    onForkMessage,
    messageFooter,
    onSelectEvidence,
    navigateEvidenceAfterSelect = false,
  }: ConversationMockProps) => {
    const [uncontrolledAttachments, setUncontrolledAttachments] = React.useState<ChatAttachment[]>([]);
    const attachments = controlledAttachments ?? uncontrolledAttachments;
    const updateAttachments = React.useCallback((update: React.SetStateAction<ChatAttachment[]>) => {
      if (controlledAttachments === undefined) setUncontrolledAttachments(update);
      onAttachmentsChange?.(update);
    }, [controlledAttachments, onAttachmentsChange]);
    React.useImperativeHandle(inputRef, () => ({
      focus: () => {},
      selectAll: () => {},
      clear: () => onInputValueChange?.(''),
      appendAttachments: (incoming) => {
        if (disabled || !enableAttachments || incoming.length === 0) return false;
        updateAttachments((current) => [...current, ...incoming]);
        return true;
      },
      replaceSelectionAttachment: (previousFingerprint, nextAttachment) => {
        if (disabled || !enableAttachments) return false;
        const normalizedPreviousFingerprint = previousFingerprint?.trim() ?? '';
        const retained = normalizedPreviousFingerprint
          ? attachments.filter(
              (attachment) => chatAttachmentFingerprint(attachment) !== normalizedPreviousFingerprint,
            )
          : attachments;
        if (!nextAttachment) {
          updateAttachments(retained);
          return true;
        }
        const nextFingerprint = chatAttachmentFingerprint(nextAttachment);
        updateAttachments(retained.some(
          (attachment) => chatAttachmentFingerprint(attachment) === nextFingerprint,
        )
          ? retained
          : [...retained, nextAttachment]);
        return true;
      },
    }), [attachments, disabled, enableAttachments, onInputValueChange, updateAttachments]);
    return (
    <section
      aria-label="智能研读对话"
      data-navigate-evidence-after-select={String(navigateEvidenceAfterSelect)}
    >
      {messages.length === 0 ? emptyState : messages.map((message) => (
        <article key={message.id}>
          <p>{message.content}</p>
          {message.evidence?.map((evidence, index) => (
            <button
              key={`${evidence.evidence_id ?? evidence.chunk_id ?? evidence.material_id ?? 'evidence'}:${index}`}
              type="button"
              data-project-id={projectId ?? ''}
              onClick={() => onSelectEvidence?.(evidence)}
            >
              打开证据 {index + 1}
            </button>
          ))}
          {message.role === 'user' && onEditMessage ? (
            <button type="button" onClick={() => onEditMessage(message)}>
              修改这条消息并从这里继续
            </button>
          ) : null}
          {onForkMessage ? (
            <button type="button" onClick={() => onForkMessage(message)}>
              从这里分叉
            </button>
          ) : null}
          {messageFooter?.(message)}
        </article>
      ))}
      <input
        aria-label="对话输入"
        value={inputValue}
        disabled={disabled}
        onChange={(event) => onInputValueChange?.(event.currentTarget.value)}
      />
      <button
        type="button"
        disabled={disabled || pendingAttachmentReads > 0}
        onClick={() => {
          onSubmit?.({ text: inputValue, attachments, attachmentsEnabled: enableAttachments });
          updateAttachments([]);
        }}
      >
        发送
      </button>
      <button
        type="button"
        onClick={() => updateAttachments((current) => [...current, manualComposerAttachment])}
      >
        模拟添加手动图片
      </button>
      <button
        type="button"
        onClick={() => updateAttachments((current) => [...current, lateManualComposerAttachment])}
      >
        模拟添加延迟图片
      </button>
      <button type="button" onClick={() => updateAttachments([])}>
        模拟丢弃全部图片
      </button>
      <button
        type="button"
        onClick={() => {
          onPendingAttachmentReadsChange?.((current) => current + 1);
          let completed = false;
          completePendingAttachmentRead = () => {
            if (completed) return;
            completed = true;
            updateAttachments((current) => [...current, lateManualComposerAttachment]);
            onPendingAttachmentReadsChange?.((current) => Math.max(0, current - 1));
          };
        }}
      >
        模拟开始延迟附件读取
      </button>
      <button
        type="button"
        onClick={() => updateAttachments(replacementComposerAttachments.slice(0, 5))}
      >
        模拟加入 5 张新图片
      </button>
      <button
        type="button"
        onClick={() => updateAttachments(replacementComposerAttachments)}
      >
        模拟加入 6 张新图片
      </button>
      <button
        type="button"
        onClick={() => onSubmit?.({
          text: inputValue,
          attachments,
          attachmentsEnabled: enableAttachments,
        })}
      >
        模拟强制提交
      </button>
      <output data-testid="composer-attachments">
        {attachments.map((attachment) => attachment.name ?? attachment.mime).join(',')}
      </output>
      {selectionContexts.length > 0 ? (
        <div role="group" aria-label="当前 PDF 选区">
          {selectionContexts.map((selectionContext, index) => (
            <div key={selectionContext.id} data-selection-id={selectionContext.id}>
              <span>{selectionContext.label}</span>
              <span>第 {selectionContext.page} 页</span>
              {selectionContext.text ? <span>{selectionContext.text}</span> : null}
              <button
                type="button"
                onClick={() => {
                  const fingerprint = selectionContext.attachmentFingerprint;
                  if (fingerprint) {
                    updateAttachments(attachments.filter(
                      (attachment) => chatAttachmentFingerprint(attachment) !== fingerprint,
                    ));
                  }
                  onRemoveSelectionContext?.(selectionContext.id);
                }}
                aria-label={selectionContexts.length === 1
                  ? `移除${selectionContext.label}`
                  : `移除选区 ${index + 1}：${selectionContext.label}，第 ${selectionContext.page} 页`}
              >
                移除选区
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {composerContext}
      {responding && onStop ? (
        <button type="button" onClick={onStop}>
          停止生成
        </button>
      ) : null}
      {composerHint && <p>{composerHint}</p>}
    </section>
    );
  },
}));

vi.mock('@/components/PdfViewer/PdfReaderShell', () => ({
  PdfReaderShell: ({
    materialId,
    initialPage,
    initialBbox,
    initialQuote,
    highlights = [],
    analysisDisabled = false,
    formulaCandidates = [],
    selectedVisualRegions = [],
    onPageChange,
    onAnalyzeText,
    onAnalyzeRegion,
  }: {
    materialId: string;
    initialPage?: number;
    initialBbox?: readonly [number, number, number, number];
    initialQuote?: string;
    highlights?: Array<{
      rects?: Array<{ x: number; y: number; w: number; h: number }>;
    }>;
    analysisDisabled?: boolean;
    formulaCandidates?: readonly PdfFormulaCandidate[];
    selectedVisualRegions?: readonly PdfSelectedVisualRegion[];
    onPageChange?: (page: number) => void;
    onAnalyzeText?: (text: string, page: number, anchor?: PdfSelectionAnchor) => void;
    onAnalyzeRegion?: (capture: PdfRegionCapture) => void;
  }) => {
    const emittedInitialPageChange = React.useRef(false);
    React.useEffect(() => {
      if (
        emittedInitialPageChange.current
        || !pdfReaderShellMockState.emitInitialPageChangeOnMount
        || initialPage === undefined
      ) {
        return;
      }
      let cancelled = false;
      void Promise.resolve().then(() => {
        if (cancelled) return;
        emittedInitialPageChange.current = true;
        pdfReaderShellMockState.initialPageChanges.push(initialPage);
        onPageChange?.(initialPage);
      });
      return () => {
        cancelled = true;
      };
    }, [initialPage, onPageChange]);
    return (
      <div
        data-testid="embedded-pdf-reader"
        data-page={initialPage ?? ''}
        data-bbox={initialBbox?.join(',') ?? ''}
        data-quote={initialQuote ?? ''}
        data-highlight-rects={JSON.stringify(highlights.flatMap((highlight) => highlight.rects ?? []))}
      >
        {materialId}
        <output data-testid="formula-candidates">
          {formulaCandidates.map((candidate) => candidate.candidateId).join(',')}
        </output>
        <output data-testid="selected-visual-regions">
          {selectedVisualRegions.map((region) => (
            `${region.kind}:${region.page}:${region.candidateId ?? ''}`
          )).join(',')}
        </output>
        <button type="button" onClick={() => onPageChange?.(7)}>
          模拟翻到第 7 页
        </button>
        <button
          type="button"
          disabled={analysisDisabled}
          onClick={() => onAnalyzeText?.('Selected paragraph with citation [7].', 3, {
            page: 3,
            rects: [{ x: 0.1, y: 0.2, w: 0.5, h: 0.08 }],
          })}
        >
          模拟选择文本
        </button>
        <button
          type="button"
          disabled={analysisDisabled}
          onClick={() => onAnalyzeRegion?.({
            kind: 'figure',
            page: 3,
            bbox: [0.1, 0.2, 0.5, 0.3],
            label: '选中的图',
            image: {
              mime: 'image/png',
              data_b64: 'ZmlndXJlLW9uZQ==',
              size: 10,
              name: 'figure-one.png',
            },
          })}
        >
          模拟选择图
        </button>
        <button
          type="button"
          disabled={analysisDisabled}
          onClick={() => {
            const complete = onAnalyzeRegion;
            completePendingRegionCapture = () => complete?.({
              kind: 'figure',
              page: 3,
              bbox: [0.1, 0.2, 0.5, 0.3],
              label: '延迟返回的图',
              image: {
                mime: 'image/png',
                data_b64: 'ZGVsYXllZC1maWd1cmU=',
                size: 14,
                name: 'delayed-figure.png',
              },
            });
          }}
        >
          模拟开始延迟选择图
        </button>
        <button
          type="button"
          disabled={analysisDisabled}
          onClick={() => onAnalyzeRegion?.({
            kind: 'table',
            page: 4,
            bbox: [0.2, 0.3, 0.4, 0.2],
            label: '选中的表',
            image: {
              mime: 'image/png',
              data_b64: 'dGFibGUtdHdv',
              size: 9,
              name: 'table-two.png',
            },
          })}
        >
          模拟选择表
        </button>
        {formulaCandidates[0] ? (
          <button
            type="button"
            disabled={analysisDisabled}
            onClick={() => {
              const candidate = formulaCandidates[0];
              onAnalyzeRegion?.({
                kind: 'formula',
                page: candidate.page,
                bbox: candidate.bbox,
                label: '选中的公式',
                candidateId: candidate.candidateId,
                chunkId: candidate.chunkId,
                text: candidate.text,
                image: {
                  mime: 'image/png',
                  data_b64: 'Zm9ybXVsYS1lcXVhdGlvbi0x',
                  size: 18,
                  name: 'formula-equation-1.png',
                },
              });
            }}
          >
            模拟选择公式
          </button>
        ) : null}
      </div>
    );
  },
}));

vi.mock('@/components/DiscussionPanel', () => ({
  DiscussionPanel: ({
    initialQuery,
    initialEvidenceMode,
  }: {
    initialQuery?: string;
    initialEvidenceMode?: string;
  }) => (
    <section aria-label="多智能体讨论">
      <textarea aria-label="讨论问题" value={initialQuery ?? ''} readOnly />
      <span>{initialEvidenceMode ?? 'none'}</span>
    </section>
  ),
}));

vi.mock('@/components/graph/WikiGraphSegmentedView', () => ({
  WikiGraphSegmentedView: ({
    payload,
    projectId,
    variant = 'rail',
    selectedDimensions,
    onChangeSelectedDimensions,
    onNavigateTarget,
  }: {
    payload: {
      nodes: Array<{ metadata?: Record<string, unknown> | null }>;
      edges: Array<{ relation: string }>;
    } | null;
    projectId?: string | null;
    variant?: 'rail' | 'explorer';
    selectedDimensions?: Set<string>;
    onChangeSelectedDimensions?: (next: Set<string>) => void;
    onNavigateTarget?: (target: GraphNavigateTarget) => void;
  }) => (
    <div
      data-testid="wiki-graph-segmented-view"
      data-project-id={projectId ?? ''}
      data-variant={variant}
      data-selected={Array.from(selectedDimensions ?? []).join(',')}
      data-dimensions={(payload?.nodes ?? [])
        .map((node) => node.metadata?.reasoning_dimension)
        .filter((value): value is string => typeof value === 'string')
        .join(',')}
      data-relations={(payload?.edges ?? []).map((edge) => edge.relation).join(',')}
    >
      {onChangeSelectedDimensions ? (
        <button type="button" onClick={() => onChangeSelectedDimensions(new Set(['evidence']))}>
          筛选证据
        </button>
      ) : null}
      {onNavigateTarget ? (
        <>
          <button
            type="button"
            onClick={() => onNavigateTarget({
              material_id: 'mat-paper',
              page: 6,
              chunk_id: 'chunk-graph',
              bbox: [0.1, 0.2, 0.4],
              bbox_unit: 'normalized_ratio',
            })}
          >
            模拟图谱跳转到畸形区域
          </button>
          <button
            type="button"
            onClick={() => onNavigateTarget({
              material_id: 'mat-paper',
              page: 0,
              chunk_id: 'chunk-graph',
              bbox: [0.1, 0.2, 0.4, 0.08],
              bbox_unit: 'normalized_ratio',
            })}
          >
            模拟图谱跳转到无效页区域
          </button>
          <button
            type="button"
            onClick={() => onNavigateTarget({
              material_id: 'mat-paper',
              page: 1.5,
              chunk_id: 'chunk-graph',
              bbox: [0.1, 0.2, 0.4, 0.08],
              bbox_unit: 'normalized_ratio',
            })}
          >
            模拟图谱跳转到小数页区域
          </button>
        </>
      ) : null}
    </div>
  ),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: vi.fn(),
}));

vi.mock('@/contexts/SmartReadContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/contexts/SmartReadContext')>();
  return {
    ...actual,
    useSmartRead: vi.fn(),
  };
});

vi.mock('@/hooks/useProjectReasoningBiasState', () => ({
  useProjectReasoningBiasState: () => ({
    loading: false,
    isEnabledForSurface: () => false,
  }),
}));

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: vi.fn(),
}));

vi.mock('@/services/annotationApi', () => ({
  getAnnotations: vi.fn(),
}));

vi.mock('@/services/resourcesApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/resourcesApi')>();
  return {
    ...actual,
    locateChunk: vi.fn(),
  };
});

vi.mock('@/services/agentSidebarApi', () => ({
  createAgentSidebarAnswerRequest: vi.fn(),
  readAgentSidebarReceipt: vi.fn(),
}));

vi.mock('@/services/intelligentChatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/intelligentChatApi')>();
  return {
    ...actual,
    archiveChatSession: vi.fn(),
    deleteChatSession: vi.fn(),
    forkChatHistoryConversation: vi.fn(),
    listChatHistoryAgents: vi.fn(),
    listChatSessions: vi.fn(),
    restoreChatSession: vi.fn(),
    resumeChatSession: vi.fn(),
    searchChatHistory: vi.fn(),
    streamIntelligentChatMessage: vi.fn(),
  };
});

vi.mock('@/services/graphApi', () => ({
  getAnswerEvidenceGraph: vi.fn(),
}));

vi.mock('@/services/smartReadTiers', () => ({
  backendTierForCostTier: () => 'balanced',
  loadSmartReadCostTier: () => 'medium',
}));

vi.mock('axios', () => ({
  default: {
    isAxiosError: () => false,
  },
}));

const mockedUseWriting = vi.mocked(useWriting);
const mockedUseSmartRead = vi.mocked(useSmartRead);
const mockedGetWritingBackendService = vi.mocked(getWritingBackendService);
const mockedListChatSessions = vi.mocked(listChatSessions);
const mockedGetAnnotations = vi.mocked(getAnnotations);
const mockedStreamIntelligentChatMessage = vi.mocked(streamIntelligentChatMessage);
const mockedLocateChunk = vi.mocked(locateChunk);
const mockedReadAgentSidebarReceipt = vi.mocked(readAgentSidebarReceipt);
const mockedCreateAgentSidebarAnswerRequest = vi.mocked(createAgentSidebarAnswerRequest);

function createDeferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
} {
  let resolveRef: ((value: T) => void) | null = null;
  let rejectRef: ((reason?: unknown) => void) | null = null;
  const promise = new Promise<T>((resolve, reject) => {
    resolveRef = resolve;
    rejectRef = reject;
  });
  if (!resolveRef || !rejectRef) {
    throw new Error('Failed to create deferred promise');
  }
  return { promise, resolve: resolveRef, reject: rejectRef };
}

describe('Dialog error helpers', () => {
  it('reads fallback dialog error text without leaking object literals', () => {
    expect(readDialogErrorText(new Error('no literature source paths configured'))).toBe('no literature source paths configured');
    expect(readDialogErrorText('plain string')).toBe('plain string');
    expect(readDialogErrorText(null)).toBe('');
  });

  it('detects unavailable-state errors through non-axios fallback messages', () => {
    expect(isUnavailableError(new Error('No literature source paths configured for this workspace'))).toBe(true);
    expect(isUnavailableError(new Error('/api/chat env=VISION_PROVIDER capability_resolved'))).toBe(false);
  });
});

describe('Dialog current PDF context helper', () => {
  it('normalizes and deduplicates formula-candidate endpoint resources', () => {
    expect(buildDialogFormulaCandidatesFromResources([
      {
        candidate_id: ' formula-1 ',
        page: 3,
        bbox: [0.1, 0.2, 0.5, 0.08],
        bbox_unit: 'normalized_ratio',
        chunk_id: ' chunk-3 ',
        text: '  E = mc^2  ',
      },
      {
        candidate_id: 'formula-1',
        page: 4,
        bbox: [0.2, 0.3, 0.4, 0.07],
        bbox_unit: 'normalized_ratio',
        chunk_id: null,
        text: null,
      },
    ])).toEqual([{
      candidateId: 'formula-1',
      page: 3,
      bbox: [0.1, 0.2, 0.5, 0.08],
      chunkId: 'chunk-3',
      text: 'E = mc^2',
    }]);
  });

  it('builds a bounded SmartRead current-PDF selection anchor', () => {
    expect(buildDialogCurrentPdfContext({
      materialId: ' mat-paper ',
      page: 6,
      selectedText: '  selected\nPDF\ttext  ',
      bbox: [0.1, 0.2, 0.3, 0.1],
      bboxUnit: 'normalized_ratio',
    })).toEqual({
      material_id: 'mat-paper',
      page: 6,
      bbox: [0.1, 0.2, 0.3, 0.1],
      bbox_unit: 'normalized_ratio',
      selected_text: 'selected PDF text',
      context_kind: 'selection',
      source_labels: ['dialog_smart_read', 'pdf_selection'],
    });
  });

  it('normalizes nested text selections without duplicating the selected passage into the question', () => {
    expect(buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      selection: {
        kind: 'text',
        page: 4,
        text: '  complete paragraph\nwith citation [7]  ',
        bbox: [0.1, 0.2, 0.5, 0.08],
        bbox_unit: 'normalized_ratio',
        label: '选中的文本',
      },
    })).toEqual({
      material_id: 'mat-paper',
      page: 4,
      bbox: [0.1, 0.2, 0.5, 0.08],
      bbox_unit: 'normalized_ratio',
      selected_text: 'complete paragraph with citation [7]',
      selection: {
        kind: 'text',
        page: 4,
        text: 'complete paragraph with citation [7]',
        bbox: [0.1, 0.2, 0.5, 0.08],
        bbox_unit: 'normalized_ratio',
        label: '选中的文本',
      },
      selections: [{
        kind: 'text',
        page: 4,
        text: 'complete paragraph with citation [7]',
        bbox: [0.1, 0.2, 0.5, 0.08],
        bbox_unit: 'normalized_ratio',
        label: '选中的文本',
      }],
      context_kind: 'selection',
      source_labels: ['dialog_smart_read', 'pdf_selection'],
    });
  });

  it('builds a visual selection context using metadata and normalized bbox only', () => {
    expect(buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      selection: {
        kind: 'table',
        page: 8,
        bbox: [0.12, 0.25, 0.6, 0.3],
        bbox_unit: 'normalized_ratio',
        label: '选中的表',
      },
    })).toEqual({
      material_id: 'mat-paper',
      page: 8,
      bbox: [0.12, 0.25, 0.6, 0.3],
      bbox_unit: 'normalized_ratio',
      selection: {
        kind: 'table',
        page: 8,
        text: null,
        bbox: [0.12, 0.25, 0.6, 0.3],
        bbox_unit: 'normalized_ratio',
        label: '选中的表',
      },
      selections: [{
        kind: 'table',
        page: 8,
        text: null,
        bbox: [0.12, 0.25, 0.6, 0.3],
        bbox_unit: 'normalized_ratio',
        label: '选中的表',
      }],
      context_kind: 'selection',
      source_labels: ['dialog_smart_read', 'pdf_selection'],
    });
  });

  it('strips image bytes and local asset paths from nested selection metadata', () => {
    const unsafeSelection = {
      kind: 'figure',
      page: 5,
      bbox: [0.1, 0.2, 0.4, 0.3],
      bbox_unit: 'normalized_ratio',
      label: '选中的图',
      asset_path: 'C:\\private\\figure.png',
      data_b64: 'c2Vuc2l0aXZlLWltYWdl',
    } as unknown as PdfContentSelection;

    const context = buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      selection: unsafeSelection,
    });

    expect(context?.selection).not.toHaveProperty('asset_path');
    expect(context?.selection).not.toHaveProperty('data_b64');
    expect(context?.selection).toEqual({
      kind: 'figure',
      page: 5,
      text: null,
      bbox: [0.1, 0.2, 0.4, 0.3],
      bbox_unit: 'normalized_ratio',
      label: '选中的图',
    });
    expect(context?.selections).toEqual([context?.selection]);
  });

  it('preserves ordered mixed selections while keeping the first selection compatibility field', () => {
    const context = buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      selections: [
        {
          kind: 'figure',
          page: 3,
          image_index: 1,
          bbox: [0.1, 0.2, 0.5, 0.3],
          bbox_unit: 'normalized_ratio',
          label: '选中的图',
        },
        {
          kind: 'text',
          page: 4,
          text: 'Paragraph with citation [8].',
          bbox: [0.1, 0.55, 0.6, 0.08],
          bbox_unit: 'normalized_ratio',
          label: '选中的文本',
        },
      ],
    });

    expect(context?.selection).toEqual(expect.objectContaining({
      kind: 'figure',
      page: 3,
      image_index: 1,
    }));
    expect(context?.selections).toEqual([
      expect.objectContaining({ kind: 'figure', page: 3, image_index: 1 }),
      expect.objectContaining({
        kind: 'text',
        page: 4,
        text: 'Paragraph with citation [8].',
      }),
    ]);
    expect(context?.selections?.[1]).not.toHaveProperty('image_index');
  });

  it('drops malformed current-PDF anchors before they reach the API', () => {
    expect(buildDialogCurrentPdfContext({ materialId: 'mat-paper' })).toBeUndefined();
    expect(buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      page: 2,
      bbox: [2, 0, 0.3, 0.1],
      bboxUnit: 'normalized_ratio',
    })).toEqual({
      material_id: 'mat-paper',
      page: 2,
      context_kind: 'reader_page',
      source_labels: ['dialog_smart_read', 'pdf_reader_page'],
    });
  });

  it('preserves chunk ids for PDF deep-link SmartRead context', () => {
    expect(buildDialogCurrentPdfContext({
      materialId: 'mat-paper',
      page: 1,
      chunkId: 'mat-paper_chunk_0',
      bbox: [0.12, 0.2, 0.32, 0.08],
      bboxUnit: 'normalized_ratio',
    })).toEqual({
      material_id: 'mat-paper',
      page: 1,
      chunk_id: 'mat-paper_chunk_0',
      bbox: [0.12, 0.2, 0.32, 0.08],
      bbox_unit: 'normalized_ratio',
      context_kind: 'deep_link',
      source_labels: ['dialog_smart_read', 'pdf_reader_page'],
    });
  });

  it('does not infer normalized_ratio for unitless or pdf_points deep-link geometry', () => {
    for (const bboxUnit of [undefined, 'pdf_points' as const]) {
      expect(buildDialogCurrentPdfContext({
        materialId: 'mat-paper',
        page: 2,
        chunkId: 'chunk-page-only',
        bbox: bboxUnit ? [72, 144, 180, 36] : [0.1, 0.2, 0.4, 0.1],
        bboxUnit,
      })).toEqual({
        material_id: 'mat-paper',
        page: 2,
        chunk_id: 'chunk-page-only',
        context_kind: 'deep_link',
        source_labels: ['dialog_smart_read', 'pdf_reader_page'],
      });
    }
  });
});

describe('Dialog SmartRead session bridge', () => {
  it('uses artifact chat session ids instead of runtime session ids', () => {
    expect(resolveDialogSmartReadChatSessionId({ session_id: ' chat-session-1 ' }, null))
      .toBe('chat-session-1');
    expect(resolveDialogSmartReadChatSessionId({}, null)).toBeUndefined();
    expect(resolveDialogSmartReadChatSessionId({}, 'existing-chat-session')).toBe('existing-chat-session');
  });
});

const mockedResumeChatSession = vi.mocked(resumeChatSession);
const mockedRestoreChatSession = vi.mocked(restoreChatSession);
const mockedGetAnswerEvidenceGraph = vi.mocked(getAnswerEvidenceGraph);

function renderDialog(initialEntries: string[] = ['/dialog']): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <PdfTabsProvider>
        <Dialog />
      </PdfTabsProvider>
    </MemoryRouter>,
  );
}

const projectSession: ChatSessionSummary = {
  session_id: 'session-project-b',
  project_id: 'project-b',
  title: '项目 B 历史会话',
  preview: '项目 B 旧问题',
  total_turns: 2,
  total_tokens: 12,
  created_at: '2026-05-29T00:00:00.000Z',
  updated_at: '2026-05-29T00:03:00.000Z',
};

const projectASession: ChatSessionSummary = {
  session_id: 'session-project-a',
  project_id: 'project-a',
  title: '项目 A 历史会话',
  preview: '项目 A 旧问题',
  total_turns: 1,
  total_tokens: 6,
  created_at: '2026-05-29T00:00:00.000Z',
  updated_at: '2026-05-29T00:02:00.000Z',
};

const archivedProjectSession: ChatSessionSummary = {
  ...projectSession,
  archived: true,
  archived_at: '2026-05-29T00:04:00.000Z',
};

const resumedProjectConversation: ChatResumeResponse = {
  session_id: 'session-project-b',
  project_id: 'project-b',
  messages: [
    {
      id: 'u-project-b',
      role: 'user',
      content: '项目 B 的问题',
      timestamp: '2026-05-29T00:01:00.000Z',
    },
    {
      id: 'a-project-b',
      role: 'assistant',
      content: '项目 B 的回答',
      timestamp: '2026-05-29T00:02:00.000Z',
      tier_used: 'balanced',
      context_metadata: { chunks: [], truncated: false },
      evidence_refs: [],
      tokens_used: { prompt: 3, completion: 4, total: 7 },
    },
  ],
};

describe('Dialog history project resume', () => {
  const setActiveProjectId = vi.fn();
  const setConversation = vi.fn();
  const clearConversation = vi.fn();
  let conversationMessages: ChatMessageData[] = [];

  beforeEach(() => {
    vi.clearAllMocks();
    pdfReaderShellMockState.emitInitialPageChangeOnMount = false;
    pdfReaderShellMockState.initialPageChanges.length = 0;
    completePendingAttachmentRead = null;
    completePendingRegionCapture = null;
    window.localStorage.clear();
    window.sessionStorage.clear();
    conversationMessages = [];
    mockedGetAnswerEvidenceGraph.mockResolvedValue({
      version: 'v1',
      scope: { kind: 'question', ref: '' },
      updated_at: '2026-05-29T00:00:00.000Z',
      nodes: [],
      edges: [],
      warnings: [],
    });
    mockedUseWriting.mockReturnValue({
      activeProjectId: 'project-a',
      setActiveProjectId,
      activeJournalStyleProfileId: '',
      setActiveJournalStyleProfileId: vi.fn(),
      projectDataVersion: 0,
      markProjectDataChanged: vi.fn(),
      activeSectionId: '',
      setActiveSectionId: vi.fn(),
      outputMode: 'markdown',
      setOutputMode: vi.fn(),
      scope: 'section',
      setScope: vi.fn(),
      connectionState: 'online',
      setConnectionState: vi.fn(),
      sessionStatus: 'idle',
      setSessionStatus: vi.fn(),
      sessionMessage: null,
      setSessionMessage: vi.fn(),
      activeJobTimeline: null,
      setActiveJobTimeline: vi.fn(),
      leftNavCollapsed: false,
      setLeftNavCollapsed: vi.fn(),
      rightDockMode: 'assistant',
      setRightDockMode: vi.fn(),
      zenMode: false,
      setZenMode: vi.fn(),
      citationDrawerOpen: false,
      setCitationDrawerOpen: vi.fn(),
    });
    mockedUseSmartRead.mockReturnValue({
      getConversation: () => ({ messages: conversationMessages, updatedAt: 0, pending: false }),
      sendMessage: vi.fn(),
      stopMessage: vi.fn(),
      setConversation,
      appendMessages: vi.fn(),
      clearConversation,
    });
    listProjectsMock.mockResolvedValue([
        {
          project_id: 'project-a',
          title: '项目 A',
          description: '',
          status: 'active',
          created_at: '2026-05-29T00:00:00.000Z',
          updated_at: '2026-05-29T00:00:00.000Z',
        },
        {
          project_id: 'project-b',
          title: '项目 B',
          description: '',
          status: 'active',
          created_at: '2026-05-29T00:00:00.000Z',
          updated_at: '2026-05-29T00:00:00.000Z',
        },
      ]);
    listMaterialsMock.mockResolvedValue([]);
    listMaterialChunksMock.mockResolvedValue({
      material_id: 'mat-paper',
      total_chunks: 0,
      chunks: [],
    });
    listFormulaCandidatesMock.mockResolvedValue({
      project_id: 'project-a',
      material_id: 'mat-paper',
      candidates: [],
    });
    listFigureTableCandidatesMock.mockResolvedValue([]);
    mockedLocateChunk.mockResolvedValue(null);
    mockedGetWritingBackendService.mockReturnValue({
      listProjects: listProjectsMock,
      listMaterials: listMaterialsMock,
      listMaterialChunks: listMaterialChunksMock,
      listFormulaCandidates: listFormulaCandidatesMock,
      listFigureTableCandidates: listFigureTableCandidatesMock,
    } as unknown as ReturnType<typeof getWritingBackendService>);
    mockedGetAnnotations.mockResolvedValue({
      material_id: 'mat-paper',
      highlights: [],
      notes: [],
      last_page: null,
    });
    mockedReadAgentSidebarReceipt.mockResolvedValue({
      conversation_id: 'sidebar-session-1',
      project_id: 'project-a',
      answer: '默认回答',
      receipt: {
        receipt_schema_version: 'scholar-ai-answer-receipt/v1',
        project_id: 'project-a',
        question: '默认问题',
        answer: '默认回答',
        top_evidence_refs: [],
      },
      staleness: {
        status: 'saved',
        checked: [],
        warnings: [],
        mismatches: [],
      },
    } as Awaited<ReturnType<typeof readAgentSidebarReceipt>>);
    mockedCreateAgentSidebarAnswerRequest.mockResolvedValue({
      request_id: 'agentreq_desktop',
      job: {
        job_id: 'job_desktop',
        status: 'started',
        metadata: {},
      },
      poll: { job: '/runtime/job/job_desktop' },
      envelope: {
        intent: 'sidebar_answer',
        project_id: 'project-a',
        user_text: '默认问题',
        resource_refs: [],
      },
    });
    mockedListChatSessions.mockResolvedValue([projectSession]);
    mockedResumeChatSession.mockResolvedValue(resumedProjectConversation);
  });

  it('restores project-bound history into that project scope and switches the active project', async () => {
    renderDialog();

    fireEvent.click(await screen.findByRole('button', { name: '项目 B 历史会话' }));

    await waitFor(() => {
      expect(setActiveProjectId).toHaveBeenCalledWith('project-b');
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-b'),
        expect.arrayContaining([
          expect.objectContaining({ id: 'u-project-b', role: 'user', content: '项目 B 的问题' }),
          expect.objectContaining({ id: 'a-project-b', role: 'assistant', content: '项目 B 的回答' }),
        ]),
        { sessionId: 'session-project-b' },
      );
    });
    expect(mockedResumeChatSession).toHaveBeenCalledWith({ session_id: 'session-project-b', limit: 100 });
  });

  it('restores ordered research selections from backend history without pixel fields', async () => {
    mockedResumeChatSession.mockResolvedValueOnce({
      session_id: 'session-project-b',
      project_id: 'project-b',
      messages: [{
        id: 'u-history-selection',
        role: 'user',
        turn_id: 'turn-history-selection',
        content: '解释历史选区',
        timestamp: '2026-07-15T01:00:00.000Z',
        research_selections: [{
          schema_version: 'scholar-ai-research-selection/v1',
          selection_id: 'selection-history-1',
          turn_id: 'turn-history-selection',
          group_id: 'group-history-selection',
          order: 0,
          material_id: 'material-history',
          kind: 'table',
          page: 7,
          bbox: [0.1, 0.2, 0.6, 0.3],
          bbox_unit: 'normalized_ratio',
        }],
      }, {
        id: 'a-history-selection',
        role: 'assistant',
        turn_id: 'turn-history-selection',
        content: '历史回答',
        timestamp: '2026-07-15T01:01:00.000Z',
        visual_observation_refs: [dialogVisualObservationReference('turn-history-selection')],
      }],
    });

    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: '项目 B 历史会话' }));

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-b'),
        expect.arrayContaining([
          expect.objectContaining({
            id: 'u-history-selection',
            turnId: 'turn-history-selection',
            researchSelections: [expect.objectContaining({
              selection_id: 'selection-history-1',
              order: 0,
              kind: 'table',
              page: 7,
            })],
          }),
          expect.objectContaining({
            id: 'a-history-selection',
            turnId: 'turn-history-selection',
            visualObservationRefs: [dialogVisualObservationReference('turn-history-selection')],
          }),
        ]),
        { sessionId: 'session-project-b' },
      );
    });
    const restoredCall = setConversation.mock.calls.find(
      (call) => (call[1] as ChatMessageData[]).some((message) => message.id === 'u-history-selection'),
    );
    expect(JSON.stringify(restoredCall?.[1])).not.toContain('image_index');
    expect(JSON.stringify(restoredCall?.[1])).not.toContain('data_b64');
  });

  it('restores a SmartRead receipt when Dialog opens with conversation_id', async () => {
    mockedResumeChatSession.mockResolvedValue({
      session_id: 'sidebar_agentreq_dbb39bc8f3784108',
      project_id: 'project-a',
      messages: [
        {
          id: 'u-sidebar-receipt',
          role: 'user',
          content: '侧栏交接问题',
          timestamp: '2026-07-09T14:00:00.000Z',
        },
        {
          id: 'a-sidebar-receipt',
          role: 'assistant',
          content: '侧栏交接回答',
          timestamp: '2026-07-09T14:01:00.000Z',
          tier_used: 'balanced',
          context_metadata: { chunks: [], truncated: false },
          evidence_refs: [],
          tokens_used: { prompt: 3, completion: 4, total: 7 },
        },
      ],
    });

    renderDialog(['/dialog?project_id=project-a&conversation_id=sidebar_agentreq_dbb39bc8f3784108']);

    await waitFor(() => {
      expect(mockedResumeChatSession).toHaveBeenCalledWith({
        session_id: 'sidebar_agentreq_dbb39bc8f3784108',
        limit: 100,
      });
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({ id: 'u-sidebar-receipt', role: 'user', content: '侧栏交接问题' }),
          expect.objectContaining({ id: 'a-sidebar-receipt', role: 'assistant', content: '侧栏交接回答' }),
        ]),
        { sessionId: 'sidebar_agentreq_dbb39bc8f3784108' },
      );
    });
  });

  it('restores display-only visual evidence for an ordinary SmartRead question without a candidate reload', async () => {
    mockedResumeChatSession.mockResolvedValue({
      ...resumedProjectConversation,
      messages: [
        {
          id: 'u-appearance',
          role: 'user',
          content: '解释 AlSi10Mg 激光焊接孔隙与工艺参数的关系',
          timestamp: '2026-05-29T00:01:00.000Z',
        },
        {
          id: 'a-appearance',
          role: 'assistant',
          content: '可以查看 Fig. 4 的焊缝外观图。',
          timestamp: '2026-05-29T00:02:00.000Z',
          tier_used: 'balanced',
          context_metadata: { chunks: [], truncated: false },
          evidence_refs: [
            {
              chunk_id: 'chunk-fig-4',
              material_id: 'mat-weld',
              source: 'Laser welding of AlSi10Mg',
              text: 'Fig. 4 shows weld appearance.',
              quote: 'Fig. 4 shows weld appearance.',
            },
          ],
          visual_evidence_refs: [
            {
              chunk_id: 'chunk-fig-4',
              material_id: 'mat-weld',
              source: 'Laser welding of AlSi10Mg',
              text: 'Fig. 4 shows weld appearance and porosity.',
              quote: 'Fig. 4 shows weld appearance and porosity.',
              figure_candidate: 'Fig. 4',
              figure_candidate_detail: {
                figure_id: 'Fig. 4',
                caption: 'Weld appearance macrograph.',
                anchor_chunk_id: 'chunk-fig-4',
              },
              image_paths: ['figures/mat-weld/fig-4.png'],
            },
          ],
          tokens_used: { prompt: 3, completion: 4, total: 7 },
        },
      ],
    });

    renderDialog();

    fireEvent.click(await screen.findByRole('button', { name: '项目 B 历史会话' }));

    await waitFor(() => {
      expect(listFigureTableCandidatesMock).not.toHaveBeenCalled();
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-b'),
        expect.arrayContaining([
          expect.objectContaining({
            id: 'a-appearance',
            relatedFigures: [
              expect.objectContaining({
                chunk_id: 'chunk-fig-4',
                material_id: 'mat-weld',
                label: 'Fig. 4',
                asset_path: 'figures/mat-weld/fig-4.png',
                source: 'chunk_image_paths',
              }),
            ],
          }),
        ]),
        { sessionId: 'session-project-b' },
      );
    });
  });

  it('collapses legacy workspace SmartRead scope into the project-literature scope control', async () => {
    renderDialog(['/dialog?project_id=project-a&scope=workspace']);

    const conversationRegion = await screen.findByRole('region', { name: '智能研读对话' });
    expect(within(conversationRegion).queryByRole('button', { name: '全项目' })).not.toBeInTheDocument();
    fireEvent.click(within(conversationRegion).getByRole('button', { name: '范围' }));
    expect(within(conversationRegion).getByRole('menuitemradio', { name: '项目文献' }))
      .toHaveAttribute('aria-checked', 'true');
  });

  it('keeps all SmartRead composer functions behind collapsed menu controls', async () => {
    renderDialog(['/dialog?project_id=project-a']);

    const conversationRegion = await screen.findByRole('region', { name: '智能研读对话' });
    for (const label of ['范围', '给智能体', '增强']) {
      const control = within(conversationRegion).getByRole('button', { name: label });
      expect(control).toHaveAttribute('aria-haspopup', 'menu');
      expect(control).toHaveAttribute('aria-expanded', 'false');
    }
    expect(within(conversationRegion).queryByRole('button', { name: /给 Claude/ })).not.toBeInTheDocument();
    expect(within(conversationRegion).queryByRole('button', { name: '回答' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitemradio', { name: '智能体回答' })).not.toBeInTheDocument();
  });

  it('ignores duplicate same-tick clicks while a history session is restoring', async () => {
    renderDialog();

    const historyButton = await screen.findByRole('button', { name: '项目 B 历史会话' });
    await act(async () => {
      historyButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      historyButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    await waitFor(() => {
      expect(mockedResumeChatSession).toHaveBeenCalledTimes(1);
    });
    expect(mockedResumeChatSession).toHaveBeenCalledWith({ session_id: 'session-project-b', limit: 100 });
  });

  it('groups SmartRead history sessions by project in the left rail', async () => {
    mockedListChatSessions.mockResolvedValue([projectASession, projectSession]);

    renderDialog();

    expect(await screen.findByText('项目 A')).toBeInTheDocument();
    expect(screen.getByText('项目 B')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '项目 A 历史会话' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '项目 B 历史会话' })).toBeInTheDocument();
  });

  it('loads archived SmartRead sessions and restores them from the left rail', async () => {
    mockedListChatSessions
      .mockResolvedValueOnce([projectSession])
      .mockResolvedValueOnce([archivedProjectSession]);

    renderDialog();

    fireEvent.click((await screen.findAllByRole('button', { name: '归档' }))[0]);
    fireEvent.click(await screen.findByRole('button', { name: '恢复' }));

    await waitFor(() => {
      expect(mockedListChatSessions).toHaveBeenLastCalledWith(15000, { archivedOnly: true });
      expect(mockedRestoreChatSession).toHaveBeenCalledWith('session-project-b');
    });
  });

  it('stops an active Dialog response by marking the streaming assistant message done', async () => {
    conversationMessages = [
      {
        id: 'u1',
        role: 'user',
        content: 'hi',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
      },
      {
        id: 'a1',
        role: 'assistant',
        content: '',
        timestamp: '2026-05-29T00:01:01.000Z',
        status: 'streaming',
      },
    ];

    renderDialog();

    fireEvent.click(await screen.findByRole('button', { name: '停止生成' }));

    expect(setConversation).toHaveBeenCalledWith(
      smartReadDialogScope('project-a'),
      expect.arrayContaining([
        expect.objectContaining({ id: 'a1', role: 'assistant', content: '已停止生成。', status: 'done' }),
      ]),
    );
  });

  it('renders the current context graph through the segmented dimension viewer', async () => {
    window.localStorage.setItem('dialog-context-tab-v1', 'graph');
    conversationMessages = [
      {
        id: 'u-graph',
        role: 'user',
        content: '这篇论文的核心证据是什么？',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
      },
      {
        id: 'a-graph',
        role: 'assistant',
        content: '证据来自文献片段。',
        timestamp: '2026-05-29T00:01:01.000Z',
        status: 'done',
        evidence: [
          {
            source: 'Reis 等 · 2013',
            text: 'Creep behavior evidence.',
            material_id: 'mat-paper',
            chunk_id: 'chunk-1',
            page: 3,
          },
        ],
      },
    ];

    renderDialog(['/dialog?project_id=project-a&material_id=mat-paper']);
    fireEvent.click(await screen.findByRole('button', { name: /图谱/ }));

    const viewer = await screen.findByTestId('wiki-graph-segmented-view');
    expect(viewer).toHaveAttribute('data-project-id', 'project-a');
    expect(viewer).toHaveAttribute('data-variant', 'rail');
    expect(viewer.getAttribute('data-dimensions')).toContain('question');
    expect(viewer.getAttribute('data-dimensions')).toContain('evidence');

    fireEvent.click(within(viewer).getByRole('button', { name: '筛选证据' }));
    expect(viewer).toHaveAttribute('data-selected', 'evidence');
    expect(within(viewer).queryByRole('button', { name: '展开图谱' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '展开' }));

    const graphDialog = await screen.findByRole('dialog', { name: '当前上下文图谱' });
    const workspace = screen.getByLabelText('智能研读工作区') as HTMLElement;
    expect(workspace).toHaveAttribute('aria-hidden', 'true');
    expect(workspace.inert).toBe(true);
    const explorer = within(graphDialog).getByTestId('wiki-graph-segmented-view');
    expect(explorer).toHaveAttribute('data-variant', 'explorer');
    expect(explorer).toHaveAttribute('data-selected', 'evidence');

    fireEvent.click(within(graphDialog).getByRole('button', { name: '关闭图谱工作台' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '当前上下文图谱' })).not.toBeInTheDocument());
    expect(workspace).not.toHaveAttribute('aria-hidden');
    expect(workspace.inert).toBe(false);
  });

  it('keeps a Graph target page but discards a malformed bbox at the Dialog boundary', async () => {
    conversationMessages = [
      {
        id: 'u-graph-navigation',
        role: 'user',
        content: '打开图谱证据。',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
      },
      {
        id: 'a-graph-navigation',
        role: 'assistant',
        content: '证据来自文献片段。',
        timestamp: '2026-05-29T00:01:01.000Z',
        status: 'done',
        evidence: [{
          source: 'paper.pdf',
          text: 'Graph evidence.',
          material_id: 'mat-paper',
          chunk_id: 'chunk-graph',
          page: 3,
        }],
      },
    ];
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);
    fireEvent.click(await screen.findByRole('button', { name: /图谱/ }));
    const graph = await screen.findByTestId('wiki-graph-segmented-view');
    fireEvent.click(within(graph).getByRole('button', { name: '模拟图谱跳转到畸形区域' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '6');
      expect(reader).toHaveAttribute('data-bbox', '');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
  });

  it('falls back to the document when a Graph target has an invalid page', async () => {
    conversationMessages = [{
      id: 'a-graph-invalid-page',
      role: 'assistant',
      content: '图谱目标页无效时只能打开文献。',
      timestamp: '2026-05-29T00:01:01.000Z',
      status: 'done',
      evidence: [{
        source: 'paper.pdf',
        text: 'Graph evidence.',
        material_id: 'mat-paper',
        chunk_id: 'chunk-graph',
        page: 3,
      }],
    }];
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);
    fireEvent.click(await screen.findByRole('button', { name: /图谱/ }));
    const graph = await screen.findByTestId('wiki-graph-segmented-view');
    fireEvent.click(within(graph).getByRole('button', { name: '模拟图谱跳转到无效页区域' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '');
      expect(reader).toHaveAttribute('data-bbox', '');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
  });

  it('does not round a fractional Graph target into a fabricated PDF page', async () => {
    conversationMessages = [{
      id: 'a-graph-fractional-page',
      role: 'assistant',
      content: '图谱目标页不是整数时只能打开文献。',
      timestamp: '2026-05-29T00:01:01.000Z',
      status: 'done',
      evidence: [{
        source: 'paper.pdf',
        text: 'Graph evidence.',
        material_id: 'mat-paper',
        chunk_id: 'chunk-graph',
        page: 3,
      }],
    }];
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);
    fireEvent.click(await screen.findByRole('button', { name: /图谱/ }));
    const graph = await screen.findByTestId('wiki-graph-segmented-view');
    fireEvent.click(within(graph).getByRole('button', { name: '模拟图谱跳转到小数页区域' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '');
      expect(reader).toHaveAttribute('data-bbox', '');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
  });

  it('loads the exact persisted answer turn graph and exposes its citation edge', async () => {
    window.localStorage.setItem('dialog-context-tab-v1', 'graph');
    conversationMessages = [
      {
        id: 'u-remote-graph',
        role: 'user',
        turnId: 'turn-remote-graph',
        content: '这段回答引用了哪篇项目文献？',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
      },
      {
        id: 'a-remote-graph',
        role: 'assistant',
        turnId: 'turn-remote-graph',
        content: '回答引用了项目内的目标文献。',
        timestamp: '2026-05-29T00:01:01.000Z',
        status: 'done',
        evidence: [{
          source: 'Source Paper',
          text: 'Citation context.',
          material_id: 'paper-source',
          chunk_id: 'chunk-source',
          page: 4,
        }],
      },
    ];
    mockedUseSmartRead.mockReturnValue({
      getConversation: () => ({
        messages: conversationMessages,
        updatedAt: 0,
        pending: false,
        sessionId: 'session-remote-graph',
      }),
      sendMessage: vi.fn(),
      stopMessage: vi.fn(),
      setConversation,
      appendMessages: vi.fn(),
      clearConversation,
    });
    mockedGetAnswerEvidenceGraph.mockResolvedValue({
      version: 'v1',
      scope: { kind: 'question', ref: 'turn-remote-graph' },
      updated_at: '2026-05-29T00:01:02.000Z',
      nodes: [
        {
          id: 'paper-source',
          label: 'Source Paper',
          type: 'paper',
          status: 'candidate',
          confidence: 0.9,
          provenance_refs: [{ material_id: 'paper-source', quote: 'Citation context.' }],
          metadata: { turn_id: 'turn-remote-graph' },
        },
        {
          id: 'paper-target',
          label: 'Target Paper',
          type: 'paper',
          status: 'candidate',
          confidence: 0.9,
          provenance_refs: [{ material_id: 'paper-target', quote: 'Reference entry.' }],
          metadata: { turn_id: 'turn-remote-graph' },
        },
      ],
      edges: [{
        id: 'cites-remote-graph',
        source: 'paper-source',
        target: 'paper-target',
        relation: 'cites',
        direction: 'directed',
        status: 'candidate',
        confidence: 0.9,
        provenance_refs: [{ material_id: 'paper-source', quote: 'Reference [7].' }],
        created_by: 'runtime_capture',
        updated_at: '2026-05-29T00:01:02.000Z',
        metadata: { turn_id: 'turn-remote-graph' },
      }],
      warnings: [],
    });

    renderDialog(['/dialog?project_id=project-a&material_id=paper-source']);
    fireEvent.click(await screen.findByRole('button', { name: /图谱/ }));

    await waitFor(() => {
      expect(mockedGetAnswerEvidenceGraph).toHaveBeenCalledWith({
        session_id: 'session-remote-graph',
        turn_id: 'turn-remote-graph',
      });
    });
    expect(await screen.findByTestId('wiki-graph-segmented-view')).toHaveAttribute(
      'data-relations',
      'cites',
    );

    fireEvent.click(screen.getByTitle('刷新当前项目材料和图谱'));
    await waitFor(() => expect(mockedGetAnswerEvidenceGraph).toHaveBeenCalledTimes(2));
  });

  it('restores a streaming draft without creating an empty assistant bubble', async () => {
    conversationMessages = [
      {
        id: 'u1',
        role: 'user',
        content: 'hi',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
      },
      {
        id: 'a1',
        role: 'assistant',
        content: '',
        timestamp: '2026-05-29T00:01:01.000Z',
        status: 'streaming',
      },
    ];

    renderDialog();

    expect(await screen.findByRole('button', { name: '停止生成' })).toBeInTheDocument();
    expect(screen.queryByText('AI 思考中…')).not.toBeInTheDocument();
  });

  it('persists a completed streaming SmartRead answer after navigating away', async () => {
    const completedStream = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent?.({
        event: 'metadata',
        session_id: 'chat-session-1',
        context_chunks_used: 0,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
      });
      options.onEvent?.({
        event: 'text_delta',
        delta: '激光焊接参数公式回答已生成。',
      });
      options.onEvent?.({
        event: 'done',
        response: '激光焊接参数公式回答已生成。',
        session_id: 'chat-session-1',
        tokens_used: { prompt: 3, completion: 4, total: 7 },
      });
      await completedStream.promise;
    });

    const rendered = renderDialog(['/dialog?project_id=project-a']);

    fireEvent.change(await screen.findByLabelText('对话输入'), {
      target: { value: '激光焊接参数公式是什么？' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledOnce();
    });
    rendered.unmount();

    await act(async () => {
      completedStream.resolve();
    });

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({ role: 'assistant', content: '激光焊接参数公式回答已生成。', status: 'done' }),
        ]),
        { sessionId: 'chat-session-1' },
      );
    });
  });

  it('persists streamed evidence identity without collapsing quote or relabeling bbox units', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent?.({
        event: 'metadata',
        session_id: 'chat-session-evidence-integrity',
        context_chunks_used: 2,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [{
          chunk_id: 'chunk-points',
          material_id: 'material-points',
          source: 'Points paper.pdf',
          text: 'Full points chunk text.',
          quote: 'Exact points sentence.',
          anchor_kind: 'text',
          bbox: [72, 144, 180, 36],
          bbox_unit: 'pdf_points',
          content_hash: 'a'.repeat(64),
          locator_hash: 'b'.repeat(64),
          chunk_hash: 'c'.repeat(64),
          embedding_input_hash: 'd'.repeat(64),
          hash_version: 'scholar-ai-chunk-hash/v2',
        }, {
          chunk_id: 'chunk-unitless',
          material_id: 'material-unitless',
          source: 'Unitless paper.pdf',
          text: 'Unitless full text.',
          quote: 'Unitless exact quote.',
          bbox: [0.1, 0.2, 0.4, 0.1],
        }],
      });
      options.onEvent?.({
        event: 'done',
        response: 'Evidence integrity answer.',
        session_id: 'chat-session-evidence-integrity',
      });
    });

    renderDialog(['/dialog?project_id=project-a']);
    fireEvent.change(await screen.findByLabelText('对话输入'), {
      target: { value: 'Show exact evidence.' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      const completedWrite = setConversation.mock.calls.find((call) => (
        call[2]?.sessionId === 'chat-session-evidence-integrity'
        && call[1]?.some((message: ChatMessageData) => message.status === 'done')
      ));
      const assistant = completedWrite?.[1]?.find((message: ChatMessageData) => message.role === 'assistant');
      expect(assistant?.evidence?.[0]).toMatchObject({
        text: 'Full points chunk text.',
        quote: 'Exact points sentence.',
        anchor_kind: 'text',
        bbox: [72, 144, 180, 36],
        bbox_unit: 'pdf_points',
        content_hash: 'a'.repeat(64),
        locator_hash: 'b'.repeat(64),
        chunk_hash: 'c'.repeat(64),
        embedding_input_hash: 'd'.repeat(64),
        hash_version: 'scholar-ai-chunk-hash/v2',
      });
      expect(assistant?.evidence?.[1]).toMatchObject({
        text: 'Unitless full text.',
        quote: 'Unitless exact quote.',
        bbox: null,
        bbox_unit: null,
      });
    });
  });

  it('keeps concurrent project responses inside the scope that started each request', async () => {
    const projectADeferred = createDeferred<void>();
    const projectBDeferred = createDeferred<void>();
    const streamOptions = new Map<
      string,
      Parameters<typeof streamIntelligentChatMessage>[1]
    >();
    mockedStreamIntelligentChatMessage.mockImplementation(async (request, options) => {
      const requestProjectId = request.project_id ?? '';
      streamOptions.set(requestProjectId, options);
      return requestProjectId === 'project-a'
        ? projectADeferred.promise
        : projectBDeferred.promise;
    });

    let activeProjectId = 'project-a';
    const writingContext = mockedUseWriting();
    mockedUseWriting.mockImplementation(() => ({
      ...writingContext,
      activeProjectId,
      setActiveProjectId: (projectId: string) => {
        activeProjectId = projectId;
      },
    }));
    const projectBMessages: ChatMessageData[] = [{
      id: 'project-b-existing',
      role: 'assistant',
      content: '项目 B 已有消息',
      timestamp: '2026-07-15T00:00:00.000Z',
      status: 'done',
    }];
    const smartReadContext = mockedUseSmartRead();
    mockedUseSmartRead.mockReturnValue({
      ...smartReadContext,
      getConversation: (scope: string) => ({
        messages: scope === smartReadDialogScope('project-b') ? projectBMessages : [],
        updatedAt: 0,
        pending: false,
      }),
    });

    const rendered = renderDialog(['/dialog']);
    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '项目 A 的问题' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(streamOptions.has('project-a')).toBe(true));

    activeProjectId = 'project-b';
    rendered.rerender(
      <MemoryRouter initialEntries={['/dialog']}>
        <PdfTabsProvider>
          <Dialog />
        </PdfTabsProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByLabelText('对话输入')).not.toBeDisabled());
    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '项目 B 的问题' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(streamOptions.has('project-b')).toBe(true));

    const lateWriteStart = setConversation.mock.calls.length;
    await act(async () => {
      streamOptions.get('project-a')?.onEvent({ event: 'text_delta', delta: '项目 A 的回答' });
      streamOptions.get('project-a')?.onEvent({
        event: 'done',
        response: '项目 A 的回答',
        session_id: 'session-project-a-late',
      });
      projectADeferred.resolve();
      await projectADeferred.promise;
    });
    await act(async () => {
      streamOptions.get('project-b')?.onEvent({ event: 'text_delta', delta: '项目 B 的回答' });
      streamOptions.get('project-b')?.onEvent({
        event: 'done',
        response: '项目 B 的回答',
        session_id: 'session-project-b-current',
      });
      projectBDeferred.resolve();
      await projectBDeferred.promise;
    });

    const lateWrites = setConversation.mock.calls.slice(lateWriteStart);
    const projectAWrites = lateWrites.filter(([scope]) => scope === smartReadDialogScope('project-a'));
    const projectBWrites = lateWrites.filter(([scope]) => scope === smartReadDialogScope('project-b'));
    expect(projectAWrites.length).toBeGreaterThan(0);
    expect(projectBWrites.length).toBeGreaterThan(0);
    projectAWrites.forEach(([, messages]) => {
      expect(messages).toEqual(expect.arrayContaining([
        expect.objectContaining({ role: 'user', content: '项目 A 的问题' }),
        expect.objectContaining({ role: 'assistant', content: '项目 A 的回答' }),
      ]));
      expect(messages).not.toEqual(expect.arrayContaining([
        expect.objectContaining({ content: '项目 B 已有消息' }),
        expect.objectContaining({ content: '项目 B 的问题' }),
      ]));
    });
    projectBWrites.forEach(([, messages]) => {
      expect(messages).toEqual(expect.arrayContaining([
        expect.objectContaining({ content: '项目 B 已有消息' }),
        expect.objectContaining({ role: 'user', content: '项目 B 的问题' }),
        expect.objectContaining({ role: 'assistant', content: '项目 B 的回答' }),
      ]));
      expect(messages).not.toEqual(expect.arrayContaining([
        expect.objectContaining({ content: '项目 A 的问题' }),
        expect.objectContaining({ content: '项目 A 的回答' }),
      ]));
    });
    await waitFor(() => expect(screen.getByLabelText('对话输入')).not.toBeDisabled());
  });

  it('persists final done-event visual refs instead of stale metadata refs', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent?.({
        event: 'metadata',
        session_id: 'chat-session-final-visuals',
        context_chunks_used: 1,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        visual_evidence_refs: [
          {
            chunk_id: 'han-fig-6',
            material_id: 'mat-han',
            source: 'Han thesis',
            text: 'Fig. 6. An unrelated thesis figure.',
            quote: 'Fig. 6. An unrelated thesis figure.',
            figure_candidate: 'Fig. 6',
            figure_candidate_detail: { caption: 'An unrelated thesis figure.' },
            image_paths: ['figure_assets/extracted/han/fig-6.png'],
          },
        ],
      });
      options.onEvent?.({
        event: 'text_delta',
        delta: 'Cui 2022 的 Fig. 6 展示焊接接头宏观形貌。',
      });
      options.onEvent?.({
        event: 'done',
        response: 'Cui 2022 的 Fig. 6 展示焊接接头宏观形貌。',
        session_id: 'chat-session-final-visuals',
        tokens_used: { prompt: 3, completion: 4, total: 7 },
        visual_evidence_refs: [
          {
            chunk_id: 'cui-fig-6',
            material_id: 'mat-cui',
            source: 'Cui 2022',
            text: 'Fig. 6. Macrostructure of the welded joints.',
            quote: 'Fig. 6. Macrostructure of the welded joints.',
            page: '6',
            figure_candidate: 'Fig. 6',
            figure_candidate_detail: { caption: 'Macrostructure of the welded joints.' },
            image_paths: ['figure_assets/extracted/cui/p0006_img001.png'],
          },
        ],
      });
    });

    renderDialog(['/dialog?project_id=project-a']);

    fireEvent.change(await screen.findByLabelText('对话输入'), {
      target: { value: '解释 Cui 2022 的 Fig. 6' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({
            role: 'assistant',
            status: 'done',
            relatedFigures: [
              expect.objectContaining({
                chunk_id: 'cui-fig-6',
                label: 'Fig. 6',
                material_id: 'mat-cui',
                page: 6,
                asset_path: 'figure_assets/extracted/cui/p0006_img001.png',
              }),
            ],
          }),
        ]),
        { sessionId: 'chat-session-final-visuals' },
      );
    });
    expect(listFigureTableCandidatesMock).not.toHaveBeenCalled();
  });

  it('preserves bbox metadata from fallback figure candidates', async () => {
    listFigureTableCandidatesMock.mockResolvedValueOnce([
      {
        id: 'candidate-weld-appearance',
        kind: 'figure',
        label: 'Fig. 3',
        caption: 'Weld surface appearance.',
        material_id: 'mat-weld',
        material_title: 'Weld paper',
        page: 6,
        chunk_id: 'chunk-fig-3',
        chunk_index: 3,
        bbox: [0.12, 0.24, 0.48, 0.31],
        bbox_unit: 'normalized_ratio',
        asset_path: 'figures/mat-weld/fig-3.png',
        source: 'pdf_embedded_image',
      },
    ]);
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent?.({
        event: 'metadata',
        session_id: 'chat-session-fallback-figure',
        context_chunks_used: 0,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
      });
      options.onEvent?.({
        event: 'done',
        response: '可查看 Fig. 3 的焊缝外观。',
        session_id: 'chat-session-fallback-figure',
      });
    });

    renderDialog(['/dialog?project_id=project-a']);

    fireEvent.change(await screen.findByLabelText('对话输入'), {
      target: { value: '展示焊缝外观图片' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({
            role: 'assistant',
            relatedFigures: [
              expect.objectContaining({
                chunk_id: 'chunk-fig-3',
                material_id: 'mat-weld',
                page: 6,
                bbox: [0.12, 0.24, 0.48, 0.31],
                bbox_unit: 'normalized_ratio',
              }),
            ],
          }),
        ]),
        { sessionId: 'chat-session-fallback-figure' },
      );
    });
  });

  it('does not invent a quote from evidence body text during history restore', async () => {
    mockedResumeChatSession.mockResolvedValue({
      session_id: 'session-no-exact-quote',
      project_id: 'project-a',
      messages: [
        {
          id: 'assistant-no-exact-quote',
          role: 'assistant',
          content: '该证据只能定位到上下文块。',
          timestamp: '2026-07-22T12:00:00.000Z',
          evidence_refs: [
            {
              chunk_id: 'chunk-context-only',
              material_id: 'mat-context-only',
              source: 'Context-only paper',
              text: 'This entire chunk is context, not an answer-attributed exact quote.',
              quote: '',
              page: 5,
            },
          ],
          tokens_used: { prompt: 1, completion: 1, total: 2 },
        },
      ],
    });

    renderDialog([
      '/dialog?project_id=project-a&conversation_id=session-no-exact-quote',
    ]);

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({
            id: 'assistant-no-exact-quote',
            evidence: [
              expect.objectContaining({
                chunk_id: 'chunk-context-only',
                quote: '',
              }),
            ],
          }),
        ]),
        { sessionId: 'session-no-exact-quote' },
      );
    });
  });

  it('keeps the desktop agent handoff entry visible before a receipt is available', async () => {
    renderDialog(['/dialog?project_id=project-a']);

    const handoffButton = await screen.findByRole('button', { name: '给智能体' });
    expect(handoffButton).not.toBeDisabled();

    fireEvent.click(handoffButton);

    const createHandoffItem = await screen.findByRole('menuitem', { name: '接手当前回答' });
    expect(createHandoffItem).toBeDisabled();
    expect(createHandoffItem).toHaveAttribute('title', '当前回答保存后可创建接手任务');
  });

  it('ignores a persisted external-agent preference and uses the configured answer model', async () => {
    window.localStorage.setItem('dialog-answer-origin-v1', 'external_agent');
    const providerResponse = [
      '问题：请直接回答',
      '直接回答，不复述问题。',
      '',
      '## 证据摘要：',
      '- 不应显示的内部证据整理。',
    ].join('\n');
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent?.({
        event: 'metadata',
        session_id: 'chat-session-internal',
        context_chunks_used: 1,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
        answer_origin: 'internal_smartread',
        answer_model_origin: 'scholar_ai_configured_chat',
        retrieval_provider: 'scholar_ai',
      });
      options.onEvent?.({
        event: 'text_delta',
        delta: providerResponse,
      });
      options.onEvent?.({
        event: 'done',
        response: providerResponse,
        session_id: 'chat-session-internal',
        tokens_used: { prompt: 10, completion: 6, total: 16 },
        answer_origin: 'internal_smartread',
        answer_model_origin: 'scholar_ai_configured_chat',
      });
    });

    renderDialog(['/dialog?project_id=project-a']);

    fireEvent.change(screen.getByLabelText('对话输入'), {
      target: { value: '请直接回答' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          query: '请直接回答',
          project_id: 'project-a',
          answer_origin: 'internal_smartread',
        }),
        expect.any(Object),
      );
    });
    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({
            role: 'assistant',
            content: '直接回答，不复述问题。',
          }),
        ]),
        expect.objectContaining({ sessionId: 'chat-session-internal' }),
      );
    });
    expect(screen.queryByText(/问题：请直接回答/)).not.toBeInTheDocument();
    expect(screen.queryByText(/证据摘要/)).not.toBeInTheDocument();
    expect(screen.queryByText(/不应显示的内部证据整理/)).not.toBeInTheDocument();
  });

  it('preserves ordinary evidence-summary wording while filtering restored internal answer artifacts', async () => {
    conversationMessages = [
      {
        id: 'u-restored-internal',
        role: 'user',
        content: '请比较两种归纳方式。',
        timestamp: '2026-07-15T02:50:00.000Z',
        status: 'done',
      },
      {
        id: 'a-restored-internal',
        role: 'assistant',
        content: [
          '用户问题：请比较两种归纳方式。',
          '正文中的“证据摘要”只是普通术语，应继续显示。',
          '',
          '### 证据摘要：',
          '- 不应显示的内部证据整理。',
        ].join('\n'),
        timestamp: '2026-07-15T02:51:00.000Z',
        status: 'done',
        metadata: {
          diagnostics: {
            answerOrigin: 'internal_smartread',
          },
        },
      },
    ];

    renderDialog(['/dialog?project_id=project-a']);

    expect(await screen.findByText('正文中的“证据摘要”只是普通术语，应继续显示。')).toBeInTheDocument();
    expect(screen.queryByText(/用户问题：请比较两种归纳方式/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^证据摘要[：:]$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/不应显示的内部证据整理/)).not.toBeInTheDocument();
  });

  it('hides repeated questions and evidence dumps from persisted legacy handoffs', async () => {
    conversationMessages = [
      {
        id: 'u-legacy-handoff',
        role: 'user',
        content: '请分析选中的区域。',
        timestamp: '2026-07-09T14:00:00.000Z',
        status: 'done',
      },
      {
        id: 'a-legacy-handoff',
        role: 'assistant',
        content: [
          '已切换为外部智能体回答模式。',
          '文献助手未调用内部聊天模型；已完成本地检索，并把证据交给 Codex/Claude 等外部智能体生成最终回答。',
          '问题：请分析选中的区域。 检索结果：12 个上下文片段，12 条证据引用。',
          '证据摘要：',
          '1. [chunk-legacy-1] 不应显示的证据正文。',
          '外部智能体应优先使用 evidence_refs / context_metadata.chunks 中的引用和 chunk_id 组织最终回答。',
        ].join('\n'),
        timestamp: '2026-07-09T14:01:00.000Z',
        status: 'done',
        metadata: {
          diagnostics: {
            answerOrigin: 'external_agent',
          },
        },
      },
    ];

    renderDialog(['/dialog?project_id=project-a']);

    expect(await screen.findByText('证据已准备，等待智能体回答。')).toBeInTheDocument();
    expect(screen.queryByText(/已切换为外部智能体回答模式/)).not.toBeInTheDocument();
    expect(screen.queryByText(/问题：请分析选中的区域/)).not.toBeInTheDocument();
    expect(screen.queryByText(/证据摘要/)).not.toBeInTheDocument();
    expect(screen.queryByText(/不应显示的证据正文/)).not.toBeInTheDocument();
  });

  it('shows an agent handoff action on the latest desktop answer and creates the shared request', async () => {
    conversationMessages = [
      {
        id: 'u1',
        role: 'user',
        content: '这条回答能交给智能体接手吗？',
        timestamp: '2026-07-09T14:00:00.000Z',
        status: 'done',
      },
      {
        id: 'a1',
        role: 'assistant',
        content: '可以，证据已经保存。',
        timestamp: '2026-07-09T14:01:00.000Z',
        status: 'done',
      },
    ];
    const receiptRead = {
      conversation_id: 'sidebar-session-desktop',
      project_id: 'project-a',
      answer: '可以，证据已经保存。',
      receipt: {
        receipt_schema_version: 'scholar-ai-answer-receipt/v1',
        project_id: 'project-a',
        question: '这条回答能交给智能体接手吗？',
        answer: '可以，证据已经保存。',
        top_evidence_refs: [],
      },
      staleness: {
        status: 'saved',
        checked: [],
        warnings: [],
        mismatches: [],
      },
    } as Awaited<ReturnType<typeof readAgentSidebarReceipt>>;
    mockedUseSmartRead.mockReturnValue({
      getConversation: () => ({
        messages: conversationMessages,
        updatedAt: 0,
        pending: false,
        sessionId: 'sidebar-session-desktop',
      }),
      sendMessage: vi.fn(),
      stopMessage: vi.fn(),
      setConversation,
      appendMessages: vi.fn(),
      clearConversation,
    });
    mockedReadAgentSidebarReceipt.mockResolvedValueOnce(receiptRead);
    mockedCreateAgentSidebarAnswerRequest.mockResolvedValueOnce({
      request_id: 'agentreq_desktop_visible',
      job: {
        job_id: 'job_desktop_visible',
        status: 'started',
        metadata: {},
      },
      poll: { job: '/runtime/job/job_desktop_visible' },
      envelope: {
        intent: 'sidebar_answer',
        project_id: 'project-a',
        user_text: '这条回答能交给智能体接手吗？',
        resource_refs: [],
      },
    });

    renderDialog(['/dialog?project_id=project-a']);

    const handoffButtons = await screen.findAllByRole('button', { name: '给智能体' });
    expect(handoffButtons.length).toBeGreaterThanOrEqual(2);

    fireEvent.click(handoffButtons[handoffButtons.length - 1]);
    fireEvent.click(await screen.findByRole('menuitem', { name: '接手当前回答' }));

    await waitFor(() => {
      expect(mockedReadAgentSidebarReceipt).toHaveBeenCalledWith('sidebar-session-desktop');
      expect(mockedCreateAgentSidebarAnswerRequest).toHaveBeenCalledWith(
        receiptRead,
        expect.objectContaining({
          projectId: 'project-a',
          agentHost: 'agent',
          source: 'desktop',
          route: '/dialog',
          generatedIn: 'desktop_dialog',
        }),
      );
    });
    expect(await screen.findByText('已创建智能体接手任务。')).toBeInTheDocument();
  });

  it('edits a user message by truncating later turns and restoring the text to the composer', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'edited answer' });
      options.onEvent({ event: 'done', response: 'edited answer', session_id: 'session-edited' });
    });
    conversationMessages = [
      {
        id: 'u1',
        role: 'user',
        turnId: 'turn-edit-1',
        content: '原问题',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
        researchSelections: [{
          schema_version: 'scholar-ai-research-selection/v1',
          selection_id: 'selection-edit-text',
          turn_id: 'turn-edit-1',
          group_id: 'group-edit-1',
          order: 0,
          material_id: 'mat-paper',
          kind: 'text',
          page: 4,
          text: '选中的原文',
          bbox: [0.1, 0.2, 0.6, 0.08],
          bbox_unit: 'normalized_ratio',
        }, {
          schema_version: 'scholar-ai-research-selection/v1',
          selection_id: 'selection-edit-formula',
          turn_id: 'turn-edit-1',
          group_id: 'group-edit-1',
          order: 1,
          material_id: 'mat-paper',
          kind: 'formula',
          page: 5,
          text: 'E = mc^2',
          bbox: [0.2, 0.3, 0.5, 0.1],
          bbox_unit: 'normalized_ratio',
          candidate_id: 'formula-edit-1',
        }],
      },
      {
        id: 'a1',
        role: 'assistant',
        content: '原回答',
        timestamp: '2026-05-29T00:02:00.000Z',
        status: 'done',
      },
    ];

    renderDialog(['/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf']);

    fireEvent.click(await screen.findByRole('button', { name: '修改这条消息并从这里继续' }));

    await waitFor(() => expect(screen.getByLabelText('对话输入')).toHaveValue('原问题'));
    const selectionGroup = await screen.findByRole('group', { name: '当前 PDF 选区' });
    expect(selectionGroup).toHaveTextContent('选中的原文');
    expect(selectionGroup).toHaveTextContent('公式');
    expect(selectionGroup).toHaveTextContent('第 5 页');
    expect(screen.getByTestId('selected-visual-regions'))
      .toHaveTextContent('formula:5:formula-edit-1');
    expect(setConversation).toHaveBeenCalledWith(
      smartReadDialogScope('project-a'),
      [],
      { sessionId: null },
    );

    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockedStreamIntelligentChatMessage).toHaveBeenCalled());
    const editedRequest = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0];
    expect(editedRequest?.images).toBeUndefined();
    expect(editedRequest?.current_pdf_context?.selections).toEqual([
      expect.objectContaining({ kind: 'text', text: '选中的原文' }),
      expect.objectContaining({
        kind: 'formula',
        text: 'E = mc^2',
        candidate_id: 'formula-edit-1',
      }),
    ]);
    expect(editedRequest?.current_pdf_context?.selections?.[1]).not.toHaveProperty('image_index');
    expect(editedRequest?.research_selections?.map((selection) => selection.order)).toEqual([0, 1]);
  });

  it('replays a durable historical figure locator without persisted pixels', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'historical figure answer' });
      options.onEvent({
        event: 'done',
        response: 'historical figure answer',
        session_id: 'session-edited-figure',
      });
    });
    conversationMessages = [
      {
        id: 'u-edit-figure',
        role: 'user',
        turnId: 'turn-edit-figure',
        content: '解释历史图表',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
        researchSelections: [{
          schema_version: 'scholar-ai-research-selection/v1',
          selection_id: 'selection-edit-figure',
          turn_id: 'turn-edit-figure',
          group_id: 'group-edit-figure',
          order: 0,
          material_id: 'mat-paper',
          kind: 'figure',
          page: 6,
          bbox: [0.12, 0.24, 0.48, 0.32],
          bbox_unit: 'normalized_ratio',
          chunk_id: 'chunk-edit-figure',
          candidate_id: 'figure-edit-1',
        }],
      },
      {
        id: 'a-edit-figure',
        role: 'assistant',
        turnId: 'turn-edit-figure',
        content: '原图表回答',
        timestamp: '2026-05-29T00:02:00.000Z',
        status: 'done',
      },
    ];

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    fireEvent.click(await screen.findByRole('button', { name: '修改这条消息并从这里继续' }));

    await waitFor(() => expect(screen.getByLabelText('对话输入')).toHaveValue('解释历史图表'));
    expect(screen.getByRole('group', { name: '当前 PDF 选区' })).toHaveTextContent('第 6 页');
    expect(screen.getByTestId('composer-attachments')).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledTimes(1));
    const replayRequest = mockedStreamIntelligentChatMessage.mock.calls[0]?.[0];
    expect(replayRequest?.images).toBeUndefined();
    expect(replayRequest?.research_selections).toEqual([
      expect.objectContaining({
        material_id: 'mat-paper',
        kind: 'figure',
        page: 6,
        bbox: [0.12, 0.24, 0.48, 0.32],
        bbox_unit: 'normalized_ratio',
        chunk_id: 'chunk-edit-figure',
        candidate_id: 'figure-edit-1',
      }),
    ]);
    expect(replayRequest?.current_pdf_context?.selections).toEqual([
      expect.objectContaining({
        kind: 'figure',
        page: 6,
        bbox: [0.12, 0.24, 0.48, 0.32],
        bbox_unit: 'normalized_ratio',
      }),
    ]);
    expect(JSON.stringify(replayRequest)).not.toContain('image_index');
    expect(JSON.stringify(replayRequest)).not.toContain('data_b64');
  });

  it('blocks a transient visual selection after its hidden pixels are lost', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    expect(screen.getByRole('group', { name: '当前 PDF 选区' })).toHaveTextContent('选中的图');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');

    fireEvent.click(screen.getByRole('button', { name: '模拟丢弃全部图片' }));
    expect(screen.getByTestId('composer-attachments')).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(mockedStreamIntelligentChatMessage).not.toHaveBeenCalled();
    expect(await screen.findByText('恢复的图表、公式或区域选区需要在 PDF 中重新选择后才能再次提交。'))
      .toBeInTheDocument();
  });

  it('forks from a visible message and drops later turns from the local branch', async () => {
    conversationMessages = [
      {
        id: 'u1',
        role: 'user',
        turnId: 'turn-fork-1',
        content: '第一问',
        timestamp: '2026-05-29T00:01:00.000Z',
        status: 'done',
        researchSelections: [{
          schema_version: 'scholar-ai-research-selection/v1',
          selection_id: 'selection-fork-1',
          turn_id: 'turn-fork-1',
          group_id: 'group-fork-1',
          order: 0,
          material_id: 'mat-paper',
          kind: 'text',
          page: 2,
          text: '分叉原文',
        }],
      },
      {
        id: 'a1',
        role: 'assistant',
        content: '第一答',
        timestamp: '2026-05-29T00:02:00.000Z',
        status: 'done',
      },
      {
        id: 'u2',
        role: 'user',
        content: '第二问',
        timestamp: '2026-05-29T00:03:00.000Z',
        status: 'done',
      },
    ];

    renderDialog();

    fireEvent.click((await screen.findAllByRole('button', { name: '从这里分叉' }))[1]);

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        [
          expect.objectContaining({ id: 'u1', content: '第一问' }),
          expect.objectContaining({ id: 'a1', content: '第一答' }),
        ],
        { sessionId: null },
      );
    });
    const forkedMessages = setConversation.mock.calls.at(-1)?.[1] as ChatMessageData[] | undefined;
    expect(forkedMessages?.[0]?.researchSelections?.[0]).toMatchObject({
      selection_id: 'selection-fork-1',
      order: 0,
      text: '分叉原文',
    });
  });

  it('renders saved pinned-paper notes in the right research context rail', async () => {
    mockedGetAnnotations.mockResolvedValue({
      material_id: 'mat-paper',
      highlights: [],
      notes: [
        {
          note_id: 'note-1',
          page: 7,
          anchor_text: '关键引文片段',
          body: '这条笔记应该出现在统一研究上下文里。',
          tags: ['机制', '证据'],
          enabled_scopes: [],
          usage_updated_at: null,
          content_hash: 'a'.repeat(64),
          created_at: '2026-05-29T00:04:00.000Z',
          updated_at: '2026-05-29T00:05:00.000Z',
        },
      ],
      last_page: null,
    });

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    fireEvent.click(await screen.findByRole('button', { name: /笔记/ }));

    expect(await screen.findByText('这条笔记应该出现在统一研究上下文里。')).toBeInTheDocument();
    expect(screen.getByText('关键引文片段')).toBeInTheDocument();
    expect(screen.getByText('机制')).toBeInTheDocument();
    expect(screen.getByText('证据')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开第 7 页' })).toBeInTheDocument();
    expect(mockedGetAnnotations).toHaveBeenCalledWith('mat-paper');

    fireEvent.click(screen.getByRole('button', { name: '打开第 7 页' }));
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' })).getByTestId('embedded-pdf-reader'))
        .toHaveAttribute('data-page', '7');
    });
  });

  it('lets a same-material reader deep-link override the current reader page', async () => {
    mockedGetAnnotations.mockResolvedValue({
      material_id: 'mat-paper',
      highlights: [],
      notes: [
        {
          note_id: 'note-page-4',
          page: 4,
          anchor_text: '同一篇文献里的另一条证据',
          body: '点击后应该跳到第 4 页，而不是停留在当前阅读页。',
          tags: [],
          enabled_scopes: [],
          usage_updated_at: null,
          content_hash: 'b'.repeat(64),
          created_at: '2026-05-29T00:04:00.000Z',
          updated_at: '2026-05-29T00:05:00.000Z',
        },
      ],
      last_page: null,
    });

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf&page=3',
    ]);

    const readerRegion = screen.getByRole('region', { name: '中间栏本文献阅读器' });
    await waitFor(() => {
      expect(within(readerRegion).getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '3');
    });

    fireEvent.click(within(readerRegion).getByRole('button', { name: '模拟翻到第 7 页' }));
    await waitFor(() => {
      expect(within(readerRegion).getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '7');
    });

    fireEvent.click(await screen.findByRole('button', { name: /笔记/ }));
    fireEvent.click(await screen.findByRole('button', { name: '打开第 4 页' }));

    await waitFor(() => {
      expect(within(readerRegion).getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '4');
    });
  });

  it('does not reuse a URL bbox after the embedded reader moves to another page', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf&page=3&bbox=0.1%2C0.2%2C0.4%2C0.08',
    ]);

    const readerRegion = screen.getByRole('region', { name: '中间栏本文献阅读器' });
    const initialReader = await within(readerRegion).findByTestId('embedded-pdf-reader');
    expect(initialReader).toHaveAttribute('data-page', '3');
    expect(initialReader).toHaveAttribute('data-bbox', '0.1,0.2,0.4,0.08');

    fireEvent.click(within(readerRegion).getByRole('button', { name: '模拟翻到第 7 页' }));

    await waitFor(() => {
      const reader = within(readerRegion).getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '7');
      expect(reader).toHaveAttribute('data-bbox', '');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
  });

  it('does not reuse a URL quote after the embedded reader moves to another page', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf&page=3&quote=The%20exact%20sentence.',
    ]);

    const readerRegion = screen.getByRole('region', { name: '中间栏本文献阅读器' });
    const initialReader = await within(readerRegion).findByTestId('embedded-pdf-reader');
    expect(initialReader).toHaveAttribute('data-page', '3');
    expect(initialReader).toHaveAttribute('data-quote', 'The exact sentence.');

    fireEvent.click(within(readerRegion).getByRole('button', { name: '模拟翻到第 7 页' }));

    await waitFor(() => {
      const reader = within(readerRegion).getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '7');
      expect(reader).toHaveAttribute('data-quote', '');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
  });

  it('discards a URL bbox that has no valid source page instead of pairing it with a persisted page', async () => {
    window.sessionStorage.setItem('pdf-tabs:v1', JSON.stringify({
      tabs: [{ materialId: 'mat-paper', title: 'paper.pdf' }],
      activeId: 'mat-paper',
      views: {
        'mat-paper': { page: 9, scale: 1.2, scrollTop: 0 },
      },
    }));
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf&bbox=0.2%2C0.3%2C0.3%2C0.1',
    ]);

    const reader = await within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .findByTestId('embedded-pdf-reader');
    expect(reader).toHaveAttribute('data-page', '9');
    expect(reader).toHaveAttribute('data-bbox', '');
    expect(reader).toHaveAttribute('data-highlight-rects', '[]');
  });

  it('renders a pinned PDF in the center reader pane while keeping SmartRead chat on the right', async () => {
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-paper',
        project_id: 'project-a',
        title: 'paper.pdf',
        title_en: '',
        summary: 'PDF metadata remains available in the research rail.',
        summary_en: '',
        type: 'reference',
        focus_points: ['method'],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const mainPane = screen.getByRole('region', { name: '中间栏本文献阅读器' });
    await waitFor(() => {
      expect(within(mainPane).getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-paper');
    });
    expect(screen.getAllByTestId('embedded-pdf-reader')).toHaveLength(1);
    expect(screen.getByRole('region', { name: '中间栏本文献阅读器' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '智能研读对话' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '在中间栏阅读本文献' })).not.toBeInTheDocument();
  });

  it('accumulates ordered figure and table selections with paired image indexes', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'table answer' });
      options.onEvent({ event: 'done', response: 'table answer', session_id: 'session-table' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择表' }));

    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('table-two.png');
    const selectionGroup = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selectionGroup).toHaveTextContent('选中的图');
    expect(selectionGroup).toHaveTextContent('第 3 页');
    expect(selectionGroup).toHaveTextContent('选中的表');
    expect(selectionGroup).toHaveTextContent('第 4 页');
    expect(screen.getByLabelText('对话输入')).toHaveValue('请结合选中的内容进行分析。');
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          images: [
            expect.objectContaining({ name: 'manual-note.png', data_b64: 'bWFudWFsLWltYWdl' }),
            expect.objectContaining({ name: 'figure-one.png', data_b64: 'ZmlndXJlLW9uZQ==' }),
            expect.objectContaining({ name: 'table-two.png', data_b64: 'dGFibGUtdHdv' }),
          ],
          current_pdf_context: expect.objectContaining({
            selection: expect.objectContaining({ kind: 'figure', page: 3, image_index: 1 }),
            selections: [
              expect.objectContaining({ kind: 'figure', page: 3, image_index: 1 }),
              expect.objectContaining({ kind: 'table', page: 4, image_index: 2 }),
            ],
          }),
          turn_id: expect.stringMatching(/^dialog-turn-/),
          research_selections: [
            expect.objectContaining({
              schema_version: 'scholar-ai-research-selection/v1',
              group_id: expect.stringMatching(/^dialog-turn-/),
              order: 0,
              material_id: 'mat-paper',
              kind: 'figure',
              page: 3,
            }),
            expect.objectContaining({
              order: 1,
              material_id: 'mat-paper',
              kind: 'table',
              page: 4,
            }),
          ],
        }),
        expect.any(Object),
      );
    });
    const persistedUserMessage = setConversation.mock.calls
      .flatMap((call) => call[1] as ChatMessageData[])
      .find((message) => message.role === 'user' && message.content === '请结合选中的内容进行分析。');
    expect(persistedUserMessage?.researchSelections?.map((selection) => selection.kind)).toEqual([
      'figure',
      'table',
    ]);
    expect(JSON.stringify(persistedUserMessage)).not.toContain('image_index');
    expect(JSON.stringify(persistedUserMessage)).not.toContain('data_b64');
  });

  it('keeps visual-processing progress out of assistant message content', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({
        event: 'metadata',
        session_id: 'session-figure-progress',
        context_chunks_used: 2,
        tier_used: 'balanced',
        context_metadata: { chunks: [], truncated: false },
        evidence_refs: [],
      });
      await pending.promise;
      options.onEvent({ event: 'text_delta', delta: 'figure answer' });
      options.onEvent({ event: 'done', response: 'figure answer', session_id: 'session-figure-progress' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    try {
      await waitFor(() => {
        expect(setConversation).toHaveBeenCalledWith(
          smartReadDialogScope('project-a'),
          expect.arrayContaining([
            expect.objectContaining({
              role: 'assistant',
              content: '',
              status: 'streaming',
            }),
          ]),
        );
      });
      const pendingMessages = setConversation.mock.calls.flatMap(
        (call) => call[1] as ChatMessageData[],
      );
      expect(pendingMessages.some((message) => /正在解析|正在检索|已找到.*参考片段/.test(message.content))).toBe(false);
    } finally {
      await act(async () => {
        pending.resolve();
        await pending.promise;
      });
      await waitFor(() => {
        expect(screen.getByLabelText('对话输入')).not.toBeDisabled();
      });
    }

    await waitFor(() => {
      expect(setConversation).toHaveBeenCalledWith(
        smartReadDialogScope('project-a'),
        expect.arrayContaining([
          expect.objectContaining({ role: 'assistant', content: 'figure answer', status: 'done' }),
        ]),
        { sessionId: 'session-figure-progress' },
      );
    });
  });

  it('stores done-event visual observation references without promoting candidate output', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (request, options) => {
      const turnId = request.turn_id ?? 'missing-turn';
      options.onEvent({ event: 'text_delta', delta: 'visual candidate answer' });
      options.onEvent({
        event: 'done',
        response: 'visual candidate answer',
        session_id: 'session-visual-candidate',
        visual_observation_refs: [dialogVisualObservationReference(turnId)],
      });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '解释视觉内容' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(mockedStreamIntelligentChatMessage).toHaveBeenCalled());
    const requestTurnId = mockedStreamIntelligentChatMessage.mock.calls[0]?.[0].turn_id ?? 'missing-turn';
    const persistedAssistant = setConversation.mock.calls
      .flatMap((call) => call[1] as ChatMessageData[])
      .filter((message) => message.role === 'assistant' && message.content === 'visual candidate answer')
      .at(-1);
    expect(persistedAssistant?.visualObservationRefs).toEqual([
      dialogVisualObservationReference(requestTurnId),
    ]);
    expect(persistedAssistant?.evidence).toBeUndefined();
    expect(persistedAssistant?.relatedFigures).toBeUndefined();
    expect(JSON.stringify(persistedAssistant)).not.toContain('output_text');
  });

  it('retains a visual selection when native text is added to the mixed selection', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'text answer' });
      options.onEvent({ event: 'done', response: 'text answer', session_id: 'session-text' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));

    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');
    const selectionGroup = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selectionGroup).toHaveTextContent('选中的图');
    expect(selectionGroup).toHaveTextContent('选中的文本');
    expect(selectionGroup).toHaveTextContent('Selected paragraph with citation [7].');
    expect(screen.getByLabelText('对话输入')).toHaveValue('请结合选中的内容进行分析。');
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          images: [
            expect.objectContaining({ name: 'manual-note.png' }),
            expect.objectContaining({ name: 'figure-one.png' }),
          ],
          current_pdf_context: expect.objectContaining({
            selection: expect.objectContaining({ kind: 'figure', image_index: 1 }),
            selections: [
              expect.objectContaining({ kind: 'figure', image_index: 1 }),
              expect.objectContaining({
                kind: 'text',
                text: 'Selected paragraph with citation [7].',
              }),
            ],
          }),
        }),
        expect.any(Object),
      );
    });
    const request = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0];
    expect(request?.current_pdf_context?.selections?.[1]).not.toHaveProperty('image_index');
  });

  it('loads formula candidates and appends an atomic formula to native text', async () => {
    listFormulaCandidatesMock.mockResolvedValue({
      project_id: 'project-a',
      material_id: 'mat-paper',
      candidates: [{
        candidate_id: 'chunk-equation-1',
        chunk_id: 'chunk-equation-1',
        page: 5,
        bbox: [0.15, 0.42, 0.55, 0.09],
        bbox_unit: 'normalized_ratio',
        text: 'E = mc^2',
      }],
    });
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'formula answer' });
      options.onEvent({ event: 'done', response: 'formula answer', session_id: 'session-formula' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    await waitFor(() => {
      expect(within(reader).getByTestId('formula-candidates')).toHaveTextContent('chunk-equation-1');
    });
    expect(listFormulaCandidatesMock).toHaveBeenCalledWith('project-a', 'mat-paper', 200);
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择公式' }));

    const selectionGroup = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selectionGroup).toHaveTextContent('选中的文本');
    expect(selectionGroup).toHaveTextContent('选中的公式');
    expect(selectionGroup).toHaveTextContent('第 5 页');
    expect(within(reader).getByTestId('selected-visual-regions'))
      .toHaveTextContent('formula:5:chunk-equation-1');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('formula-equation-1.png');
    expect(screen.getByLabelText('对话输入')).toHaveValue('请结合选中的内容进行分析。');

    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockedStreamIntelligentChatMessage).toHaveBeenCalled());
    const request = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0];
    expect(request?.images).toEqual([
      expect.objectContaining({ name: 'formula-equation-1.png' }),
    ]);
    expect(request?.current_pdf_context?.selections).toEqual([
      expect.objectContaining({
        kind: 'text',
        text: 'Selected paragraph with citation [7].',
      }),
      expect.objectContaining({
        kind: 'formula',
        page: 5,
        image_index: 0,
        candidate_id: 'chunk-equation-1',
        chunk_id: 'chunk-equation-1',
        text: 'E = mc^2',
      }),
    ]);
  });

  it('removes exactly one mixed selection and its paired hidden screenshot', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'plain answer' });
      options.onEvent({ event: 'done', response: 'plain answer', session_id: 'session-no-selection' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择表' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));
    fireEvent.click(within(screen.getByRole('group', { name: '当前 PDF 选区' })).getByRole('button', {
      name: '移除选区 2：选中的表，第 4 页',
    }));

    const selectionGroup = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selectionGroup).toHaveTextContent('选中的图');
    expect(selectionGroup).toHaveTextContent('选中的文本');
    expect(selectionGroup).not.toHaveTextContent('选中的表');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');
    expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('table-two.png');

    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '继续提问' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          images: [
            expect.objectContaining({ name: 'manual-note.png' }),
            expect.objectContaining({ name: 'figure-one.png' }),
          ],
          current_pdf_context: expect.objectContaining({
            selections: [
              expect.objectContaining({ kind: 'figure', image_index: 1 }),
              expect.objectContaining({ kind: 'text' }),
            ],
          }),
        }),
        expect.any(Object),
      );
    });
  });

  it('clears PDF selections and paired hidden pixels when starting an already-unsaved conversation', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    expect(screen.getByRole('group', { name: '当前 PDF 选区' })).toHaveTextContent('选中的图');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');

    fireEvent.click(screen.getByRole('button', { name: '新建对话' }));

    expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
  });

  it('clears only an automatic selection prompt when the final PDF selection is removed', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    expect(screen.getByLabelText('对话输入')).toHaveValue('请分析选中的图。');
    fireEvent.click(screen.getByRole('button', { name: '移除选中的图' }));
    expect(screen.getByLabelText('对话输入')).toHaveValue('');

    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.change(screen.getByLabelText('对话输入'), {
      target: { value: '比较这张图与论文结论是否一致' },
    });
    fireEvent.click(screen.getByRole('button', { name: '移除选中的图' }));

    expect(screen.getByLabelText('对话输入')).toHaveValue('比较这张图与论文结论是否一致');
  });

  it('drops hidden selection pixels but keeps manual images when switching to project scope', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'project answer' });
      options.onEvent({ event: 'done', response: 'project answer', session_id: 'session-project-scope' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');

    const conversationRegion = screen.getByRole('region', { name: '智能研读对话' });
    fireEvent.click(within(conversationRegion).getByRole('button', { name: '范围' }));
    fireEvent.click(within(conversationRegion).getByRole('menuitemradio', { name: '项目文献' }));

    await waitFor(() => {
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
    });

    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '继续问项目问题' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(mockedStreamIntelligentChatMessage).toHaveBeenCalled());
    const request = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0];
    expect(request?.images).toEqual([expect.objectContaining({ name: 'manual-note.png' })]);
    expect(request?.current_pdf_context).toBeUndefined();
  });

  it('drops hidden selection pixels when the last PDF tab closes and keeps manual images', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'text_delta', delta: 'project answer' });
      options.onEvent({ event: 'done', response: 'project answer', session_id: 'session-project-after-pdf' });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    expect(screen.getByRole('group', { name: '当前 PDF 选区' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '关闭 paper.pdf' }));

    await waitFor(() => {
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
    });

    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '继续问项目问题' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          images: [expect.objectContaining({ name: 'manual-note.png' })],
          material_id: undefined,
          current_pdf_context: undefined,
        }),
        expect.any(Object),
      );
    });
  });

  it('disables reader analysis selections while an answer is generating', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    expect(within(reader).getByRole('button', { name: '模拟选择文本' })).toBeDisabled();
    expect(within(reader).getByRole('button', { name: '模拟选择图' })).toBeDisabled();
    expect(within(reader).getByRole('button', { name: '模拟选择表' })).toBeDisabled();

    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));
    expect(screen.getByLabelText('对话输入')).toHaveValue('');
    expect(screen.getByTestId('composer-attachments')).toBeEmptyDOMElement();

    await act(async () => {
      pending.resolve();
      await pending.promise;
    });
    await waitFor(() => {
      expect(within(reader).getByRole('button', { name: '模拟选择文本' })).not.toBeDisabled();
    });
  });

  it('restores every valid mixed selection and paired visual attachment after a request failure', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (request, options) => {
      const turnId = request.turn_id ?? 'missing-turn';
      options.onEvent({
        event: 'done',
        response: 'partial visual answer',
        session_id: 'session-visual-failure',
        visual_observation_refs: [dialogVisualObservationReference(turnId)],
      });
      throw new Error('provider unavailable');
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择表' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByLabelText('对话输入')).toHaveValue('请结合选中的内容进行分析。');
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('table-two.png');
      const selectionGroup = screen.getByRole('group', { name: '当前 PDF 选区' });
      expect(selectionGroup).toHaveTextContent('选中的图');
      expect(selectionGroup).toHaveTextContent('选中的表');
      expect(selectionGroup).toHaveTextContent('选中的文本');
    });
    const request = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0];
    expect(request?.current_pdf_context?.selections).toEqual([
      expect.objectContaining({ kind: 'figure', image_index: 1 }),
      expect.objectContaining({ kind: 'table', image_index: 2 }),
      expect.objectContaining({ kind: 'text' }),
    ]);
    const failedAssistant = setConversation.mock.calls
      .flatMap((call) => call[1] as ChatMessageData[])
      .filter((message) => message.role === 'assistant' && message.status === 'error')
      .at(-1);
    expect(failedAssistant?.visualObservationRefs).toEqual([
      dialogVisualObservationReference(request?.turn_id ?? 'missing-turn'),
    ]);
  });

  it('restores the ordered mixed-selection draft after the user stops generation', async () => {
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      const turnId = _payload.turn_id ?? 'missing-turn';
      options.onEvent({
        event: 'done',
        response: 'partial visual answer',
        session_id: 'session-visual-stopped',
        visual_observation_refs: [dialogVisualObservationReference(turnId)],
      });
      await new Promise<void>((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'));
        }, { once: true });
      });
    });
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择文本' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    fireEvent.click(await screen.findByRole('button', { name: '停止生成' }));

    await waitFor(() => {
      expect(screen.getByLabelText('对话输入')).toHaveValue('请结合选中的内容进行分析。');
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('figure-one.png');
      const restoredSelections = screen.getByRole('group', { name: '当前 PDF 选区' });
      expect(restoredSelections).toHaveTextContent('选中的图');
      expect(restoredSelections).toHaveTextContent('选中的文本');
    });
    expect(setConversation).toHaveBeenCalledWith(
      smartReadDialogScope('project-a'),
      expect.arrayContaining([
        expect.objectContaining({ role: 'assistant', content: '已停止生成。', status: 'done' }),
      ]),
    );
    const stoppedAssistant = setConversation.mock.calls
      .flatMap((call) => call[1] as ChatMessageData[])
      .filter((message) => message.role === 'assistant' && message.content === '已停止生成。')
      .at(-1);
    const requestTurnId = mockedStreamIntelligentChatMessage.mock.calls.at(-1)?.[0].turn_id ?? 'missing-turn';
    expect(stoppedAssistant?.visualObservationRefs).toEqual([
      dialogVisualObservationReference(requestTurnId),
    ]);
  });

  it('merges retry images into manual attachments that arrive while the request is pending', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟添加延迟图片' }));

    await act(async () => {
      pending.reject(new Error('provider unavailable'));
      try {
        await pending.promise;
      } catch {
        // The Dialog request handler owns the failure and restores retry state.
      }
    });

    await waitFor(() => {
      const attachmentNames = screen.getByTestId('composer-attachments').textContent ?? '';
      expect(attachmentNames).toContain('manual-note.png');
      expect(attachmentNames).toContain('late-note.png');
      expect(attachmentNames).toContain('figure-one.png');
      expect(attachmentNames.match(/manual-note\.png/g)).toHaveLength(1);
    });
  });

  it('reserves the last retry slot for the hidden visual selection pixels', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    fireEvent.click(screen.getByRole('button', { name: '模拟加入 5 张新图片' }));
    await act(async () => {
      pending.reject(new Error('provider unavailable'));
      try {
        await pending.promise;
      } catch {
        // The Dialog request handler owns the failure and restores retry state.
      }
    });

    await waitFor(() => {
      const attachmentNames = screen.getByTestId('composer-attachments').textContent ?? '';
      replacementComposerAttachments.slice(0, 5).forEach((attachment) => {
        expect(attachmentNames).toContain(attachment.name);
      });
      expect(attachmentNames).toContain('figure-one.png');
      expect(attachmentNames).not.toContain('manual-note.png');
      expect(attachmentNames.split(',')).toHaveLength(6);
      expect(screen.getByRole('group', { name: '当前 PDF 选区' })).toHaveTextContent('选中的图');
    });
  });

  it('keeps six newer manual images and omits selection metadata when hidden pixels cannot be restored', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    fireEvent.click(screen.getByRole('button', { name: '模拟加入 6 张新图片' }));
    await act(async () => {
      pending.reject(new Error('provider unavailable'));
      try {
        await pending.promise;
      } catch {
        // The Dialog request handler owns the failure and restores retry state.
      }
    });

    await waitFor(() => {
      const attachmentNames = screen.getByTestId('composer-attachments').textContent ?? '';
      replacementComposerAttachments.forEach((attachment) => {
        expect(attachmentNames).toContain(attachment.name);
      });
      expect(attachmentNames).not.toContain('figure-one.png');
      expect(attachmentNames).not.toContain('manual-note.png');
      expect(attachmentNames.split(',')).toHaveLength(6);
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    });
  });

  it('keeps pending attachment reads across composer remounts and rejects early submission', async () => {
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '模拟开始延迟附件读取' }));
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '模拟强制提交' }));
    expect(mockedStreamIntelligentChatMessage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '关闭 paper.pdf' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
    });

    await act(async () => {
      completePendingAttachmentRead?.();
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '发送' })).not.toBeDisabled();
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('late-note.png');
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
    });
  });

  it('does not restore stale selection pixels after a PDF A-to-B-to-A round trip', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    window.sessionStorage.setItem('pdf-tabs:v1', JSON.stringify({
      tabs: [
        { materialId: 'mat-paper', title: 'paper.pdf' },
        { materialId: 'mat-other', title: 'other.pdf' },
      ],
      activeId: 'mat-paper',
      views: {},
    }));
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    fireEvent.click(screen.getByRole('tab', { name: 'other.pdf' }));
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-other');
    });
    fireEvent.click(screen.getByRole('tab', { name: 'paper.pdf' }));
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-paper');
    });

    await act(async () => {
      pending.reject(new Error('provider unavailable'));
      try {
        await pending.promise;
      } catch {
        // The Dialog request handler owns the failure and restores retry state.
      }
    });

    await waitFor(() => {
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    });
  });

  it('ignores a visual crop that finishes after the reader switches to another PDF', async () => {
    window.sessionStorage.setItem('pdf-tabs:v1', JSON.stringify({
      tabs: [
        { materialId: 'mat-paper', title: 'paper.pdf' },
        { materialId: 'mat-other', title: 'other.pdf' },
      ],
      activeId: 'mat-paper',
      views: {},
    }));
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(within(reader).getByRole('button', { name: '模拟开始延迟选择图' }));
    expect(completePendingRegionCapture).not.toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: 'other.pdf' }));
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-other');
    });

    act(() => completePendingRegionCapture?.());

    expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('delayed-figure.png');
  });

  it('does not restore old selection pixels after the request leaves its PDF context', async () => {
    const pending = createDeferred<void>();
    mockedStreamIntelligentChatMessage.mockImplementationOnce(async () => pending.promise);
    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    const reader = await screen.findByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    fireEvent.click(within(reader).getByRole('button', { name: '模拟选择图' }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(screen.getByLabelText('对话输入')).toBeDisabled());

    fireEvent.click(screen.getByRole('button', { name: '关闭 paper.pdf' }));
    await waitFor(() => {
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    });

    await act(async () => {
      pending.reject(new Error('provider unavailable'));
      try {
        await pending.promise;
      } catch {
        // The Dialog request handler owns the failure and restores retry state.
      }
    });

    await waitFor(() => {
      expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
      expect(screen.getByTestId('composer-attachments')).not.toHaveTextContent('figure-one.png');
      expect(screen.queryByRole('group', { name: '当前 PDF 选区' })).not.toBeInTheDocument();
    });
  });

  it('lets Dialog own evidence activation without enabling child navigation', () => {
    renderDialog(['/dialog?project_id=project-a']);

    expect(screen.getByRole('region', { name: '智能研读对话' }))
      .toHaveAttribute('data-navigate-evidence-after-select', 'false');
  });

  it('keeps a cross-material citation bbox when the reader mount reports the initial page', async () => {
    pdfReaderShellMockState.emitInitialPageChangeOnMount = true;
    conversationMessages = [{
      id: 'assistant-with-cross-material-bbox',
      role: 'assistant',
      content: '图表引用应在切换文献后保留精确区域。',
      evidence: [{
        evidence_id: 'ev-cross-material-bbox',
        material_id: 'mat-target',
        chunk_id: 'chunk-target-bbox',
        page: 5,
        source: 'target.pdf',
        bbox: [0.12, 0.24, 0.5, 0.16],
        bbox_unit: 'normalized_ratio',
        quote: 'Figure 2 caption must not become a text anchor.',
        anchor_kind: 'visual',
      }],
    }];
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-start',
        project_id: 'project-a',
        title: 'start.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
      {
        material_id: 'mat-target',
        project_id: 'project-a',
        title: 'target.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-start&material_title=start.pdf',
    ]);
    expect(await within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .findByTestId('embedded-pdf-reader')).toHaveTextContent('mat-start');

    fireEvent.click(screen.getByRole('button', { name: '打开证据 1' }));

    await waitFor(() => expect(pdfReaderShellMockState.initialPageChanges).toContain(5));
    const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .getByTestId('embedded-pdf-reader');
    expect(reader).toHaveTextContent('mat-target');
    expect(reader).toHaveAttribute('data-page', '5');
    expect(reader).toHaveAttribute('data-bbox', '0.12,0.24,0.5,0.16');
    expect(reader).toHaveAttribute('data-quote', '');
    expect(reader).toHaveAttribute(
      'data-highlight-rects',
      JSON.stringify([{ x: 0.12, y: 0.24, w: 0.5, h: 0.16 }]),
    );

    mockedStreamIntelligentChatMessage.mockImplementationOnce(async (_payload, options) => {
      options.onEvent({ event: 'done', response: 'anchor preserved', session_id: 'session-anchor-preserved' });
    });
    fireEvent.change(screen.getByLabelText('对话输入'), {
      target: { value: '继续基于这个图表提问' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockedStreamIntelligentChatMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          material_id: 'mat-target',
          current_pdf_context: expect.objectContaining({
            material_id: 'mat-target',
            page: 5,
            chunk_id: 'chunk-target-bbox',
            bbox: [0.12, 0.24, 0.5, 0.16],
            bbox_unit: 'normalized_ratio',
            context_kind: 'deep_link',
          }),
        }),
        expect.any(Object),
      );
    });
  });

  it('keeps a cross-material citation quote when the reader mount reports the initial page', async () => {
    pdfReaderShellMockState.emitInitialPageChangeOnMount = true;
    conversationMessages = [{
      id: 'assistant-with-cross-material-quote',
      role: 'assistant',
      content: '文本引用应在切换文献后保留原句锚点。',
      evidence: [{
        evidence_id: 'ev-cross-material-quote',
        material_id: 'mat-target',
        chunk_id: 'chunk-target-quote',
        page: 6,
        source: 'target.pdf',
        quote: 'The exact sentence survives the document switch.',
      }],
    }];
    mockedLocateChunk.mockResolvedValueOnce(null);
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-start',
        project_id: 'project-a',
        title: 'start.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
      {
        material_id: 'mat-target',
        project_id: 'project-a',
        title: 'target.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-start&material_title=start.pdf',
    ]);
    expect(await within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .findByTestId('embedded-pdf-reader')).toHaveTextContent('mat-start');

    fireEvent.click(screen.getByRole('button', { name: '打开证据 1' }));

    await waitFor(() => expect(pdfReaderShellMockState.initialPageChanges).toContain(6));
    const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .getByTestId('embedded-pdf-reader');
    expect(reader).toHaveTextContent('mat-target');
    expect(reader).toHaveAttribute('data-page', '6');
    expect(reader).toHaveAttribute('data-quote', 'The exact sentence survives the document switch.');
    expect(reader).toHaveAttribute('data-highlight-rects', '[]');
  });

  it('retains the exact text quote when a page-level reference is enriched with a block bbox', async () => {
    conversationMessages = [
      {
        id: 'assistant-with-evidence',
        role: 'assistant',
        content: '正文里的 [1] 应该能直接打开来源。',
        evidence: [
          {
            evidence_id: 'ev-1',
            material_id: 'mat-paper',
            chunk_id: 'chunk-paper-1',
            page: 5,
            source: 'paper.pdf',
            text: 'A wider evidence context.',
            quote: 'The exact cited sentence.',
          },
        ],
      },
    ];
    mockedLocateChunk.mockResolvedValueOnce({
      material_id: 'mat-paper',
      chunk_id: 'chunk-paper-1',
      page: 5,
      chunk_index: 2,
      bbox: [0.12, 0.24, 0.5, 0.08],
      bbox_unit: 'normalized_ratio',
    });
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-paper',
        project_id: 'project-a',
        title: 'paper.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog(['/dialog?project_id=project-a']);

    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));

    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-paper');
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '5');
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveAttribute('data-bbox', '0.12,0.24,0.5,0.08');
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveAttribute(
          'data-highlight-rects',
          '[]',
        );
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveAttribute('data-quote', 'The exact cited sentence.');
    });
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-paper-1', 'project-a');
  });

  it('uses the locator page with its bbox when evidence and locator pages differ', async () => {
    conversationMessages = [{
      id: 'assistant-with-stale-evidence-page',
      role: 'assistant',
      content: '正文里的 [1] 应使用同一定位来源。',
      evidence: [{
        evidence_id: 'ev-stale-page',
        material_id: 'mat-paper',
        chunk_id: 'chunk-moved-to-page-7',
        page: 5,
        source: 'paper.pdf',
        text: 'A wider evidence context.',
        quote: 'The exact cited sentence.',
      }],
    }];
    mockedLocateChunk.mockResolvedValueOnce({
      material_id: 'mat-paper',
      chunk_id: 'chunk-moved-to-page-7',
      page: 7,
      chunk_index: 2,
      bbox: [0.14, 0.28, 0.48, 0.09],
      bbox_unit: 'normalized_ratio',
    });
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog(['/dialog?project_id=project-a']);
    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveTextContent('mat-paper');
      expect(reader).toHaveAttribute('data-page', '7');
      expect(reader).toHaveAttribute('data-bbox', '0.14,0.28,0.48,0.09');
      expect(reader).toHaveAttribute(
        'data-highlight-rects',
        '[]',
      );
      expect(reader).toHaveAttribute('data-quote', 'The exact cited sentence.');
    });
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-moved-to-page-7', 'project-a');
  });

  it('falls back to an exact text quote while keeping the known page when locator has no bbox', async () => {
    conversationMessages = [{
      id: 'assistant-with-quote-evidence',
      role: 'assistant',
      content: '正文里的 [1] 应定位到原句。',
      evidence: [{
        evidence_id: 'ev-quote',
        material_id: 'mat-paper',
        chunk_id: 'chunk-quote-1',
        page: 5,
        source: 'paper.pdf',
        text: 'A wider evidence context.',
        quote: '  The exact\n cited sentence.  ',
      }],
    }];
    mockedLocateChunk.mockResolvedValueOnce(null);
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog(['/dialog?project_id=project-a']);
    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveAttribute('data-page', '5');
      expect(reader).toHaveAttribute('data-quote', 'The exact cited sentence.');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-quote-1', 'project-a');
  });

  it('rejects a locator that conflicts with the clicked evidence identity', async () => {
    conversationMessages = [{
      id: 'assistant-with-conflicting-locator',
      role: 'assistant',
      content: '正文里的 [1] 必须保留原引用目标。',
      evidence: [{
        evidence_id: 'ev-original',
        material_id: 'mat-paper',
        chunk_id: 'chunk-original',
        page: 5,
        source: 'paper.pdf',
        quote: 'The original cited sentence.',
      }],
    }];
    mockedLocateChunk.mockResolvedValueOnce({
      material_id: 'mat-other',
      chunk_id: 'chunk-other',
      page: 9,
      chunk_index: 4,
      bbox: [0.2, 0.3, 0.4, 0.1],
      bbox_unit: 'normalized_ratio',
    });
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog(['/dialog?project_id=project-a']);
    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveTextContent('mat-paper');
      expect(reader).toHaveAttribute('data-page', '5');
      expect(reader).toHaveAttribute('data-quote', 'The original cited sentence.');
      expect(reader).toHaveAttribute('data-highlight-rects', '[]');
    });
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-original', 'project-a');
  });

  it('keeps the newest evidence click when an older locator resolves later', async () => {
    const firstLocator = createDeferred<Awaited<ReturnType<typeof locateChunk>>>();
    conversationMessages = [{
      id: 'assistant-with-competing-evidence',
      role: 'assistant',
      content: '连续点击 [1] 和 [2] 时应保留后一次选择。',
      evidence: [
        {
          evidence_id: 'ev-first',
          chunk_id: 'chunk-first',
          source: 'first.pdf',
        },
        {
          evidence_id: 'ev-second',
          chunk_id: 'chunk-second',
          source: 'second.pdf',
        },
      ],
    }];
    mockedLocateChunk.mockImplementation((chunkId) => {
      if (chunkId === 'chunk-first') return firstLocator.promise;
      return Promise.resolve({
        material_id: 'mat-second',
        chunk_id: 'chunk-second',
        page: 9,
        chunk_index: 2,
        bbox: [0.11, 0.22, 0.44, 0.12],
        bbox_unit: 'normalized_ratio',
      });
    });
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-first',
        project_id: 'project-a',
        title: 'first.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
      {
        material_id: 'mat-second',
        project_id: 'project-a',
        title: 'second.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog(['/dialog?project_id=project-a']);
    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));
    fireEvent.click(screen.getByRole('button', { name: '打开证据 2' }));

    await waitFor(() => {
      const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader');
      expect(reader).toHaveTextContent('mat-second');
      expect(reader).toHaveAttribute('data-page', '9');
      expect(reader).toHaveAttribute(
        'data-highlight-rects',
        JSON.stringify([{ x: 0.11, y: 0.22, w: 0.44, h: 0.12 }]),
      );
    });

    await act(async () => {
      firstLocator.resolve({
        material_id: 'mat-first',
        chunk_id: 'chunk-first',
        page: 3,
        chunk_index: 1,
        bbox: [0.1, 0.2, 0.3, 0.08],
        bbox_unit: 'normalized_ratio',
      });
      await firstLocator.promise;
    });

    const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .getByTestId('embedded-pdf-reader');
    expect(reader).toHaveTextContent('mat-second');
    expect(reader).toHaveAttribute('data-page', '9');
    expect(mockedLocateChunk).toHaveBeenNthCalledWith(1, 'chunk-first', 'project-a');
    expect(mockedLocateChunk).toHaveBeenNthCalledWith(2, 'chunk-second', 'project-a');
  });

  it('keeps a manually selected PDF tab when an older evidence locator resolves later', async () => {
    const pendingLocator = createDeferred<Awaited<ReturnType<typeof locateChunk>>>();
    conversationMessages = [{
      id: 'assistant-with-pending-evidence',
      role: 'assistant',
      content: '引用定位期间手动切换文献时，应保留用户选择。',
      evidence: [{
        evidence_id: 'ev-pending',
        chunk_id: 'chunk-pending',
        source: 'evidence.pdf',
      }],
    }];
    mockedLocateChunk.mockReturnValueOnce(pendingLocator.promise);
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-manual',
        project_id: 'project-a',
        title: 'manual.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
      {
        material_id: 'mat-evidence',
        project_id: 'project-a',
        title: 'evidence.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);
    window.sessionStorage.setItem('pdf-tabs:v1', JSON.stringify({
      tabs: [
        { materialId: 'mat-start', title: 'start.pdf' },
        { materialId: 'mat-manual', title: 'manual.pdf' },
      ],
      activeId: 'mat-start',
      views: {},
    }));

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-start&material_title=start.pdf',
    ]);

    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-pending', 'project-a');
    fireEvent.click(screen.getByRole('tab', { name: 'manual.pdf' }));

    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-manual');
    });

    await act(async () => {
      pendingLocator.resolve({
        material_id: 'mat-evidence',
        chunk_id: 'chunk-pending',
        page: 6,
        chunk_index: 1,
        bbox: [0.1, 0.2, 0.4, 0.08],
        bbox_unit: 'normalized_ratio',
      });
      await pendingLocator.promise;
    });

    const reader = within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
      .getByTestId('embedded-pdf-reader');
    expect(reader).toHaveTextContent('mat-manual');
  });

  it('keeps a manually selected reader page when an older evidence locator resolves later', async () => {
    const pendingLocator = createDeferred<Awaited<ReturnType<typeof locateChunk>>>();
    conversationMessages = [{
      id: 'assistant-with-pending-page-evidence',
      role: 'assistant',
      content: '引用定位期间手动翻页时，应保留用户页码。',
      evidence: [{
        evidence_id: 'ev-pending-page',
        chunk_id: 'chunk-pending-page',
        source: 'paper.pdf',
      }],
    }];
    mockedLocateChunk.mockReturnValueOnce(pendingLocator.promise);
    listMaterialsMock.mockResolvedValue([{
      material_id: 'mat-paper',
      project_id: 'project-a',
      title: 'paper.pdf',
      title_en: '',
      summary: '',
      summary_en: '',
      type: 'reference',
      focus_points: [],
      focus_points_en: [],
      created_at: '2026-05-29T00:00:00.000Z',
      updated_at: '2026-05-29T00:00:00.000Z',
    }]);

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf&page=3',
    ]);
    const readerRegion = screen.getByRole('region', { name: '中间栏本文献阅读器' });
    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));
    expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-pending-page', 'project-a');
    fireEvent.click(within(readerRegion).getByRole('button', { name: '模拟翻到第 7 页' }));

    await waitFor(() => {
      expect(within(readerRegion).getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '7');
    });

    await act(async () => {
      pendingLocator.resolve({
        material_id: 'mat-paper',
        chunk_id: 'chunk-pending-page',
        page: 6,
        chunk_index: 1,
        bbox: [0.1, 0.2, 0.4, 0.08],
        bbox_unit: 'normalized_ratio',
      });
      await pendingLocator.promise;
    });

    const reader = within(readerRegion).getByTestId('embedded-pdf-reader');
    expect(reader).toHaveAttribute('data-page', '7');
    expect(reader).toHaveAttribute('data-bbox', '');
  });

  it('uses the chunk locator before opening a chunk-only SmartRead evidence reference', async () => {
    conversationMessages = [
      {
        id: 'assistant-with-chunk-only-evidence',
        role: 'assistant',
        content: '参考片段只有 chunk_id 时也应该能打开来源。',
        evidence: [
          {
            evidence_id: 'ev-located',
            chunk_id: 'chunk-located',
            source: 'located.pdf',
            text: 'Evidence text.',
          },
        ],
      },
    ];
    mockedLocateChunk.mockResolvedValueOnce({
      material_id: 'mat-located',
      chunk_id: 'chunk-located',
      page: 8,
      chunk_index: 3,
      bbox: [0.1, 0.2, 0.3, 0.1],
      bbox_unit: 'normalized_ratio',
    });
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-located',
        project_id: 'project-a',
        title: 'located.pdf',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);

    renderDialog(['/dialog?project_id=project-a']);

    fireEvent.click(await screen.findByRole('button', { name: '打开证据 1' }));

    await waitFor(() => {
      expect(mockedLocateChunk).toHaveBeenCalledWith('chunk-located', 'project-a');
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-located');
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveAttribute('data-page', '8');
    });
  });

  it('shows chunk-derived concrete suggested questions for an empty pinned-paper chat', async () => {
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-paper',
        project_id: 'project-a',
        title: 'Laser welding joint performance',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);
    listMaterialChunksMock.mockResolvedValue({
      material_id: 'mat-paper',
      total_chunks: 1,
      chunks: [
        {
          material_id: 'mat-paper',
          chunk_id: 'chunk-weld',
          content: 'Laser welding creates a heat affected zone and fusion zone that influence fatigue strength of welded joints.',
        },
      ],
    });

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    fireEvent.click(await screen.findByRole('button', { name: '研读对话' }));
    const suggestion = await screen.findByRole('button', { name: /材料与焊法/ });
    expect(suggestion).toHaveTextContent('材料或接头形式');
    fireEvent.click(suggestion);

    await waitFor(() => {
      expect(String((screen.getByLabelText('对话输入') as HTMLInputElement).value))
        .toContain('使用了哪些焊接方式或关键工艺参数');
    });
    expect(listMaterialChunksMock).toHaveBeenCalledWith('project-a', 'mat-paper');
  });

  it('launches multi-agent reading enhancement with the current paper context', async () => {
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-paper',
        project_id: 'project-a',
        title: 'Laser welding joint performance',
        title_en: '',
        summary: '',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);
    listMaterialChunksMock.mockResolvedValue({
      material_id: 'mat-paper',
      total_chunks: 1,
      chunks: [
        {
          material_id: 'mat-paper',
          chunk_id: 'chunk-weld',
          content: 'Laser welding creates a heat affected zone and fusion zone that influence fatigue strength of welded joints.',
        },
      ],
    });

    renderDialog([
      '/dialog?project_id=project-a&scope=paper&material_id=mat-paper&material_title=paper.pdf',
    ]);

    fireEvent.click(await screen.findByRole('button', { name: '研读对话' }));
    await screen.findByRole('button', { name: /材料与焊法/ });
    fireEvent.click(await screen.findByRole('button', { name: '增强' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '多人研读' }));

    await waitFor(() => {
      expect(String((screen.getByLabelText('讨论问题') as HTMLTextAreaElement).value))
        .toContain('多角色研读讨论');
    });
    expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' })).getByTestId('embedded-pdf-reader'))
      .toHaveTextContent('mat-paper');
    expect(String((screen.getByLabelText('讨论问题') as HTMLTextAreaElement).value))
      .toContain('材料或接头形式');
    expect(screen.getByText('from_project')).toBeInTheDocument();
  });

  // B10 (2026-06-13): user reported clicking "研读" on a context-rail material whose
  // title is the real paper title (no .pdf suffix) left the center pane on chat
  // instead of switching to the reader. Root cause: pinnedLooksLikePdf only matched
  // titles ending in .pdf, so readerTabAvailable stayed false and the bounce-back
  // effect (centerTab==='reader' && !readerTabAvailable -> setCenterTab('chat'))
  // immediately reverted the tab. The fix makes pinnedLooksLikePdf optimistic for
  // any pinned material id, since project-rail materials are always PDF references.
  it('switches center pane to the reader when 研读 is clicked on a non-.pdf-suffixed material', async () => {
    listMaterialsMock.mockResolvedValue([
      {
        material_id: 'mat-real-title',
        project_id: 'project-a',
        title: 'Laser welding joint performance',  // no .pdf suffix — real paper title
        title_en: '',
        summary: 'A reference paper without a .pdf-suffixed title in the library.',
        summary_en: '',
        type: 'reference',
        focus_points: [],
        focus_points_en: [],
        created_at: '2026-05-29T00:00:00.000Z',
        updated_at: '2026-05-29T00:00:00.000Z',
      },
    ]);
    // Preset context rail tab to '项目文献' so the material card with the 研读
    // button is rendered directly.
    window.localStorage.setItem('dialog-context-tab-v1', 'project');

    renderDialog(['/dialog?project_id=project-a']);

    // Wait for the project materials list to render, then click 研读.
    const readButton = await screen.findByRole('button', { name: '研读' });
    fireEvent.click(screen.getByRole('button', { name: '模拟添加手动图片' }));
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
    fireEvent.click(readButton);

    // After the click, the center pane must switch to the embedded reader and
    // stay there (no bounce back to chat).
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: '中间栏本文献阅读器' }))
        .getByTestId('embedded-pdf-reader')).toHaveTextContent('mat-real-title');
    });
    expect(screen.getByTestId('composer-attachments')).toHaveTextContent('manual-note.png');
  });
});
