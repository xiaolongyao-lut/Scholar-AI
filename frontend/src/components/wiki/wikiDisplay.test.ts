import { describe, expect, it } from 'vitest';

import {
  formatWikiError,
  formatWikiPageLabel,
  formatWikiWarning,
  sanitizeWikiVisibleText,
} from './wikiDisplay';

describe('wiki display sanitization', () => {
  it('shows page names instead of full local paths', () => {
    expect(formatWikiPageLabel('C:\\Users\\xiao\\wiki\\claims\\paper-a.md')).toBe('paper-a');
    expect(formatWikiPageLabel('notes/source-b.markdown')).toBe('source-b');
  });

  it('hides routes, structured blobs, and raw identifiers', () => {
    expect(formatWikiError('GET /api/wiki/graph failed')).toBe('读取 Wiki 信息失败，请稍后重试。');
    expect(formatWikiWarning('{"detail":"page_store_path missing"}')).toBe('检测到一项需要处理的 Wiki 状态。');
    expect(sanitizeWikiVisibleText('source_id missing', '隐藏')).toBe('隐藏');
  });

  it('keeps ordinary Chinese user-facing text', () => {
    expect(formatWikiWarning('索引需要重新生成')).toBe('索引需要重新生成');
  });

  it('maps source manifest warnings to user-facing integrity text', () => {
    expect(formatWikiWarning('Wiki query index source manifest hash differs from the current generated wiki pages.')).toBe(
      'Wiki 来源清单已变化，检索索引需要重新生成。',
    );
  });
});
