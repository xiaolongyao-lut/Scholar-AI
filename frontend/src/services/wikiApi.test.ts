import { describe, expect, it } from 'vitest';

import {
  WikiApiError,
  extractCitationWarnings,
  parseWikiCompileDryRun,
  parseWikiDoctor,
  parseWikiGraph,
  parseWikiImport,
  parseWikiPageDetail,
  parseWikiPageList,
  parseWikiReviewList,
  parseWikiStatus,
} from '@/services/wikiApi';

describe('wikiApi.parseWikiImport', () => {
  it('preserves bounded evidence locator fields returned by local markdown imports', () => {
    const parsed = parseWikiImport({
      enabled: true,
      dry_run: false,
      confirm_write: true,
      imported: 1,
      skipped: 0,
      errored: 0,
      pages: [
        {
          source_path: 'notes/local-source.md',
          import_source_hash: 'a'.repeat(64),
          source_hash: 'b'.repeat(64),
          content_hash: 'c'.repeat(64),
          ref_id: 'wiki:synthesis/synthesis-local-source.md',
          chunk_id: 'wiki:synthesis/synthesis-local-source.md#chunk-0',
          read_endpoint: '/api/agent-bridge/resource/wiki:synthesis/synthesis-local-source.md',
          span_start: 0,
          span_end: 128,
          title: 'Local Source',
          kind: 'synthesis',
          status: 'draft',
          slug: 'synthesis-local-source',
          path: 'synthesis/synthesis-local-source.md',
          action: 'created',
          review_item_id: 'import-synthesis-local-source',
          runtime_session_id: 'session_1',
          runtime_job_id: 'job_1',
          runtime_approval_id: 'approval_1',
          warnings: [],
          error: '',
        },
      ],
      warnings: [],
    });

    expect(parsed.pages[0].ref_id).toBe('wiki:synthesis/synthesis-local-source.md');
    expect(parsed.pages[0].chunk_id).toBe('wiki:synthesis/synthesis-local-source.md#chunk-0');
    expect(parsed.pages[0].read_endpoint).toBe('/api/agent-bridge/resource/wiki:synthesis/synthesis-local-source.md');
    expect(parsed.pages[0].import_source_hash).toBe('a'.repeat(64));
    expect(parsed.pages[0].source_hash).toBe('b'.repeat(64));
    expect(parsed.pages[0].content_hash).toBe('c'.repeat(64));
    expect(parsed.pages[0].span_start).toBe(0);
    expect(parsed.pages[0].span_end).toBe(128);
  });
});

describe('wikiApi.parseWikiStatus', () => {
  it('accepts the backend wiki status contract', () => {
    const parsed = parseWikiStatus({
      enabled: false,
      page_count: 0,
      stale: false,
      integrity_status: 'disabled',
      index_hash: 'none',
      source_manifest_hash: 'unknown',
      indexed_source_manifest_hash: 'unknown',
      indexed_page_count: 0,
      source_page_count: null,
      graph_json_exists: false,
      graph_db_exists: false,
      query_index_exists: false,
      review_queue_exists: false,
      paths: {
        wiki_root: 'C:\\wiki',
        graph_json: 'C:\\wiki\\graph.json',
      },
      warnings: ['Wiki integration is disabled.'],
      manifest_drilldown: {
        schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
        status: 'disabled',
        hash_algorithm: 'sha256',
        limit: 10,
        missing_count: 0,
        extra_count: 0,
        mismatched_count: 0,
        truncated: false,
        missing_pages: [],
        extra_pages: [],
        mismatched_pages: [],
      },
    });

    expect(parsed.stale).toBe(false);
    expect(parsed.integrity_status).toBe('disabled');
    expect(parsed.source_page_count).toBeNull();
    expect(parsed.paths.wiki_root).toBe('C:\\wiki');
    expect(parsed.manifest_drilldown.status).toBe('disabled');
  });

  it('rejects malformed warnings payloads', () => {
    expect(() =>
      parseWikiStatus({
        enabled: true,
        page_count: 1,
        stale: false,
        integrity_status: 'aligned',
        index_hash: 'abc',
        source_manifest_hash: 'source',
        indexed_source_manifest_hash: 'source',
        indexed_page_count: 1,
        source_page_count: 1,
        graph_json_exists: true,
        graph_db_exists: true,
        query_index_exists: true,
        review_queue_exists: true,
        paths: { wiki_root: 'C:\\wiki' },
        warnings: [1],
      })
    ).toThrowError(WikiApiError);
  });

  it('treats omitted source page count as unknown for generated-client compatibility', () => {
    const parsed = parseWikiStatus({
      enabled: true,
      page_count: 1,
      stale: false,
      integrity_status: 'indexed_manifest_recorded',
      index_hash: 'abc',
      source_manifest_hash: 'source',
      indexed_source_manifest_hash: 'source',
      indexed_page_count: 1,
      graph_json_exists: true,
      graph_db_exists: true,
      query_index_exists: true,
      review_queue_exists: true,
      paths: { wiki_root: 'C:\\wiki' },
      warnings: [],
    });

    expect(parsed.source_page_count).toBeNull();
    expect(parsed.manifest_drilldown.status).toBe('unknown');
  });

  it('parses bounded page-level manifest drilldown samples', () => {
    const parsed = parseWikiStatus({
      enabled: true,
      page_count: 3,
      stale: true,
      integrity_status: 'source_hash_mismatch',
      index_hash: 'abc',
      source_manifest_hash: 'source',
      indexed_source_manifest_hash: 'indexed',
      indexed_page_count: 3,
      source_page_count: 3,
      graph_json_exists: true,
      graph_db_exists: true,
      query_index_exists: true,
      review_queue_exists: true,
      paths: { wiki_root: 'C:\\wiki' },
      warnings: [],
      manifest_drilldown: {
        schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
        status: 'source_hash_mismatch',
        hash_algorithm: 'sha256',
        limit: 10,
        missing_count: 1,
        extra_count: 1,
        mismatched_count: 1,
        truncated: false,
        missing_pages: [
          {
            kind: 'missing',
            page_path: 'concepts/d.md',
            source_hash: 'a'.repeat(64),
            indexed_hash: null,
            redacted: false,
          },
        ],
        extra_pages: [
          {
            kind: 'extra',
            page_path: '<redacted>',
            source_hash: null,
            indexed_hash: null,
            redacted: true,
          },
        ],
        mismatched_pages: [
          {
            kind: 'mismatched',
            page_path: 'concepts/a.md',
            source_hash: 'b'.repeat(64),
            indexed_hash: 'c'.repeat(64),
            redacted: false,
          },
        ],
      },
    });

    expect(parsed.manifest_drilldown.missing_pages[0].page_path).toBe('concepts/d.md');
    expect(parsed.manifest_drilldown.extra_pages[0].redacted).toBe(true);
    expect(parsed.manifest_drilldown.mismatched_count).toBe(1);
  });
});

