import type { SamplingParams } from '@/services/samplingApi';

const FIELDS: Array<keyof SamplingParams> = ['temperature', 'top_p', 'top_k', 'max_tokens'];

export function summarizeInspirationSampling(overrides?: SamplingParams): string {
  const activeFields = FIELDS.filter((field) => overrides?.[field] !== undefined);
  if (activeFields.length === 0) {
    return 'Sampling: 默认';
  }
  return `Sampling: 已覆盖 (${activeFields.join(', ')})`;
}
