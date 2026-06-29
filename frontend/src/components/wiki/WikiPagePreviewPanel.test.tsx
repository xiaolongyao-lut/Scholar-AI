import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WikiPagePreviewPanel } from './WikiPagePreviewPanel';
import type { WikiPageDetailModel } from '@/types/wiki';

function wikiPageFixture(): WikiPageDetailModel {
  return {
    enabled: true,
    path: 'claims/tagged-page.md',
    frontmatter: {
      id: 'claim-tagged-page',
      title: 'Tagged Wiki Claim',
      kind: 'claim',
      status: 'final',
      tags: ['fatigue', 'porosity'],
      labels: 'AM, evidence-backed',
      source_ids: ['source-a', 'source-b'],
      evidence_refs: [
        {
          material_id: 'mat-sensitive-a',
          chunk_id: 'chunk-sensitive-a',
          page: 4,
          bbox: [0.1, 0.2, 0.3, 0.1],
          quote: 'Do not expose this quote in the attributes panel.',
        },
        { chunk_id: 'chunk-sensitive-b', quote: 'Do not expose this quote either.' },
      ],
    },
    body: '# Tagged Wiki Claim\n\nThe public body remains readable.',
  };
}

describe('WikiPagePreviewPanel', () => {
  it('renders page tags and structured summaries without exposing raw frontmatter objects', () => {
    render(
      <WikiPagePreviewPanel
        selectedPath="claims/tagged-page.md"
        page={wikiPageFixture()}
        isLoading={false}
        error={null}
        onRefresh={vi.fn()}
      />,
    );

    const attributes = within(screen.getByRole('heading', { name: '页面属性' }).closest('div')!.parentElement!);
    expect(attributes.getByText('Tagged Wiki Claim')).toBeInTheDocument();
    expect(attributes.getByText('断言')).toBeInTheDocument();
    expect(attributes.getByText('已定稿')).toBeInTheDocument();
    expect(attributes.getByText('2 项')).toBeInTheDocument();
    expect(attributes.getByText('2 条')).toBeInTheDocument();
    expect(attributes.getByText('fatigue')).toBeInTheDocument();
    expect(attributes.getByText('porosity')).toBeInTheDocument();
    expect(attributes.getByText('AM')).toBeInTheDocument();
    expect(attributes.getByText('evidence-backed')).toBeInTheDocument();
    expect(attributes.queryByText(/chunk-sensitive-a/)).toBeNull();
    expect(attributes.queryByText(/Do not expose this quote/)).toBeNull();
  });

  it('renders PDF evidence anchors as source links without exposing raw ids', () => {
    render(
      <WikiPagePreviewPanel
        selectedPath="claims/tagged-page.md"
        page={wikiPageFixture()}
        isLoading={false}
        error={null}
        onRefresh={vi.fn()}
      />,
    );

    const anchors = screen.getByLabelText('PDF 证据定位');
    const link = within(anchors).getByRole('link', { name: /打开原文 p\.4/ });
    expect(link).toHaveAttribute(
      'href',
      '/dialog?scope=paper&material_id=mat-sensitive-a&tab=reader&page=4&chunk=chunk-sensitive-a&bbox=0.1%2C0.2%2C0.3%2C0.1',
    );
    expect(anchors).not.toHaveTextContent('mat-sensitive-a');
    expect(anchors).not.toHaveTextContent('chunk-sensitive-a');
    expect(anchors).not.toHaveTextContent('Do not expose this quote');
  });
});
