/**
 * Discussion defaults — type guards + normalization.
 *
 * The backend `/api/discussion/defaults` endpoint returns a permissive
 * shape: any field may be missing, of the wrong type, or out of range.
 * `normalizeDiscussionDefaults` clamps numeric fields to the same
 * bounds the DiscussionPanel UI enforces (1-20 turns, 0.5-1 threshold)
 * and applies safe defaults so callers can rely on every field being
 * present.
 *
 * Bounds are kept in sync with `literature_assistant/core/models/discussion.py`
 * (`min_turns: ge=1 le=20`, `convergence_threshold: ge=0.0 le=1.0`)
 * — note frontend tightens threshold lower bound to 0.5 because values
 * below 0.5 essentially disable the auto-stop gate.
 */

export interface DiscussionDefaults {
  auto_stop: boolean;
  min_turns: number;
  convergence_threshold: number;
  convergence_judge_agent_id: string;
}

export const DEFAULT_DISCUSSION_DEFAULTS: DiscussionDefaults = Object.freeze({
  auto_stop: false,
  min_turns: 2,
  convergence_threshold: 0.85,
  convergence_judge_agent_id: '',
});

export const DISCUSSION_DEFAULT_BOUNDS = Object.freeze({
  min_turns: { min: 1, max: 20 },
  convergence_threshold: { min: 0.5, max: 1 },
});

export const DISCUSSION_TURN_WARNING_THRESHOLD = 5;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readOptionalBoolean(source: Record<string, unknown>, key: string): boolean | undefined {
  const value = source[key];
  return typeof value === 'boolean' ? value : undefined;
}

function readOptionalNumber(
  source: Record<string, unknown>,
  key: string,
  min: number,
  max: number,
): number | undefined {
  const value = source[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return undefined;
  }
  return Math.min(max, Math.max(min, value));
}

function readOptionalString(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === 'string' ? value : undefined;
}

/**
 * Coerce an arbitrary `/api/discussion/defaults` response payload into
 * a fully-populated DiscussionDefaults record. Missing fields, wrong
 * types, and out-of-range numbers all collapse to the safe default.
 *
 * Inputs:
 *  - value: anything the backend returned (may be null, an array, a
 *    primitive, or an object).
 *
 * Output:
 *  - DiscussionDefaults with every field populated.
 */
export function normalizeDiscussionDefaults(value: unknown): DiscussionDefaults {
  if (!isRecord(value)) {
    return { ...DEFAULT_DISCUSSION_DEFAULTS };
  }
  return {
    auto_stop: readOptionalBoolean(value, 'auto_stop') ?? DEFAULT_DISCUSSION_DEFAULTS.auto_stop,
    min_turns:
      readOptionalNumber(
        value,
        'min_turns',
        DISCUSSION_DEFAULT_BOUNDS.min_turns.min,
        DISCUSSION_DEFAULT_BOUNDS.min_turns.max,
      ) ?? DEFAULT_DISCUSSION_DEFAULTS.min_turns,
    convergence_threshold:
      readOptionalNumber(
        value,
        'convergence_threshold',
        DISCUSSION_DEFAULT_BOUNDS.convergence_threshold.min,
        DISCUSSION_DEFAULT_BOUNDS.convergence_threshold.max,
      ) ?? DEFAULT_DISCUSSION_DEFAULTS.convergence_threshold,
    convergence_judge_agent_id:
      readOptionalString(value, 'convergence_judge_agent_id') ??
      DEFAULT_DISCUSSION_DEFAULTS.convergence_judge_agent_id,
  };
}
