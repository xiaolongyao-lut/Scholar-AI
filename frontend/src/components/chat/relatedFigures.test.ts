import { describe, expect, it } from 'vitest';

import { relatedFiguresFromEvidenceRefs } from './relatedFigures';

describe('relatedFiguresFromEvidenceRefs', () => {
  it('preserves a nested visual locator when the evidence ref has no top-level locator', () => {
    expect(relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-caption',
      source: 'Paper with a figure',
      quote: 'Figure 4 shows the measured surface.',
      figure_candidate: 'Figure 4',
      figure_candidate_detail: {
        id: 'figure-4',
        kind: 'figure',
        page: 7,
        bbox: [0.12, 0.24, 0.55, 0.31],
        bbox_unit: 'normalized_ratio',
      },
      image_paths: ['figures/material-figure/figure-4.png'],
    }])).toEqual([
      expect.objectContaining({
        material_id: 'material-figure',
        chunk_id: 'chunk-caption',
        page: 7,
        bbox: [0.12, 0.24, 0.55, 0.31],
        bbox_unit: 'normalized_ratio',
        quote: 'Figure 4 shows the measured surface.',
      }),
    ]);
  });

  it('prefers a valid top-level locator over nested candidate metadata', () => {
    const [figure] = relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-caption',
      source: 'Paper with a figure',
      page: 9,
      bbox: [0.2, 0.3, 0.4, 0.2],
      bbox_unit: 'normalized_ratio',
      figure_candidate_detail: {
        id: 'figure-4',
        page: 7,
        bbox: [0.12, 0.24, 0.55, 0.31],
        bbox_unit: 'normalized_ratio',
      },
      image_paths: ['figures/material-figure/figure-4.png'],
    }]);

    expect(figure).toMatchObject({
      page: 9,
      bbox: [0.2, 0.3, 0.4, 0.2],
      bbox_unit: 'normalized_ratio',
    });
  });

  it('keeps a nested bbox paired with its nested page', () => {
    const [figure] = relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-caption',
      page: 9,
      figure_candidate_detail: {
        id: 'figure-4',
        page: 7,
        bbox: [0.12, 0.24, 0.55, 0.31],
        bbox_unit: 'normalized_ratio',
      },
      image_paths: ['figures/material-figure/figure-4.png'],
    }]);

    expect(figure).toMatchObject({
      page: 7,
      bbox: [0.12, 0.24, 0.55, 0.31],
      bbox_unit: 'normalized_ratio',
    });
  });

  it('does not combine a top-level bbox with a nested-only page', () => {
    const [figure] = relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-caption',
      bbox: [0.2, 0.3, 0.4, 0.2],
      bbox_unit: 'normalized_ratio',
      figure_candidate_detail: {
        id: 'figure-4',
        page: 7,
      },
      image_paths: ['figures/material-figure/figure-4.png'],
    }]);

    expect(figure).toMatchObject({
      page: 7,
      bbox: null,
      bbox_unit: null,
    });
  });

  it('drops visual geometry when bbox_unit is missing', () => {
    const [figure] = relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-unitless',
      page: 4,
      bbox: [0.2, 0.3, 0.4, 0.2],
      image_paths: ['figures/material-figure/unitless.png'],
    }]);

    expect(figure).toMatchObject({
      page: 4,
      bbox: null,
      bbox_unit: null,
    });
  });

  it('does not relabel pdf_points geometry as normalized_ratio', () => {
    const [figure] = relatedFiguresFromEvidenceRefs([{
      material_id: 'material-figure',
      chunk_id: 'chunk-pdf-points',
      page: 5,
      bbox: [72, 144, 180, 36],
      bbox_unit: 'pdf_points',
      image_paths: ['figures/material-figure/pdf-points.png'],
    }]);

    expect(figure).toMatchObject({
      page: 5,
      bbox: null,
      bbox_unit: null,
    });
  });
});
