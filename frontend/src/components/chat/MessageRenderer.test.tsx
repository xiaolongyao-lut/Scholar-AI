import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { MessageRenderer, type ChatMessageData } from './MessageRenderer';
import { formatChatVisibleError } from './chatDisplay';

function renderMessage(message: ChatMessageData) {
  return render(
    <MemoryRouter>
      <MessageRenderer message={message} />
    </MemoryRouter>,
  );
}

describe('MessageRenderer diagnostics', () => {
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

  it('renders expandable wiki and project joint recall diagnostics', () => {
    renderMessage({
      id: 'assistant-joint-recall',
      role: 'assistant',
      content: '证据包表明该机制有项目文献和 Wiki 沉淀共同支持。',
      metadata: {
        diagnostics: {
          retrieval: {
            retrieval_method: 'hybrid_rerank',
            embedding_status: 'active',
            rerank_status: 'active',
            joint_recall: {
              status: 'available',
              fusion: 'weighted_rrf',
              project_weight: 0.4,
              wiki_weight: 0.6,
              project_hit_count: 4,
              wiki_hit_count: 7,
              fused_count: 8,
              wiki_share_after_fusion: 0.625,
              max_wiki_share_after_fusion: 0.7,
              wiki_summaries: [
                {
                  title: 'AlSi10Mg 缺陷机理',
                  summary: '孔隙、熔池稳定性与疲劳裂纹萌生存在耦合。',
                  ref_id: 'wiki:synthesis/al-si-10-mg.md',
                  read_endpoint: '/api/agent-bridge/resource/wiki:synthesis/al-si-10-mg.md',
                },
              ],
            },
          },
        },
      },
    });

    const toggle = screen.getByRole('button', { name: /联合召回/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveTextContent('项目 4');
    expect(toggle).toHaveTextContent('Wiki 7');
    expect(toggle).toHaveTextContent('63%');

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('融合: weighted rrf')).toBeInTheDocument();
    expect(screen.getByText('权重: 项目 0.4 / Wiki 0.6')).toBeInTheDocument();
    expect(screen.getByText('AlSi10Mg 缺陷机理')).toBeInTheDocument();
    expect(screen.getByText('孔隙、熔池稳定性与疲劳裂纹萌生存在耦合。')).toBeInTheDocument();
    expect(screen.getByText('wiki:synthesis/al-si-10-mg.md')).toBeInTheDocument();
    expect(screen.getByText('hybrid rerank')).toBeInTheDocument();
  });

  it('hides unavailable joint recall diagnostics', () => {
    renderMessage({
      id: 'assistant-joint-recall-unavailable',
      role: 'assistant',
      content: '没有可用的 Wiki 联合召回。',
      metadata: {
        diagnostics: {
          retrieval: {
            retrieval_method: 'lexical',
            embedding_status: 'unavailable',
            rerank_status: 'unavailable',
            joint_recall: { status: 'unavailable' },
          },
        },
      },
    });

    expect(screen.queryByRole('button', { name: /联合召回/ })).not.toBeInTheDocument();
    expect(screen.getByText('lexical')).toBeInTheDocument();
  });

  it('renders candidate qrels as review-needed instead of semantic quality proof', () => {
    renderMessage({
      id: 'assistant-candidate-qrels',
      role: 'assistant',
      content: '检索命中了候选证据，但质量标签仍需人工复核。',
      metadata: {
        diagnostics: {
          retrieval: {
            retrieval_method: 'hybrid_rerank',
            embedding_status: 'active',
            rerank_status: 'active',
            qrels_status: {
              schema_version: 'retrieval-qrels-status/v1',
              status: 'candidate',
              candidate_qrels_count: 3,
              reviewed_qrels_count: 0,
              canonical_qrels_count: 0,
              semantic_quality_claim_allowed: false,
              quality_claim: 'candidate_qrels_review_required',
              notes: ['Candidate qrels require human review before semantic quality claims.'],
            },
          },
        },
      },
    });

    expect(screen.getByText('qrels 待复核')).toBeInTheDocument();
    expect(screen.getByText('候选 3')).toBeInTheDocument();
    expect(screen.queryByText('语义质量已验证')).not.toBeInTheDocument();
  });

  it('renders canonical qrels as the only verified retrieval quality state', () => {
    renderMessage({
      id: 'assistant-canonical-qrels',
      role: 'assistant',
      content: '检索质量已有 canonical qrels 支撑。',
      metadata: {
        diagnostics: {
          retrieval: {
            retrieval_method: 'hybrid_rerank',
            embedding_status: 'active',
            rerank_status: 'active',
            qrels_status: {
              schema_version: 'retrieval-qrels-status/v1',
              status: 'canonical',
              candidate_qrels_count: 0,
              reviewed_qrels_count: 0,
              canonical_qrels_count: 8,
              semantic_quality_claim_allowed: true,
              quality_claim: 'canonical_qrels_available',
              notes: ['Canonical qrels are available for offline retrieval-quality evaluation.'],
            },
          },
        },
      },
    });

    expect(screen.getByText('语义质量已验证')).toBeInTheDocument();
    expect(screen.getByText('canonical 8')).toBeInTheDocument();
  });

  it('renders lexical fallback and TOLF graph diagnostics', () => {
    renderMessage({
      id: 'assistant-retrieval-health',
      role: 'assistant',
      content: 'AlSi10Mg 激光焊接证据如下。',
      metadata: {
        diagnostics: {
          retrieval: {
            retrieval_method: 'tolf_gateway_fusion',
            embedding_status: 'lexical_only',
            lexical_only: true,
            fallback_reasons: ['dense_recall_missing_contract_or_embedding'],
            gateway: {
              dense_hit_count: 0,
              lexical_hit_count: 4,
              visual_hit_count: 1,
              candidate_count: 5,
              dense_enabled: false,
              chroma_status: 'unavailable',
              fts_status: 'valid',
            },
            tolf: {
              status: 'active',
              graph_node_count: 45,
              graph_edge_count: 96,
              gate_after_count: 6,
              activation_mean: 0.42,
              top_final_rank_score: 0.82,
              rank_contribution_keys: ['dense', 'lexical_exact', 'locator_quality', 'tolf_evidence'],
            },
          },
        },
      },
    });

    expect(screen.getByText('lexical-only fallback')).toBeInTheDocument();
    expect(screen.getByText('0 / 4 / 1 命中')).toBeInTheDocument();
    expect(screen.getByText('TOLF 45 节点 · 96 边 · gate 6')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /检索状态/ }));

    expect(screen.getByText('当前回答进入 lexical-only fallback。')).toBeInTheDocument();
    expect(screen.getByText('图: 45 节点 / 96 边')).toBeInTheDocument();
    expect(screen.getByText(/dense recall missing contract or embedding/)).toBeInTheDocument();
  });

  it('renders mixed project and wiki evidence refs without leaking bounded source paths', () => {
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

    expect(screen.getByRole('button', { name: /项目论文 A/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /AlSi10Mg Wiki 综述/ })).toBeInTheDocument();
    expect(screen.getByText('Wiki')).toBeInTheDocument();
    expect(screen.getByLabelText('融合分: 0.03')).toBeInTheDocument();
    expect(screen.getByLabelText('融合分: 0.010')).toBeInTheDocument();
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

  it('labels chunk image assets for related figure candidates', () => {
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
    });

    expect(screen.getByText('相关图像/图表候选')).toBeInTheDocument();
    expect(screen.getByText('图 4')).toBeInTheDocument();
    expect(screen.getByText('p.9')).toBeInTheDocument();
    expect(screen.getByText('图像资产')).toBeInTheDocument();
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

    const image = await screen.findByRole('img', { name: /图 4 Weld appearance/i });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/writing/figures/file?'));
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(image).toHaveAttribute('src', 'blob:related-figure');
  });
});
