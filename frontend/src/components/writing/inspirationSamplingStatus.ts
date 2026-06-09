import type { SamplingParams } from '@/services/samplingApi';

const FIELDS: Array<keyof SamplingParams> = ['temperature', 'top_p', 'top_k', 'max_tokens'];
const FIELD_LABELS: Record<keyof SamplingParams, string> = {
  temperature: '温度',
  top_p: 'Top-P',
  top_k: 'Top-K',
  max_tokens: '最大输出',
};

export function summarizeInspirationSampling(overrides?: SamplingParams): string {
  const activeFields = FIELDS.filter((field) => overrides?.[field] !== undefined);
  if (activeFields.length === 0) {
    return '采样参数：默认';
  }
  return `采样参数：已覆盖 ${activeFields.map((field) => FIELD_LABELS[field]).join('、')}`;
}
