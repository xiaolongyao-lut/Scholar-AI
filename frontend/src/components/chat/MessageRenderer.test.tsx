import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { MessageRenderer, type ChatMessageData } from './MessageRenderer';
import { formatChatVisibleError } from './chatDisplay';
import type { VisualObservationReference } from '@/types/visualObservation';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

function renderMessage(message: ChatMessageData, options?: { projectId?: string | null }) {
  return render(
    <MemoryRouter>
      <MessageRenderer message={message} projectId={options?.projectId} />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

describe('MessageRenderer diagnostics', () => {
  it('renders only the answer body when a streamed provider includes display artifacts', () => {
    renderMessage({
      id: 'assistant-visible-answer-only',
      role: 'assistant',
      content: [
        '问题：请比较两种方法。',
        '两种方法的主要差异在约束条件。',
        '',
        '## 证据摘要：',
        '- 不应进入普通气泡。',
      ].join('\n'),
      status: 'streaming',
    });

    expect(screen.getByText('两种方法的主要差异在约束条件。')).toBeInTheDocument();
    expect(screen.queryByText(/问题：请比较两种方法/)).not.toBeInTheDocument();
    expect(screen.queryByText(/证据摘要/)).not.toBeInTheDocument();
    expect(screen.queryByText(/不应进入普通气泡/)).not.toBeInTheDocument();
  });

  it('does not create an assistant bubble before the first visible answer text', () => {
    renderMessage({
      id: 'assistant-empty-stream',
      role: 'assistant',
      content: '问题：仍在等待回答正文。',
      status: 'streaming',
    });

    expect(document.querySelector('.message-bubble')).not.toBeInTheDocument();
    expect(screen.queryByText('AI 思考中…')).not.toBeInTheDocument();
  });

  it.each([
    ['legacy evidence summary', '## 证据摘要：\n- 仅供内部审计。'],
    ['legacy external-agent bridge', '已切换为外部智能体回答模式。'],
    ['legacy evidence-ready placeholder', '证据已准备，等待智能体回答。'],
  ])('does not leave an empty completed bubble for %s content', (_label, content) => {
    render(
      <MemoryRouter>
        <MessageRenderer
          message={{
            id: `assistant-empty-${_label}`,
            role: 'assistant',
            content,
            status: 'done',
            timestamp: '2026-07-16T01:00:00.000Z',
          }}
          footer={<span>不应显示的消息操作</span>}
          onForkMessage={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(document.querySelector('.message-bubble')).not.toBeInTheDocument();
    expect(document.querySelector('time')).not.toBeInTheDocument();
    expect(screen.queryByText('不应显示的消息操作')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '从这里分叉' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '记到待确认' })).not.toBeInTheDocument();
  });

  it('keeps a figure-only assistant message when its text is fully sanitized', () => {
    renderMessage({
      id: 'assistant-figure-only-after-sanitize',
      role: 'assistant',
      content: '## 证据摘要：\n- 不进入普通正文。',
      status: 'done',
      relatedFigures: [{
        id: 'figure-only-1',
        kind: 'figure',
        label: '图 1',
        caption: 'Figure-only visual evidence.',
        material_id: 'material-1',
        page: 3,
        chunk_id: 'chunk-figure-only-1',
        asset_path: 'figures/material-1/figure-only-1.png',
        source: 'chunk_image_paths',
      }],
    }, { projectId: 'project-1' });

    expect(document.querySelector('.message-bubble')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '相关图表 1 项' })).toBeInTheDocument();
    expect(screen.queryByText(/证据摘要/)).not.toBeInTheDocument();
  });

  it('maps unsupported tool-calling proxy errors to an actionable visible message', () => {
    expect(
      formatChatVisibleError(
        new Error('status_code=500, Tool/function calling is not supported by this proxy.'),
      ),
    ).toBe('当前 API 代理不支持工具调用，请在设置中测试工具调用能力，或改用普通问答链路。');
  });

  it('renders SmartRead stream errors as failed messages instead of generating state', () => {
    renderMessage({
      id: 'assistant-stream-error',
      role: 'assistant',
      content: '回答失败：上游 LLM 响应超时，请稍后重试或在设置中切换服务地址。',
      status: 'error',
    });

    expect(screen.getByText('回答失败：上游 LLM 响应超时，请稍后重试或在设置中切换服务地址。')).toBeInTheDocument();
    expect(screen.getByText('生成失败')).toBeInTheDocument();
    expect(screen.queryByText('生成中…')).not.toBeInTheDocument();
  });

  it('keeps retrieval diagnostics and source summaries out of chat bubbles', () => {
    renderMessage({
      id: 'assistant-hidden-diagnostics',
      role: 'assistant',
      content: '这是直接面向用户的回答。',
      metadata: {
        diagnostics: {
          context: {
            chunkCount: 1,
            sourceCount: 1,
            chunks: [
              {
                index: 1,
                source: 'Ping 等 - 2026 - Oscillating laser welding.pdf',
                content: '不应独立显示的证据摘要。',
                relevance_score: 0.91,
                chunk_id: 'chunk-hidden-1',
                material_id: 'material-hidden-1',
                page: 2,
              },
            ],
          },
          retrieval: {
            retrieval_method: 'hybrid_rerank',
            embedding_status: 'active',
            rerank_status: 'active',
            joint_recall: {
              status: 'available',
              fusion: 'weighted_rrf',
              project_hit_count: 4,
              wiki_hit_count: 7,
              fused_count: 8,
              wiki_share_after_fusion: 0.625,
            },
          },
        },
      },
    });

    expect(screen.getByText('这是直接面向用户的回答。')).toBeInTheDocument();
    expect(screen.queryByText(/个参考片段/)).not.toBeInTheDocument();
    expect(screen.queryByText(/个来源/)).not.toBeInTheDocument();
    expect(screen.queryByText('Ping 等 - 2026 - Oscillating laser welding.pdf')).not.toBeInTheDocument();
    expect(screen.queryByText('不应独立显示的证据摘要。')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /联合召回/ })).not.toBeInTheDocument();
    expect(screen.queryByText('hybrid rerank')).not.toBeInTheDocument();
  });

  it('keeps visual observation references and candidate output out of normal answer bubbles', () => {
    const pollutedReference = {
      schema_version: 'scholar-ai-visual-observation-ref/v1',
      candidate_id: 'visual-candidate-hidden',
      turn_id: 'turn-hidden',
      route: 'direct_model',
      generation_status: 'succeeded',
      review_status: 'candidate',
      selection_ids: ['selection-hidden'],
      output_sha256: `sha256:${'1'.repeat(64)}`,
      cache_status: 'miss',
      read_endpoint: '/api/chat/visual-observations/visual-candidate-hidden',
      output_text: 'Candidate output must remain outside the answer bubble.',
    } as unknown as VisualObservationReference;

    renderMessage({
      id: 'assistant-visual-observation-hidden',
      role: 'assistant',
      content: '这是回答模型直接给用户的正文。',
      visualObservationRefs: [pollutedReference],
      status: 'done',
    });

    expect(screen.getByText('这是回答模型直接给用户的正文。')).toBeInTheDocument();
    expect(screen.queryByText('visual-candidate-hidden')).not.toBeInTheDocument();
    expect(screen.queryByText('direct_model')).not.toBeInTheDocument();
    expect(screen.queryByText('miss')).not.toBeInTheDocument();
    expect(screen.queryByText('/api/chat/visual-observations/visual-candidate-hidden')).not.toBeInTheDocument();
    expect(screen.queryByText('Candidate output must remain outside the answer bubble.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /相关图表/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /visual-candidate-hidden/ })).not.toBeInTheDocument();
  });

  it('keeps structured evidence out of the bubble when the answer has no inline citations', () => {
    renderMessage({
      id: 'assistant-mixed-evidence',
      role: 'assistant',
      content: '证据同时来自项目文献与 Wiki 记忆。',
      evidence: [
        {
          evidence_id: 'chunk:project-1',
          chunk_id: 'project-1',
          material_id: 'material-1',
          source: '项目论文 A',
          text: '项目证据摘要',
          source_type: 'project',
          joint_score: 0.031,
        },
        {
          evidence_id: 'wiki:synthesis/alsi10mg.md',
          chunk_id: 'wiki:synthesis/alsi10mg.md',
          source: 'Wiki 记忆',
          source_title: 'AlSi10Mg Wiki 综述',
          source_path: 'synthesis/alsi10mg.md',
          text: 'Wiki 证据摘要',
          source_type: 'wiki',
          joint_score: 0.0098,
        },
      ],
    });

    expect(screen.getByText('证据同时来自项目文献与 Wiki 记忆。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /项目论文 A/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /AlSi10Mg Wiki 综述/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Wiki')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('融合分: 0.03')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('融合分: 0.010')).not.toBeInTheDocument();
    expect(screen.queryByText('synthesis/alsi10mg.md')).not.toBeInTheDocument();
  });

  it('turns numeric answer citations into clickable evidence links', () => {
    const onSelectEvidence = vi.fn();
    const evidence = {
      evidence_id: 'evidence-1',
      chunk_id: 'chunk_hidden_1',
      material_id: 'material-1',
      source: 'Laser welding of AlSi10Mg',
      text: 'Laser welding evidence excerpt.',
      source_type: 'project' as const,
      page: 6,
    };

    render(
      <MemoryRouter>
        <MessageRenderer
          message={{
            id: 'assistant-inline-citation',
            role: 'assistant',
            content: 'AlSi10Mg 的激光焊接外观在图 4 中有对应证据 [1]。',
            evidence: [evidence],
          }}
          onSelectEvidence={onSelectEvidence}
        />
      </MemoryRouter>,
    );

    const citation = screen.getByRole('button', { name: /\[1\]/ });
    expect(citation).toHaveAttribute('title', 'Laser welding of AlSi10Mg · p.6');
    fireEvent.click(citation);

    expect(onSelectEvidence).toHaveBeenCalledTimes(1);
    expect(onSelectEvidence).toHaveBeenCalledWith(evidence);
    expect(screen.queryByText('chunk_hidden_1')).not.toBeInTheDocument();
  });

  it('turns grouped numeric citations into separate clickable evidence links', () => {
    const onSelectEvidence = vi.fn();
    const refs = [
      {
        evidence_id: 'evidence-1',
        chunk_id: 'chunk_hidden_1',
        material_id: 'material-1',
        source: 'Zhang 2019',
        text: 'Laser welding evidence.',
        page: 1,
      },
      {
        evidence_id: 'evidence-2',
        chunk_id: 'chunk_hidden_2',
        material_id: 'material-2',
        source: 'Nunes 2023',
        text: 'Review evidence.',
        page: 2,
      },
      {
        evidence_id: 'evidence-3',
        chunk_id: 'chunk_hidden_3',
        material_id: 'material-3',
        source: 'Ping 2026',
        text: 'Pore evidence.',
        page: 3,
      },
    ];

    render(
      <MemoryRouter>
        <MessageRenderer
          message={{
            id: 'assistant-inline-citation-group',
            role: 'assistant',
            content: '孔隙分布由多篇文献共同支持 [1, 2, 3]。',
            evidence: refs,
          }}
          onSelectEvidence={onSelectEvidence}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /\[2\]/ }));

    expect(screen.getByRole('button', { name: /\[1\]/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[3\]/ })).toBeInTheDocument();
    expect(onSelectEvidence).toHaveBeenCalledWith(refs[1]);
    expect(screen.queryByText('chunk_hidden_2')).not.toBeInTheDocument();
  });

  it('resolves grouped citations from diagnostic context chunks when evidence refs are sparse', () => {
    const onSelectEvidence = vi.fn();
    const citationChunks = [1, 7, 9, 11].map((index) => ({
      index,
      source: `Source ${index}`,
      content: `Context excerpt ${index}`,
      relevance_score: 1,
      chunk_id: `chunk-context-${index}`,
      material_id: `material-context-${index}`,
      page: index + 1,
    }));

    render(
      <MemoryRouter>
        <MessageRenderer
          projectId="project-1"
          onSelectEvidence={onSelectEvidence}
          message={{
            id: 'assistant-inline-citation-context-fallback',
            role: 'assistant',
            content: '孔隙分布由上下文片段共同支持 [1, 7, 9, 11]。',
            evidence: [],
            metadata: {
              diagnostics: {
                context: {
                  chunkCount: citationChunks.length,
                  sourceCount: citationChunks.length,
                  chunks: citationChunks,
                },
              },
            },
          }}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /\[9\]/ }));

    expect(screen.getByRole('button', { name: /\[1\]/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[7\]/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[11\]/ })).toBeInTheDocument();
    expect(onSelectEvidence).toHaveBeenCalledWith(expect.objectContaining({
      chunk_id: 'chunk-context-9',
      material_id: 'material-context-9',
      page: 10,
      source: 'Source 9',
    }));
    expect(screen.queryByText('chunk-context-9')).not.toBeInTheDocument();
  });

  it('does not render diagnostic context as standalone evidence controls', () => {
    const onSelectEvidence = vi.fn();
    render(
      <MemoryRouter>
        <MessageRenderer
          projectId="project-1"
          onSelectEvidence={onSelectEvidence}
          message={{
            id: 'assistant-context-snippet',
            role: 'assistant',
            content: '参考片段已经用于回答。',
            metadata: {
              diagnostics: {
                context: {
                  chunkCount: 1,
                  sourceCount: 1,
                  chunks: [
                    {
                      index: 1,
                      source: 'Zhang 2019',
                      content: 'Laser welding generally lowers porosity.',
                      relevance_score: 1,
                      chunk_id: 'chunk-context-1',
                      material_id: 'material-context-1',
                      page: 5,
                    },
                  ],
                },
              },
            },
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('button', { name: /1 个参考片段/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /打开片段 1/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Zhang 2019')).not.toBeInTheDocument();
    expect(onSelectEvidence).not.toHaveBeenCalled();
    expect(screen.queryByText('chunk-context-1')).not.toBeInTheDocument();
  });

  it('does not render legacy analysis-chain summaries in chat answers', () => {
    renderMessage({
      id: 'assistant-analysis-chain-hidden',
      role: 'assistant',
      content: '这是面向用户的回答正文。',
      analysis_chain: {
        observation: '内部观察摘要',
        evidence: [
          '[1] source=Zhang 2019.pdf; chunk_id=chunk-chain-1; material_id=material-chain-1; section=正文; page=5',
        ],
      },
    });

    expect(screen.getByText('这是面向用户的回答正文。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /证据化推理摘要/ })).not.toBeInTheDocument();
    expect(screen.queryByText('内部观察摘要')).not.toBeInTheDocument();
    expect(screen.queryByText(/chunk-chain-1/)).not.toBeInTheDocument();
  });

  it('wraps markdown tables in a horizontal scroll region', () => {
    renderMessage({
      id: 'assistant-wide-table',
      role: 'assistant',
      content: [
        '| 文献来源 | 激光功率 | 焊接速度 | 离焦量 | 保护气 | 外观判断 |',
        '| --- | --- | --- | --- | --- | --- |',
        '| Zhang 等 (2019) | 4 kW | 6.5 m/min | 0 mm | Ar | 表面连续，无明显塌陷 |',
      ].join('\n'),
    });

    const tableRegion = screen.getByRole('region', { name: '可横向滚动的表格' });
    expect(tableRegion).toHaveClass('overflow-x-auto');
    expect(tableRegion).toHaveClass('w-full');
    expect(tableRegion).toHaveClass('min-w-0');
    expect(within(tableRegion).getByRole('table')).toHaveClass('w-max');
    expect(within(tableRegion).getByRole('table')).toHaveClass('min-w-full');
  });

  it('keeps a single related figure collapsed until the user expands it', () => {
    renderMessage({
      id: 'assistant-related-figure',
      role: 'assistant',
      content: '可疑似查看 Fig. 4 的外观图块。',
      relatedFigures: [
        {
          id: 'figure-4',
          kind: 'figure',
          label: '图 4',
          caption: 'Weld appearance after laser processing.',
          material_id: 'material-1',
          material_title: 'Li 2023 AlSi10Mg laser welding',
          page: 9,
          chunk_id: 'chunk-33',
          asset_path: 'figures/material-1/figure-4.png',
          source: 'chunk_image_paths',
        },
      ],
    }, { projectId: 'project-1' });

    const disclosure = screen.getByRole('button', { name: '相关图表 1 项' });
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('img', { name: /图 4 Weld appearance/i })).not.toBeInTheDocument();
    expect(screen.queryByText('图 4')).not.toBeInTheDocument();

    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    const figureGrid = document.getElementById(disclosure.getAttribute('aria-controls') ?? '');
    if (!(figureGrid instanceof HTMLElement)) {
      throw new Error('Expected the expanded related-figure grid.');
    }
    expect(figureGrid).toHaveClass('[grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]');
    expect(figureGrid).not.toHaveClass('xl:grid-cols-3');
    expect(screen.getByText('图 4')).toBeInTheDocument();
    expect(screen.getByText('p.9')).toBeInTheDocument();
    expect(screen.getByText('图像资产')).toBeInTheDocument();
  });

  it('replaces a matching markdown image with a collapsed disclosure at that answer position', () => {
    renderMessage({
      id: 'assistant-inline-markdown-figure',
      role: 'assistant',
      content: [
        '孔隙随热输入变化，下面给出对应显微图。',
        '',
        '![Fig. 4](figure_assets/material-1/figure-4.png)',
        '',
        '焊接速度还会改变熔池稳定性。',
      ].join('\n'),
      relatedFigures: [
        {
          id: 'figure-4',
          kind: 'figure',
          label: '图 4',
          caption: 'Porosity under different heat inputs.',
          material_id: 'material-1',
          page: 9,
          chunk_id: 'chunk-33',
          asset_path: 'figure_assets/material-1/figure-4.png',
          source: 'chunk_image_paths',
        },
      ],
    }, { projectId: 'project-1' });

    const disclosure = screen.getByRole('button', { name: '相关图表 1 项' });
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('img', { name: 'Fig. 4' })).not.toBeInTheDocument();
    expect(disclosure.closest('[data-answer-block-index]')).toHaveAttribute('data-answer-block-index', '1');

    fireEvent.click(disclosure);
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Porosity under different heat inputs.')).toBeInTheDocument();
  });

  it('places independent figure disclosures beside the paragraph supported by each citation', () => {
    renderMessage({
      id: 'assistant-paragraph-figures',
      role: 'assistant',
      content: '孔隙随热输入变化。[1]\n\n焊接速度会改变熔池稳定性。[2]',
      evidence: [
        { chunk_id: 'anchor-porosity', evidence_id: 'anchor-porosity', source: 'Paper A' },
        { chunk_id: 'anchor-speed', evidence_id: 'anchor-speed', source: 'Paper A' },
      ],
      relatedFigures: [
        {
          id: 'figure-porosity',
          kind: 'figure',
          label: '图 4',
          caption: 'Porosity under different heat inputs.',
          material_id: 'material-1',
          chunk_id: 'figure-chunk-4',
          anchor_chunk_id: 'anchor-porosity',
          asset_path: 'figures/material-1/figure-4.png',
        },
        {
          id: 'figure-speed',
          kind: 'figure',
          label: '图 8',
          caption: 'Molten pool response at different welding speeds.',
          material_id: 'material-1',
          chunk_id: 'figure-chunk-8',
          anchor_chunk_id: 'anchor-speed',
          asset_path: 'figures/material-1/figure-8.png',
        },
      ],
    }, { projectId: 'project-1' });

    const disclosures = screen.getAllByRole('button', { name: '相关图表 1 项' });
    expect(disclosures).toHaveLength(2);
    expect(screen.getByText(/孔隙随热输入变化/).closest('[data-answer-block-index]')).toContainElement(disclosures[0]);
    expect(screen.getByText(/焊接速度会改变熔池稳定性/).closest('[data-answer-block-index]')).toContainElement(disclosures[1]);

    fireEvent.click(disclosures[0]);
    expect(disclosures[0]).toHaveAttribute('aria-expanded', 'true');
    expect(disclosures[1]).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Porosity under different heat inputs.')).toBeInTheDocument();
    expect(screen.queryByText('Molten pool response at different welding speeds.')).not.toBeInTheDocument();
  });

  it('places English and Chinese formula locators beside their matching answer paragraphs', () => {
    renderMessage({
      id: 'assistant-formula-locators',
      role: 'assistant',
      content: [
        '第一项由 Equation 1 定义。',
        '',
        '第二项见 Eq. 2。',
        '',
        '第三项按公式 3。',
        '',
        '第四项遵循方程 4。',
      ].join('\n'),
      relatedFigures: [
        {
          id: 'equation-1',
          kind: 'formula',
          label: 'Equation 1',
          caption: 'Balance relation A.',
          material_id: 'material-formulas',
          chunk_id: 'equation-chunk-1',
          asset_path: 'figures/material-formulas/equation-1.png',
        },
        {
          id: 'equation-2',
          kind: 'formula',
          label: 'Eq. 2',
          caption: 'Balance relation B.',
          material_id: 'material-formulas',
          chunk_id: 'equation-chunk-2',
          asset_path: 'figures/material-formulas/equation-2.png',
        },
        {
          id: 'formula-3',
          kind: 'formula',
          label: '公式 3',
          caption: 'Balance relation C.',
          material_id: 'material-formulas',
          chunk_id: 'formula-chunk-3',
          asset_path: 'figures/material-formulas/formula-3.png',
        },
        {
          id: 'equation-4',
          kind: 'formula',
          label: '方程 4',
          caption: 'Balance relation D.',
          material_id: 'material-formulas',
          chunk_id: 'equation-chunk-4',
          asset_path: 'figures/material-formulas/equation-4.png',
        },
      ],
    }, { projectId: 'project-1' });

    const disclosures = screen.getAllByRole('button', { name: '相关图表 1 项' });
    expect(disclosures).toHaveLength(4);
    expect(screen.getByText(/第一项由 Equation 1 定义/).closest('[data-answer-block-index]')).toContainElement(disclosures[0]);
    expect(screen.getByText(/第二项见 Eq\. 2/).closest('[data-answer-block-index]')).toContainElement(disclosures[1]);
    expect(screen.getByText(/第三项按公式 3/).closest('[data-answer-block-index]')).toContainElement(disclosures[2]);
    expect(screen.getByText(/第四项遵循方程 4/).closest('[data-answer-block-index]')).toContainElement(disclosures[3]);
  });

  it('does not force a cross-material visual candidate into a cited paragraph', () => {
    renderMessage({
      id: 'assistant-cross-material-figure',
      role: 'assistant',
      content: '较高焊接速度会缩短气孔生长时间。[1]',
      evidence: [
        {
          chunk_id: 'sun-porosity-anchor',
          evidence_id: 'sun-porosity-anchor',
          material_id: 'material-sun',
          source: 'Sun 2022',
        },
      ],
      relatedFigures: [
        {
          id: 'unrelated-fsw-figure',
          kind: 'figure',
          label: '图 21',
          caption: 'Failure path following tensile testing of a friction stir weld.',
          material_id: 'material-fsw',
          chunk_id: 'fsw-figure-21',
          anchor_chunk_id: 'sun-porosity-anchor',
          asset_path: 'figures/material-fsw/figure-21.png',
        },
      ],
    }, { projectId: 'project-1' });

    expect(screen.queryByRole('button', { name: /相关图表/ })).not.toBeInTheDocument();
  });

  it('disambiguates duplicate figure numbers from the surrounding answer text', () => {
    renderMessage({
      id: 'assistant-duplicate-figure-number',
      role: 'assistant',
      content: [
        '**Fig. 7 (Ping et al., 2026)** directly shows pores and the joint fracture location.',
        '',
        '> Figure 7. Weld surface morphology, pores, joint fracture location, and fracture-site microstructure.',
      ].join('\n'),
      relatedFigures: [
        {
          id: 'ping-figure-7',
          kind: 'figure',
          label: '图 7',
          caption: 'Figure 7. Weld surface morphology, pores, joint fracture location, and fracture-site microstructure.',
          material_id: 'material-ping',
          material_title: 'Ping et al. 2026 oscillating laser welding',
          chunk_id: 'ping-figure-7-chunk',
          asset_path: 'figures/material-ping/figure-7.png',
        },
        {
          id: 'sun-figure-7',
          kind: 'figure',
          label: '图 7',
          caption: 'Figure 7. Schematic evolution of weld porosity at different power ratios.',
          material_id: 'material-sun',
          material_title: 'Sun et al. 2022 adjustable ring mode laser welding',
          chunk_id: 'sun-figure-7-chunk',
          asset_path: 'figures/material-sun/figure-7.png',
        },
      ],
    }, { projectId: 'project-1' });

    const disclosure = screen.getByRole('button', { name: '相关图表 1 项' });
    fireEvent.click(disclosure);
    const disclosurePanel = disclosure.closest('[data-related-figure-disclosure]');
    if (!(disclosurePanel instanceof HTMLElement)) {
      throw new Error('Expected a related-figure disclosure container.');
    }

    expect(
      within(disclosurePanel).getByText(/Weld surface morphology, pores, joint fracture location/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Schematic evolution of weld porosity/)).not.toBeInTheDocument();
  });

  it('does not lexically pile other figures onto a paragraph with an explicit figure number', () => {
    renderMessage({
      id: 'assistant-explicit-figure-does-not-absorb-neighbours',
      role: 'assistant',
      content: 'Fig. 4 compares SLM and casting AlSi10Mg weld cross sections, dimensions, and porosity.',
      relatedFigures: [
        {
          id: 'cui-figure-4',
          kind: 'figure',
          label: '图 4',
          caption: 'Fig. 4. Cross sections, weld dimensions, and porosity of SLM and casting AlSi10Mg alloys.',
          material_id: 'material-cui',
          material_title: 'Cui et al. 2022 laser welding of AlSi10Mg',
          chunk_id: 'cui-figure-4-chunk',
          asset_path: 'figures/material-cui/figure-4.png',
        },
        {
          id: 'cui-figure-2',
          kind: 'figure',
          label: '图 2',
          caption: 'Fig. 2. Schematic diagram of autogenous, single-pass, and LMD welding processes.',
          material_id: 'material-cui',
          material_title: 'Cui et al. 2022 laser welding of AlSi10Mg',
          chunk_id: 'cui-figure-2-chunk',
          asset_path: 'figures/material-cui/figure-2.png',
        },
        {
          id: 'cui-figure-10',
          kind: 'figure',
          label: '图 10',
          caption: 'Fig. 10. Microstructures of laser welded joints in SLM and casting AlSi10Mg alloys.',
          material_id: 'material-cui',
          material_title: 'Cui et al. 2022 laser welding of AlSi10Mg',
          chunk_id: 'cui-figure-10-chunk',
          asset_path: 'figures/material-cui/figure-10.png',
        },
      ],
    }, { projectId: 'project-1' });

    expect(screen.getByRole('button', { name: '相关图表 1 项' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '相关图表 2 项' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '相关图表 3 项' })).not.toBeInTheDocument();
  });

  it('does not treat a shared publication year plus a generic topic word as visual relevance', () => {
    renderMessage({
      id: 'assistant-year-is-not-visual-relevance',
      role: 'assistant',
      content: 'Sun et al. (2022) studied how power ratio and welding speed affect porosity.',
      relatedFigures: [
        {
          id: 'unrelated-2022-porosity-figure',
          kind: 'figure',
          label: '图 18',
          caption: 'Fig. 18. Porosity morphology on the fracture surface.',
          material_id: 'material-cui',
          material_title: 'Cui et al. 2022 fracture study',
          chunk_id: 'cui-figure-18-chunk',
          asset_path: 'figures/material-cui/figure-18.png',
        },
      ],
    }, { projectId: 'project-1' });

    expect(screen.queryByRole('button', { name: /相关图表/ })).not.toBeInTheDocument();
  });

  it('omits visual candidates with no citation, figure-number, or lexical relationship', () => {
    renderMessage({
      id: 'assistant-unrelated-visual-candidate',
      role: 'assistant',
      content: '较高焊接速度会缩短激光与材料的相互作用时间。',
      relatedFigures: [
        {
          id: 'unrelated-gyroid-figure',
          kind: 'figure',
          label: '图 4',
          caption: 'Morphological reconstruction of a hybrid gyroid-diamond lattice.',
          material_id: 'material-gyroid',
          chunk_id: 'gyroid-figure-4',
          asset_path: 'figures/material-gyroid/figure-4.png',
        },
      ],
    }, { projectId: 'project-1' });

    expect(screen.queryByRole('button', { name: /相关图表/ })).not.toBeInTheDocument();
  });

  it('does not use lexical fallback for a visual from outside the answer evidence materials', () => {
    renderMessage({
      id: 'assistant-cross-material-lexical-visual',
      role: 'assistant',
      content: '孔隙形貌和显微组织共同反映激光焊接接头的质量变化。',
      evidence: [
        {
          chunk_id: 'cui-narrative-anchor',
          evidence_id: 'cui-narrative-anchor',
          material_id: 'material-cui',
          source: 'Cui 2022',
        },
      ],
      relatedFigures: [
        {
          id: 'han-generic-porosity-figure',
          kind: 'figure',
          label: '图 6',
          caption: '激光焊接接头的孔隙形貌和显微组织。',
          material_id: 'material-han',
          material_title: 'Han thesis',
          chunk_id: 'han-figure-6-chunk',
          asset_path: 'figures/material-han/figure-6.png',
        },
      ],
    }, { projectId: 'project-1' });

    expect(screen.queryByRole('button', { name: /相关图表/ })).not.toBeInTheDocument();
  });

  it('renders protected related figure assets through a fetched blob URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi.fn().mockResolvedValue(new Blob(['image-bytes'], { type: 'image/png' })),
    });
    const createObjectURL = vi.fn().mockReturnValue('blob:related-figure');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });

    render(
      <MemoryRouter>
        <MessageRenderer
          projectId="project-1"
          message={{
            id: 'assistant-related-protected-figure',
            role: 'assistant',
            content: '可查看图 4 的外观图块。',
            relatedFigures: [
              {
                id: 'figure-4',
                kind: 'figure',
                label: '图 4',
                caption: 'Weld appearance after laser processing.',
                material_id: 'material-1',
                material_title: 'Li 2023 AlSi10Mg laser welding',
                page: 9,
                chunk_id: 'chunk-33',
                asset_path: 'figures/material-1/figure-4.png',
                source: 'chunk_image_paths',
              },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(fetchMock).not.toHaveBeenCalled();
    const disclosure = screen.getByRole('button', { name: '相关图表 1 项' });
    fireEvent.click(disclosure);
    const image = await screen.findByRole('img', { name: /图 4 Weld appearance/i });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/writing/figures/file?'));
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(image).toHaveAttribute('src', 'blob:related-figure');
  });

  it('opens a related visual card at its exact PDF region', async () => {
    render(
      <MemoryRouter>
        <MessageRenderer
          projectId="project-1"
          message={{
            id: 'assistant-related-visual-anchor',
            role: 'assistant',
            content: '图 4 展示了焊缝区域。',
            relatedFigures: [{
              id: 'figure-4-anchor',
              kind: 'figure',
              label: '图 4',
              caption: 'Weld appearance after laser processing.',
              material_id: 'material-1',
              material_title: 'Li 2023 AlSi10Mg laser welding',
              page: 9,
              bbox: [0.12, 0.24, 0.55, 0.31],
              bbox_unit: 'normalized_ratio',
              chunk_id: 'chunk-33',
              source: 'chunk_image_paths',
            }],
          }}
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '相关图表 1 项' }));
    fireEvent.click(await screen.findByRole('button', { name: '定位图 4' }));

    await waitFor(() => {
      const location = screen.getByTestId('location').textContent ?? '';
      const parsed = new URL(location, 'http://localhost');
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('material_id')).toBe('material-1');
      expect(parsed.searchParams.get('page')).toBe('9');
      expect(parsed.searchParams.get('bbox')).toBe('0.12,0.24,0.55,0.31');
      expect(parsed.searchParams.get('anchor_kind')).toBe('visual');
    });
  });
});
