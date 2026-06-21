import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { MessageRenderer, type ChatMessageData } from './MessageRenderer';

function renderMessage(message: ChatMessageData) {
  return render(
    <MemoryRouter>
      <MessageRenderer message={message} />
    </MemoryRouter>,
  );
}

describe('MessageRenderer diagnostics', () => {
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
});