describe('wikiApi.parseWikiPageList', () => {
  it('accepts page summaries for the read-only list panel', () => {
    const parsed = parseWikiPageList({
      enabled: true,
      pages: [
        { path: 'concepts/alpha.md', title: 'Alpha', kind: 'concept', status: 'draft' },
      ],
    });

    expect(parsed.pages[0].title).toBe('Alpha');
    expect(parsed.pages[0].kind).toBe('concept');
  });
});

describe('wikiApi.parseWikiDoctor', () => {
  it('extracts structured doctor checks when the report shape matches the backend contract', () => {
    const parsed = parseWikiDoctor({
      enabled: true,
      report: {
        ok: false,
        status: 'warning',
        counts: { ok: 2, warning: 1, error: 0 },
        checks: [
          {
            id: 'retrieval',
            label: 'Retrieval',
            status: 'warning',
            summary: 'Index is stale.',
            detail: 'page mismatch',
            metrics: { indexed_pages: 1 },
            actions: [
              {
                command: 'wiki query-index rebuild',
                description: 'Rebuild wiki FTS query index.',
                safe_auto_repair: true,
              },
            ],
          },
        ],
      },
    });

    expect(parsed.structuredReport?.status).toBe('warning');
    expect(parsed.structuredReport?.checks[0].actions[0].safe_auto_repair).toBe(true);
  });
});

describe('wikiApi.parseWikiReviewList', () => {
  it('accepts review queue items for the read-only queue panel', () => {
    const parsed = parseWikiReviewList({
      enabled: true,
      items: [
        {
          item_id: 'draft-1',
          kind: 'draft',
          title: 'Draft 1',
          page_path: 'concepts/draft-1.md',
          summary: 'Needs review.',
          status: 'pending',
          created_at: '2026-05-04T10:00:00Z',
          source: 'wiki',
          metadata: { hash: 'abc' },
          decision: null,
        },
      ],
    });

    expect(parsed.items[0].metadata.hash).toBe('abc');
    expect(parsed.items[0].status).toBe('pending');
  });
});

describe('wikiApi.parseWikiGraph', () => {
  it('extracts a structured graph snapshot when node and edge arrays are present', () => {
    const parsed = parseWikiGraph({
      enabled: true,
      graph: {
        schema_version: 1,
        updated_at: '2026-05-04T10:00:00Z',
        node_count: 1,
        edge_count: 1,
        nodes: [
          {
            node_id: 'concepts/alpha',
            page_path: 'concepts/alpha.md',
            kind: 'concept',
            title: 'Alpha',
            status: 'draft',
            content_hash: 'hash-1',
            frontmatter_id: 'concepts/alpha',
            metadata: {},
          },
        ],
        edges: [
          {
            edge_id: 'edge-1',
            source_id: 'concepts/alpha',
            target_id: 'concepts/beta',
            edge_type: 'wikilink',
            weight: 0.5,
            confidence: 'medium',
            evidence: '[[concepts/beta]]',
            source_path: 'concepts/alpha.md',
            target_path: 'concepts/beta.md',
            metadata: {},
          },
        ],
      },
    });

    expect(parsed.structuredGraph?.node_count).toBe(1);
    expect(parsed.structuredGraph?.edges[0].edge_type).toBe('wikilink');
  });
});

