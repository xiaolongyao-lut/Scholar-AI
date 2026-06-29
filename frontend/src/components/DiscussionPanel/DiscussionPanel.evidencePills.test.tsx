/**
 * Tests for DiscussionPanel evidence pills + scroll helper (G4).
 *
 * Covers:
 *  - evidenceSnippetDomId returns the canonical anchor id
 *  - scrollToEvidence finds element by id and triggers scrollIntoView
 *  - scrollToEvidence is a silent no-op when the element is missing
 *  - DiscussionEvidencePackSection renders snippet cards with the
 *    matching anchor id derived from evidence_ids (or the position
 *    fallback when evidence_ids is missing)
 *  - Section returns null when evidence is null / has no snippets
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import {
  DiscussionCitationOverlapWarning,
  DiscussionCitedEvidencePills,
  DiscussionEvidencePackSection,
  buildCitationOverlapWarningSummary,
  evidenceSnippetDomId,
  formatDiscussionAnswerText,
  formatDiscussionEvidenceLabel,
  formatDiscussionRunError,
  formatDiscussionSynthesisText,
  scrollToEvidence,
} from './DiscussionPanel';
import type {
  DiscussionRunResult,
  DiscussionEvidencePackPayload,
  DiscussionAgentTrace,
} from '../../services/discussionApi';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function parseLocationUrl(value: string): URL {
  return new URL(value, 'http://localhost');
}

function makeResult(
  evidence: DiscussionEvidencePackPayload | null,
): DiscussionRunResult {
  return {
    run_id: 'r1',
    project_id: 'p1',
    query: 'q',
    evidence,
    turns: [],
    synthesis: {
      text: '',
      strategy: 'synthesize',
      synthesizer_agent_id: null,
      synthesizer_provider: '',
      synthesizer_model: '',
      success: true,
      error: null,
    },
    elapsed_ms: 0,
    stopped_early: false,
    stop_reason: 'max_turns',
    convergence: null,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  locateChunkMock.mockReset();
});

describe('evidenceSnippetDomId', () => {
  it('returns evidence-snippet-<id>', () => {
    expect(evidenceSnippetDomId('E1')).toBe('evidence-snippet-E1');
    expect(evidenceSnippetDomId('E10')).toBe('evidence-snippet-E10');
  });
});

describe('discussion visible copy helpers', () => {
  it('formats evidence labels without exposing raw ids', () => {
    expect(formatDiscussionEvidenceLabel('E2')).toBe('证据 2');
    expect(formatDiscussionEvidenceLabel('chunk_abc', 3)).toBe('证据 4');
  });

  it('sanitizes raw runtime errors', () => {
    expect(formatDiscussionRunError(new Error('env=VISION_PROVIDER /api/discussion capability_resolved'))).toBe(
      '讨论运行失败，请检查角色接口和证据配置。',
    );
    expect(formatDiscussionRunError(new Error('project_id is required'))).toBe('当前证据来源需要先选择项目。');
  });

  it('sanitizes live agent answers and synthesis before rendering or reuse', () => {
    const unsafe = 'env=VISION_PROVIDER /api/discussion capability_resolved C:\\Users\\xiao\\trace.json';

    expect(formatDiscussionAnswerText(unsafe)).toBe('回答内容已隐藏，避免显示内部路径或系统字段。');
    expect(formatDiscussionSynthesisText(unsafe)).toBe('综合结论已隐藏，避免显示内部路径或系统字段。');
    expect(formatDiscussionAnswerText('这个结论需要补充对照实验。')).toBe('这个结论需要补充对照实验。');
  });
});

describe('scrollToEvidence', () => {
  it('calls scrollIntoView on the matching element', () => {
    const node = document.createElement('div');
    node.id = evidenceSnippetDomId('E2');
    const spy = vi.fn();
    Object.defineProperty(node, 'scrollIntoView', {
      value: spy,
      configurable: true,
    });
    document.body.appendChild(node);
    scrollToEvidence('E2');
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'smooth', block: 'center' }),
    );
    document.body.removeChild(node);
  });

  it('is a silent no-op when element does not exist', () => {
    expect(() => scrollToEvidence('E999')).not.toThrow();
  });

  it('toggles a brief highlight class on the target element', () => {
    vi.useFakeTimers();
    try {
      const node = document.createElement('div');
      node.id = evidenceSnippetDomId('E3');
      Object.defineProperty(node, 'scrollIntoView', {
        value: vi.fn(),
        configurable: true,
      });
      document.body.appendChild(node);
      scrollToEvidence('E3');
      expect(node.classList.contains('ring-primary')).toBe(true);
      vi.advanceTimersByTime(1600);
      expect(node.classList.contains('ring-primary')).toBe(false);
      document.body.removeChild(node);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('DiscussionEvidencePackSection', () => {
  it('renders a card per snippet keyed by evidence_ids', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'p1',
      query: 'q',
      truncated: false,
      evidence_ids: ['E1', 'E2'],
      snippets: [
        { chunk_id: 'c1', content: 'first body', source: 'paper one' },
        { chunk_id: 'c2', content: 'second body', source: 'paper two' },
      ] as unknown as Record<string, unknown>[],
    });
    const { container, getByTestId } = render(
      <DiscussionEvidencePackSection result={result} />,
    );
    expect(container.querySelector('#evidence-snippet-E1')).not.toBeNull();
    expect(container.querySelector('#evidence-snippet-E2')).not.toBeNull();
    expect(getByTestId('evidence-snippet-E1').textContent).toContain('first body');
    expect(getByTestId('evidence-snippet-E2').textContent).toContain('second body');
  });

  it('falls back to E1..EN when evidence_ids is missing on legacy payloads', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'p1',
      query: 'q',
      truncated: false,
      // evidence_ids omitted on purpose to simulate a stored old payload
      snippets: [
        { chunk_id: 'c1', content: 'old payload body' },
      ] as unknown as Record<string, unknown>[],
    });
    const { container } = render(
      <DiscussionEvidencePackSection result={result} />,
    );
    expect(container.querySelector('#evidence-snippet-E1')).not.toBeNull();
  });

  it('does not render raw chunk identifiers as visible source labels', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'p1',
      query: 'q',
      truncated: false,
      evidence_ids: ['chunk_abc'],
      snippets: [
        { chunk_id: 'chunk_abc', content: 'env=VISION_PROVIDER /api/discussion' },
      ] as unknown as Record<string, unknown>[],
    });
    render(<DiscussionEvidencePackSection result={result} />);

    expect(screen.getAllByText('证据 1').length).toBeGreaterThan(0);
    expect(screen.getByText('证据内容已隐藏，避免显示内部路径或系统字段。')).toBeInTheDocument();
    expect(screen.queryByText('chunk_abc')).not.toBeInTheDocument();
    expect(screen.queryByText(/env=VISION_PROVIDER/)).not.toBeInTheDocument();
  });

  it('returns null when evidence is null', () => {
    const result = makeResult(null);
    const { container } = render(
      <DiscussionEvidencePackSection result={result} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('returns null when snippets is empty', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'p1',
      query: 'q',
      truncated: false,
      evidence_ids: [],
      snippets: [],
    });
    const { container } = render(
      <DiscussionEvidencePackSection result={result} />,
    );
    expect(container.firstChild).toBeNull();
  });
});

describe('DiscussionCitedEvidencePills', () => {
  const trace: DiscussionAgentTrace = {
    agent_id: 'critic_1',
    role: 'critic',
    role_label: '批评方',
    credential_id: null,
    provider: 'local',
    model: 'test',
    latency_ms: 1,
    success: true,
    answer: 'uses E1',
    error: null,
    cited_evidence_ids: ['E1'],
  };

  it('opens a cited evidence pill in the PDF reader when snippet metadata has a material target', async () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'project-1',
      query: 'q',
      truncated: false,
      evidence_ids: ['E1'],
      snippets: [
        {
          chunk_id: 'chunk-1',
          material_id: 'mat-1',
          page: 6,
          content: 'evidence body',
          source: 'paper one',
        },
      ] as unknown as Record<string, unknown>[],
    });
    render(
      <MemoryRouter>
        <DiscussionCitedEvidencePills result={result} trace={trace} />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /paper one/i }));

    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('mat-1');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('p1');
      expect(parsed.searchParams.get('page')).toBe('6');
      expect(parsed.searchParams.get('chunk')).toBe('chunk-1');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('keeps the evidence-card scroll fallback when snippet metadata cannot open a PDF target', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'project-1',
      query: 'q',
      truncated: false,
      evidence_ids: ['E1'],
      snippets: [
        { chunk_id: 'chunk-1', content: 'evidence body', source: 'paper one' },
      ] as unknown as Record<string, unknown>[],
    });
    const node = document.createElement('div');
    node.id = evidenceSnippetDomId('E1');
    const spy = vi.fn();
    Object.defineProperty(node, 'scrollIntoView', {
      value: spy,
      configurable: true,
    });
    document.body.appendChild(node);
    try {
      render(
        <MemoryRouter>
          <DiscussionCitedEvidencePills result={result} trace={trace} />
        </MemoryRouter>,
      );
      fireEvent.click(screen.getByRole('button', { name: '定位证据 1' }));
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      document.body.removeChild(node);
    }
  });
});

describe('DiscussionCitationOverlapWarning', () => {
  function makeTrace(
    agentId: string,
    roleLabel: string,
    citedEvidenceIds: string[],
  ): DiscussionAgentTrace {
    return {
      agent_id: agentId,
      role: 'critic',
      role_label: roleLabel,
      credential_id: null,
      provider: 'local',
      model: 'test',
      latency_ms: 1,
      success: true,
      answer: 'answer',
      error: null,
      cited_evidence_ids: citedEvidenceIds,
    };
  }

  it('summarizes repeated cited evidence across successful agents', () => {
    const result = makeResult({
      pack_id: 'pk',
      pack_version: '1',
      project_id: 'p1',
      query: 'q',
      truncated: false,
      evidence_ids: ['E1', 'E2', 'E3'],
      snippets: [],
    });
    result.turns = [
      {
        turn_index: 0,
        agent_traces: [
          makeTrace('proposer_1', '支持方', ['E1', 'E2']),
          makeTrace('critic_1', '批评方', ['E2', 'E3']),
        ],
      },
    ];

    const summary = buildCitationOverlapWarningSummary(result);

    expect(summary?.overlapping_evidence_ids).toEqual(['E2']);
    expect(summary?.max_pair_overlap).toBeCloseTo(1 / 3);
  });

  it('renders an accessible warning when citations overlap', () => {
    const result = makeResult(null);
    result.turns = [
      {
        turn_index: 0,
        agent_traces: [
          makeTrace('proposer_1', '支持方', ['E1', 'E2']),
          makeTrace('critic_1', '批评方', ['E2']),
        ],
      },
    ];

    render(<DiscussionCitationOverlapWarning result={result} />);

    expect(screen.getByRole('alert')).toHaveTextContent('引用重叠');
    expect(screen.getByText('证据 2')).toBeInTheDocument();
    expect(screen.getByText(/支持方 \/ 批评方/)).toBeInTheDocument();
  });

  it('does not render when cited evidence is independent', () => {
    const result = makeResult(null);
    result.turns = [
      {
        turn_index: 0,
        agent_traces: [
          makeTrace('proposer_1', '支持方', ['E1']),
          makeTrace('critic_1', '批评方', ['E2']),
        ],
      },
    ];

    const { container } = render(<DiscussionCitationOverlapWarning result={result} />);

    expect(container.firstChild).toBeNull();
  });
});
