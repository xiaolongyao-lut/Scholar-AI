import type { HTMLAttributes, ReactNode } from 'react';

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { CitationAnchor, DraftContent, WritingMaterial } from '@/types/writing';

import { ReferenceDrawer } from './ReferenceDrawer';

vi.mock('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
}));

const createMaterial = (overrides: Partial<WritingMaterial> = {}): WritingMaterial => ({
  id: 'material-1',
  titleZh: '默认资料',
  titleEn: 'Default Material',
  summaryZh: '默认摘要',
  summaryEn: 'Default Summary',
  type: 'paper',
  focusPointsZh: ['默认焦点'],
  focusPointsEn: ['Default Focus'],
  ...overrides,
});

const createDraft = (content: string): DraftContent => ({
  sectionId: 'section-1',
  content,
  wordCount: content.split(/\s+/).filter(Boolean).length,
  lastSavedAt: '2026-04-29T10:00:00Z',
  isDirty: false,
});

const buildAnchors = (
  content: string,
  seeds: Array<{ token: string; materialId: string | null; ordinal: number }>,
): CitationAnchor[] => {
  let searchStart = 0;

  return seeds.map(({ token, materialId, ordinal }) => {
    const startOffset = content.indexOf(token, searchStart);

    if (startOffset < 0) {
      throw new Error(`Token not found in content: ${token}`);
    }

    searchStart = startOffset + token.length;

    return {
      id: token.slice(2, -1),
      instanceId: `${token.slice(2, -1)}@${startOffset}`,
      materialId,
      token,
      startOffset,
      endOffset: startOffset + token.length,
      ordinal,
    };
  });
};

const renderReferenceDrawer = ({
  materials,
  draft,
  citationAnchors,
  citationCountByMaterial,
}: {
  materials: WritingMaterial[];
  draft: DraftContent;
  citationAnchors: CitationAnchor[];
  citationCountByMaterial: Record<string, number>;
}) => {
  render(
    <ReferenceDrawer
      isOpen
      onClose={vi.fn()}
      materials={materials}
      draft={draft}
      citationAnchors={citationAnchors}
      citationCountByMaterial={citationCountByMaterial}
      activeMaterialId={null}
      activeCitationAnchorInstanceId={null}
      activeSectionTitle="结果与讨论"
      onRequestCitationInsertion={vi.fn()}
      onRequestAnchorFocus={vi.fn()}
      onSelectMaterial={vi.fn()}
    />,
  );
};

describe('ReferenceDrawer', () => {
  it('surfaces evidence status badges and review warnings for weak, dangling, unbound, uncited, and dominant evidence', () => {
    const weakMaterial = createMaterial({
      id: 'paper-weak',
      titleZh: '弱证据论文',
      titleEn: 'Weak Evidence Paper',
      summaryZh: '',
      summaryEn: '',
      focusPointsZh: [],
      focusPointsEn: [],
    });
    const unusedMaterial = createMaterial({
      id: 'paper-unused',
      titleZh: '未引用资料',
      titleEn: 'Unused Material',
    });

    const weakTokenOne = '[^cite:paper-weak:a1b2c3]';
    const weakTokenTwo = '[^cite:paper-weak:d4e5f6]';
    const weakTokenThree = '[^cite:paper-weak:g7h8i9]';
    const danglingToken = '[^cite:paper-missing:j1k2l3]';
    const unboundToken = '[^cite:unbound:m4n5o6]';
    const uncitedParagraph = '这是一段需要补证据的长段落，用来模拟没有 source anchor 的章节内容。'.repeat(6);
    const citedParagraph = [
      '这一段集中使用同一条弱证据来支撑多个判断',
      weakTokenOne,
      '并继续追加第二个锚点',
      weakTokenTwo,
      '再追加第三个锚点',
      weakTokenThree,
      '同时包含一个悬挂引用',
      danglingToken,
      '以及一个未绑定资料的引用',
      unboundToken,
      '用于触发 focused review heuristics。',
    ].join(' ');
    const content = `${uncitedParagraph}\n\n${citedParagraph}`;
    const citationAnchors = buildAnchors(content, [
      { token: weakTokenOne, materialId: 'paper-weak', ordinal: 1 },
      { token: weakTokenTwo, materialId: 'paper-weak', ordinal: 2 },
      { token: weakTokenThree, materialId: 'paper-weak', ordinal: 3 },
      { token: danglingToken, materialId: 'paper-missing', ordinal: 4 },
      { token: unboundToken, materialId: null, ordinal: 5 },
    ]);

    renderReferenceDrawer({
      materials: [weakMaterial, unusedMaterial],
      draft: createDraft(content),
      citationAnchors,
      citationCountByMaterial: {
        'paper-weak': 3,
        'paper-unused': 0,
        'paper-missing': 1,
        __unbound__: 1,
      },
    });

    expect(screen.getByText('证据较弱')).toBeInTheDocument();
    expect(screen.getByText('尚未引用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /审计/i }));

    expect(screen.getByText('存在无引长段落')).toBeInTheDocument();
    expect(screen.getByText('存在未绑定资料的 anchor')).toBeInTheDocument();
    expect(screen.getByText('存在悬挂引用')).toBeInTheDocument();
    expect(screen.getByText('部分证据条目摘要较弱')).toBeInTheDocument();
    expect(screen.getByText('引用过度集中')).toBeInTheDocument();
  });

  it('reports a healthy review state when evidence coverage is balanced and bound', () => {
    const firstMaterial = createMaterial({
      id: 'paper-a',
      titleZh: '资料 A',
      titleEn: 'Material A',
    });
    const secondMaterial = createMaterial({
      id: 'paper-b',
      titleZh: '资料 B',
      titleEn: 'Material B',
    });
    const firstToken = '[^cite:paper-a:a1b2c3]';
    const secondToken = '[^cite:paper-b:d4e5f6]';
    const content = `这一段的论述由资料 A 支撑 ${firstToken}。\n\n另一段的论述由资料 B 支撑 ${secondToken}。`;
    const citationAnchors = buildAnchors(content, [
      { token: firstToken, materialId: 'paper-a', ordinal: 1 },
      { token: secondToken, materialId: 'paper-b', ordinal: 2 },
    ]);

    renderReferenceDrawer({
      materials: [firstMaterial, secondMaterial],
      draft: createDraft(content),
      citationAnchors,
      citationCountByMaterial: {
        'paper-a': 1,
        'paper-b': 1,
      },
    });

    fireEvent.click(screen.getByRole('button', { name: /审计/i }));

    expect(screen.getByText('当前 section 的证据面板健康')).toBeInTheDocument();
    expect(screen.queryByText('存在无引长段落')).not.toBeInTheDocument();
    expect(screen.queryByText('存在未绑定资料的 anchor')).not.toBeInTheDocument();
  });
});