describe('wikiApi.parseWikiPageDetail', () => {
  it('accepts page frontmatter and body for the preview panel', () => {
    const parsed = parseWikiPageDetail({
      enabled: true,
      path: 'concepts/alpha.md',
      frontmatter: {
        id: 'concepts/alpha',
        title: 'Alpha',
        status: 'draft',
      },
      body: '# Alpha\n\nBody text.',
    });

    expect(parsed.path).toBe('concepts/alpha.md');
    expect(parsed.frontmatter.title).toBe('Alpha');
    expect(parsed.body).toContain('Body text.');
  });
});

describe('wikiApi.extractCitationWarnings', () => {
  it('derives citation and evidence risks from page detail locally', () => {
    const draftWithoutCitations = {
      enabled: true,
      path: 'concepts/alpha.md',
      frontmatter: { status: 'draft' },
      body: 'This is a draft without any citations or wikilinks.',
    };
    expect(extractCitationWarnings(draftWithoutCitations)).toContain('草稿内容缺乏基础引用或证据链接。');

    // Body has citations but missing from frontmatter
    const unreferencedCitation = {
      enabled: true,
      path: 'concepts/beta.md',
      frontmatter: { status: 'review' },
      body: 'A claim is made here [来源].',
    };
    expect(extractCitationWarnings(unreferencedCitation)).toContain('正文包含引用标记，但 Frontmatter 缺少 evidence_refs/references，无法做跳转或后续审计。');

    const missingQuote = {
      enabled: true,
      path: 'claims/gamma.md',
      frontmatter: { kind: 'claim' },
      body: 'I claim something.',
    };
    expect(extractCitationWarnings(missingQuote)).toContain('证据型页面缺少 evidence_refs，不能进入 final/claim 可信链路。');
    expect(extractCitationWarnings(missingQuote)).toContain('这是一个 Claim，但正文中未找到 `> 引述` 或 `## Evidence` 证据上下文。');
  });

  it('accepts wikilink-backed evidence without false citation-reference warnings', () => {
    const linkedDraft = {
      enabled: true,
      path: 'concepts/linked.md',
      frontmatter: { status: 'draft' },
      body: 'This note links to [[sources/paper-a]] for evidence.',
    };

    expect(extractCitationWarnings(linkedDraft)).toEqual([]);
  });

  it('validates frontmatter evidence_refs for citation jump readiness', () => {
    const validClaim = {
      enabled: true,
      path: 'claims/valid.md',
      frontmatter: {
        kind: 'claim',
        status: 'final',
        evidence_refs: [
          { chunk_id: 'chunk-1', material_id: 'paper-1', quote: 'Quoted support text.' },
        ],
      },
      body: '> 引述：Quoted support text.\n\nThe claim is supported by [[paper-1]].',
    };

    expect(extractCitationWarnings(validClaim)).toEqual([]);

    const malformedClaim = {
      enabled: true,
      path: 'claims/malformed.md',
      frontmatter: {
        kind: 'claim',
        evidence_refs: [{ chunk_id: 'chunk-1' }, 'loose-ref'],
      },
      body: '> 引述：needs quote text.\n\nThe claim uses @cite(chunk-1).',
    };

    expect(extractCitationWarnings(malformedClaim)).toContain('部分 evidence_refs 缺少 chunk_id/source_id/material_id 或 quote/text，引用跳转可能不可用。');
  });
});

describe('wikiApi.parseWikiCompileDryRun', () => {
  it('accepts dry-run compile payload for the safe compile panel', () => {
    const parsed = parseWikiCompileDryRun({
      enabled: true,
      dry_run: true,
      created: 2,
      updated: 0,
      skipped: 0,
      planned_paths: ['concepts/alpha.md', 'claims/claim-a.md'],
      written_paths: [],
      budget_summary: {
        input_tokens: 1200,
        output_tokens: 500,
        total_tokens: 1700,
        input_cost_usd: 0.0012,
        output_cost_usd: 0.001,
        estimated_cost_usd: 0.0022,
        pricing_configured: true,
        pricing_source: 'test-rate',
        currency: 'USD',
      },
      budget_checks: [
        {
          source_id: 'src-1',
          source_chunks: 4,
          total_chunk_chars: 4800,
          estimated_tokens: 1200,
          over_budget: false,
          reason: 'within compile budget',
        },
      ],
      errors: [],
      warnings: ['Compile dry-run completed without writing wiki pages.'],
    });

    expect(parsed.enabled).toBe(true);
    expect(parsed.dry_run).toBe(true);
    expect(parsed.created).toBe(2);
    expect(parsed.planned_paths).toHaveLength(2);
    expect(parsed.budget_summary.total_tokens).toBe(1700);
    expect(parsed.budget_checks[0].source_id).toBe('src-1');
    expect(parsed.warnings[0]).toContain('dry-run');
  });
});
