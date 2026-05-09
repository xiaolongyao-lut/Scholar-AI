import test from 'node:test';
import assert from 'node:assert/strict';

async function loadModule() {
  try {
    return await import('./inspirationSamplingStatus.ts');
  } catch (error) {
    assert.fail(`inspirationSamplingStatus.ts must exist for the InspirationPanel summary hint: ${error}`);
  }
}

test('summarizeInspirationSampling reports default when no overrides are present', async () => {
  const { summarizeInspirationSampling } = await loadModule();

  assert.equal(summarizeInspirationSampling(undefined), 'Sampling: 默认');
  assert.equal(summarizeInspirationSampling({}), 'Sampling: 默认');
});

test('summarizeInspirationSampling lists overridden inspiration fields', async () => {
  const { summarizeInspirationSampling } = await loadModule();

  assert.equal(
    summarizeInspirationSampling({ temperature: 0.9, max_tokens: 2048 }),
    'Sampling: 已覆盖 (temperature, max_tokens)',
  );
});
