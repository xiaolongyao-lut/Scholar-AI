import { sanitizeWikiVisibleText } from '@/components/wiki/wikiDisplay';
import type { GraphNode } from './payloadToRf';

/**
 * 图谱节点的证据展示读取 + 脱敏。维度图谱详情面板与关系图谱详情面板共用，
 * 保证「证据文本永不泄漏内部路径 / 凭证 / 系统字段」这条安全规则只实现一次。
 *
 * 输入：GraphNode（可能带 metadata.evidence_text 或 evidence_refs[].text）。
 * 输出：可安全直接渲染的字符串，或 null（无可展示证据）。
 */

const UNSAFE_PATTERN = /https?:\/\/|[A-Za-z]:\\|api[_\s-]?key|authorization|bearer|token|secret|env_refs|sha256:/i;
const MAX_EVIDENCE_LENGTH = 420;

export function sanitizeEvidencePreviewText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  if (!raw) return fallback;
  if (UNSAFE_PATTERN.test(raw)) return fallback;
  return raw.length > MAX_EVIDENCE_LENGTH ? `${raw.slice(0, MAX_EVIDENCE_LENGTH - 1)}…` : raw;
}

export function readNodeEvidenceText(node: GraphNode): string | null {
  const meta = (node.metadata ?? {}) as Record<string, unknown>;
  const fromMeta = typeof meta.evidence_text === 'string' ? meta.evidence_text : null;
  const fromRef = node.evidence_refs?.find((ref) => ref.text)?.text ?? null;
  const raw = fromMeta || fromRef;
  if (!raw) return null;
  return sanitizeEvidencePreviewText(raw, '证据内容已隐藏，避免显示内部路径或系统字段。');
}

export function readNodeLabel(node: GraphNode): string {
  return sanitizeWikiVisibleText(node.label, '知识节点');
}
