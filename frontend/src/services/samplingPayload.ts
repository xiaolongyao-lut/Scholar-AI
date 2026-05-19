import type { SamplingParams } from './samplingApi.ts';

const SAMPLING_FIELDS: Array<keyof SamplingParams> = [
  'temperature',
  'top_p',
  'top_k',
  'max_tokens',
];

export function normalizeSamplingOverrides(overrides?: SamplingParams): SamplingParams {
  const normalized: SamplingParams = {};

  for (const field of SAMPLING_FIELDS) {
    const value = overrides?.[field];
    if (value !== undefined) {
      normalized[field] = value;
    }
  }

  return normalized;
}

export function hasSamplingOverrides(overrides?: SamplingParams): boolean {
  return Object.keys(normalizeSamplingOverrides(overrides)).length > 0;
}

export function updateSamplingOverrides(
  overrides: SamplingParams | undefined,
  field: keyof SamplingParams,
  value: number | undefined,
): SamplingParams | undefined {
  const next = normalizeSamplingOverrides({
    ...overrides,
    [field]: value,
  });

  return hasSamplingOverrides(next) ? next : undefined;
}

export function buildSamplingSaveRequest(
  task: string,
  overrides?: SamplingParams,
):
  | { type: 'put'; payload: Record<string, SamplingParams> }
  | { type: 'delete'; task: string } {
  const normalized = normalizeSamplingOverrides(overrides);

  if (Object.keys(normalized).length === 0) {
    return { type: 'delete', task };
  }

  return {
    type: 'put',
    payload: {
      [task]: normalized,
    },
  };
}
