import type { InspirationSpark } from '@/types/writing';

const TECHNICAL_DETAIL_PLACEHOLDER = '（已隐藏技术细节）';
const GENERIC_CONTENT_FALLBACK = '内容包含内部诊断，已隐藏。';
const GENERIC_ERROR_FALLBACK = '生成失败，请检查配置或稍后重试。';
const CREDENTIAL_ERROR_MESSAGE = '访问凭证不可用，请在 API 配置中检查后重试。';
const NETWORK_ERROR_MESSAGE = '生成超时或网络不可用，请稍后重试。';

const ROUTE_OR_URL_PATTERN = /\bhttps?:\/\/\S+|(?:^|[\s"'([{])\/(?:api|inspiration|mcp|chat|agent|settings|resources|runtime)\S*/gi;
const WINDOWS_PATH_PATTERN = /\b[A-Za-z]:\\[^\s"'<>]+|\\\\[^\s"'<>]+/g;
const JSONISH_PATTERN = /[{[][^{}\[\]\n]{0,600}["'][^{}\[\]\n]{0,600}:[^{}\[\]\n]{0,600}[}\]]/g;
const ENV_ASSIGNMENT_PATTERN = /\benv\s*=|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b/g;
const INTERNAL_SNAKE_PATTERN = /\b(?:capability|provider|credential|session|runtime|route|tool|mcp|api|env)_[a-z0-9_]+\b/gi;
const SNAKE_CODE_ONLY_PATTERN = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;
const SECRET_WORD_PATTERN = /\b(api[\s_-]*key|authorization|bearer|token|secret|password|credential)\b/i;
const NETWORK_ERROR_PATTERN = /\b(timeout|timed out|network error|econnaborted|err_network|failed to fetch)\b/i;
const STATUS_ERROR_PATTERN = /\b(status code|http)\s*(4\d\d|5\d\d)\b/i;

type AnalysisChainKey =
  | 'observation'
  | 'mechanism'
  | 'evidence'
  | 'boundary'
  | 'counter_evidence'
  | 'next_action';

export type InspirationAnalysisFieldKind = 'text' | 'list';

export interface InspirationAnalysisField {
  key: AnalysisChainKey;
  label: string;
  stageLabel: string;
  kind: InspirationAnalysisFieldKind;
  values: string[];
}

export type InspirationAnalysisMode = 'irac' | 'fincot';

export interface InspirationAnalysisDisplay {
  mode: InspirationAnalysisMode;
  title: string;
  fields: InspirationAnalysisField[];
  confidenceReason: string | null;
  temporalSensitivity: number | null;
}

interface FieldLabelConfig {
  label: string;
  stageLabel: string;
}

const IRAC_FIELD_LABELS: Record<AnalysisChainKey, FieldLabelConfig> = {
  observation: { label: '研究问题', stageLabel: 'Issue' },
  mechanism: { label: '规则 / 机制', stageLabel: 'Rule' },
  evidence: { label: '适用证据', stageLabel: 'Application' },
  boundary: { label: '边界条件', stageLabel: 'Application' },
  counter_evidence: { label: '反例 / 冲突', stageLabel: 'Counter' },
  next_action: { label: '下一步', stageLabel: 'Conclusion' },
};

const FINCOT_FIELD_LABELS: Record<AnalysisChainKey, FieldLabelConfig> = {
  observation: { label: '现象', stageLabel: 'Phenomenon' },
  mechanism: { label: '驱动 / 中介机制', stageLabel: 'Driver' },
  evidence: { label: '结果指标 / 证据', stageLabel: 'Indicator' },
  boundary: { label: '风险 / 边界', stageLabel: 'Risk' },
  counter_evidence: { label: '反向信号', stageLabel: 'Counter' },
  next_action: { label: '下一步验证', stageLabel: 'Validation' },
};

function normalizeVisibleInput(value: string | null | undefined): string {
  return String(value ?? '').replace(/\u0000/g, '').trim();
}

function collapseHiddenPlaceholders(value: string): string {
  return value
    .replace(new RegExp(`(?:${TECHNICAL_DETAIL_PLACEHOLDER.replace(/[()]/g, '\\$&')}\\s*){2,}`, 'g'), TECHNICAL_DETAIL_PLACEHOLDER)
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

/**
 * Bounds model/runtime text before it is rendered in the inspiration UI.
 *
 * Input must be plain text from API responses or caught errors. The returned
 * string is safe for ordinary UI copy: URLs, local paths, env labels, JSON-like
 * blobs, credential words, and internal diagnostic codes are hidden.
 */
export function sanitizeInspirationVisibleText(
  value: string | null | undefined,
  fallback = GENERIC_CONTENT_FALLBACK,
): string {
  const raw = normalizeVisibleInput(value);
  const fallbackText = normalizeVisibleInput(fallback) || GENERIC_CONTENT_FALLBACK;
  if (!raw) return fallbackText;
  if (SECRET_WORD_PATTERN.test(raw)) return CREDENTIAL_ERROR_MESSAGE;
  if (SNAKE_CODE_ONLY_PATTERN.test(raw)) return fallbackText;

  const sanitized = collapseHiddenPlaceholders(
    raw
      .replace(ROUTE_OR_URL_PATTERN, (match) => (
        /^https?:/i.test(match) || match.startsWith('/')
          ? TECHNICAL_DETAIL_PLACEHOLDER
          : `${match[0] ?? ''}${TECHNICAL_DETAIL_PLACEHOLDER}`
      ))
      .replace(WINDOWS_PATH_PATTERN, TECHNICAL_DETAIL_PLACEHOLDER)
      .replace(JSONISH_PATTERN, TECHNICAL_DETAIL_PLACEHOLDER)
      .replace(ENV_ASSIGNMENT_PATTERN, '内部配置')
      .replace(INTERNAL_SNAKE_PATTERN, '内部诊断'),
  );

  if (!sanitized || sanitized === TECHNICAL_DETAIL_PLACEHOLDER) return fallbackText;
  return sanitized;
}

/**
 * Converts unknown generation failures into bounded user-facing copy.
 *
 * The shape accepts any thrown value because axios/fetch/runtime exceptions
 * vary by browser and adapter. Diagnostic detail stays out of the rendered UI.
 */
export function formatInspirationVisibleError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? '');
  if (NETWORK_ERROR_PATTERN.test(message)) return NETWORK_ERROR_MESSAGE;
  if (STATUS_ERROR_PATTERN.test(message)) return GENERIC_ERROR_FALLBACK;
  return sanitizeInspirationVisibleText(message, GENERIC_ERROR_FALLBACK);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readVisibleText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const raw = normalizeVisibleInput(value);
  if (!raw) return null;
  return sanitizeInspirationVisibleText(raw, GENERIC_CONTENT_FALLBACK);
}

function readVisibleTextList(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  const values: string[] = [];
  for (const item of value) {
    const visible = readVisibleText(item);
    if (visible) values.push(visible);
    if (values.length >= limit) break;
  }
  return values;
}

function readTemporalSensitivity(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

function appendTextField(
  fields: InspirationAnalysisField[],
  chain: Record<string, unknown>,
  key: AnalysisChainKey,
  labels: Record<AnalysisChainKey, FieldLabelConfig>,
): void {
  const value = readVisibleText(chain[key]);
  if (!value) return;
  const label = labels[key];
  fields.push({
    key,
    label: label.label,
    stageLabel: label.stageLabel,
    kind: 'text',
    values: [value],
  });
}

function appendListField(
  fields: InspirationAnalysisField[],
  chain: Record<string, unknown>,
  key: AnalysisChainKey,
  labels: Record<AnalysisChainKey, FieldLabelConfig>,
): void {
  const values = readVisibleTextList(chain[key], 5);
  if (values.length === 0) return;
  const label = labels[key];
  fields.push({
    key,
    label: label.label,
    stageLabel: label.stageLabel,
    kind: 'list',
    values,
  });
}

/**
 * Converts optional Inspiration chain fields into a bounded display model.
 *
 * Input may come from current API responses or old localStorage snapshots, so
 * every field is shape-checked at runtime before UI rendering.
 */
export function buildInspirationAnalysisDisplay(
  spark: Pick<
    InspirationSpark,
    'analysis_chain' | 'fincot_chain' | 'frame' | 'confidence_reason' | 'temporal_sensitivity'
  >,
): InspirationAnalysisDisplay | null {
  const fincotChain = isRecord(spark.fincot_chain) ? spark.fincot_chain : null;
  const analysisChain = isRecord(spark.analysis_chain) ? spark.analysis_chain : null;
  const mode: InspirationAnalysisMode = fincotChain || spark.frame === 'fincot' ? 'fincot' : 'irac';
  const labels = mode === 'fincot' ? FINCOT_FIELD_LABELS : IRAC_FIELD_LABELS;
  const chain = fincotChain ?? analysisChain;
  const fields: InspirationAnalysisField[] = [];

  if (chain) {
    appendTextField(fields, chain, 'observation', labels);
    appendTextField(fields, chain, 'mechanism', labels);
    appendListField(fields, chain, 'evidence', labels);
    appendTextField(fields, chain, 'boundary', labels);
    appendListField(fields, chain, 'counter_evidence', labels);
    appendTextField(fields, chain, 'next_action', labels);
  }

  const confidenceReason = readVisibleText(spark.confidence_reason);
  const temporalSensitivity = readTemporalSensitivity(spark.temporal_sensitivity);

  if (fields.length === 0 && !confidenceReason && temporalSensitivity === null) {
    return null;
  }

  return {
    mode,
    title: mode === 'fincot' ? 'FinCoT 推理链' : 'IRAC 分析链',
    fields,
    confidenceReason,
    temporalSensitivity,
  };
}
