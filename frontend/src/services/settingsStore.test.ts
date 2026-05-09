/**
 * settingsStore.test.ts — TASK-180: Settings retrievalTopK persistence test
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { loadSettings, saveSettings, type AppSettings } from '@/services/settingsStore';

describe('settingsStore', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns default settings when localStorage is empty', () => {
    const settings = loadSettings();
    expect(settings.workspace.retrievalTopK).toBe(6);
    expect(settings.llm.provider).toBe('DeepSeek');
    expect(settings.embedding.dimension).toBe(1536);
  });

  it('persists and loads custom retrievalTopK', () => {
    const settings = loadSettings();
    settings.workspace.retrievalTopK = 12;
    saveSettings(settings);

    const reloaded = loadSettings();
    expect(reloaded.workspace.retrievalTopK).toBe(12);
  });

  it('deep-merges partial saved data with defaults', () => {
    localStorage.setItem('scholar-ai-settings', JSON.stringify({
      workspace: { retrievalTopK: 15 },
    }));
    const settings = loadSettings();
    expect(settings.workspace.retrievalTopK).toBe(15);
    expect(settings.workspace.autoIndex).toBe(true); // from defaults
    expect(settings.llm.model).toBe('deepseek-chat'); // from defaults
  });

  it('handles corrupted localStorage gracefully', () => {
    // Overwrite with truly invalid JSON
    localStorage.setItem('scholar-ai-settings', '<<<INVALID>>>');
    const settings = loadSettings();
    // loadSettings catches JSON.parse errors and returns a full defaults shape
    expect(settings).toHaveProperty('llm');
    expect(settings).toHaveProperty('embedding');
    expect(settings).toHaveProperty('workspace');
    expect(typeof settings.workspace.retrievalTopK).toBe('number');
  });

  it('roundtrips full settings without loss', () => {
    const custom: AppSettings = {
      llm: {
        provider: 'TestProvider',
        apiKey: 'key-xxx',
        model: 'test-model',
        baseUrl: 'http://localhost:9999',
        temperature: 0.3,
        topP: 0.5,
        maxTokens: 2048,
        systemPrompt: 'You are a test.',
      },
      embedding: {
        provider: 'TestEmbed',
        apiKey: 'ek-xxx',
        model: 'embed-test',
        baseUrl: 'http://localhost:9998',
        dimension: 768,
      },
      workspace: {
        localStoragePath: '/tmp/test',
        autoIndex: false,
        retrievalTopK: 20,
      },
    };

    saveSettings(custom);
    const reloaded = loadSettings();
    expect(reloaded).toEqual(custom);
  });
});
