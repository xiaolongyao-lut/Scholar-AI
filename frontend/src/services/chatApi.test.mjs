import test from 'node:test';
import assert from 'node:assert/strict';

import axios from 'axios';
import { askChatWithConfig } from './chatApi.ts';

const originalPost = axios.post;

const ENV_KEYS = [
  'VITE_API_BASE_URL',
  'VITE_GEMINI_PROVIDER',
  'VITE_GEMINI_BASE_URL',
  'VITE_GEMINI_API_KEY',
  'VITE_GEMINI_MODEL',
  'VITE_COPILOT_PROVIDER',
  'VITE_COPILOT_BASE_URL',
  'VITE_COPILOT_API_KEY',
  'VITE_COPILOT_MODEL',
];

function makeAxiosError(status, detail) {
  return {
    isAxiosError: true,
    message: detail,
    response: {
      status,
      data: { detail },
    },
  };
}

function applyEnv(values) {
  for (const key of ENV_KEYS) {
    if (Object.prototype.hasOwnProperty.call(values, key)) {
      process.env[key] = values[key];
    } else {
      delete process.env[key];
    }
  }
}

test.afterEach(() => {
  axios.post = originalPost;
  applyEnv({});
});

test('askChatWithConfig tries Gemini env config first and falls back to Copilot on Gemini request failure', async () => {
  applyEnv({
    VITE_GEMINI_PROVIDER: 'Gemini',
    VITE_GEMINI_BASE_URL: 'https://gemini.example.com',
    VITE_GEMINI_API_KEY: 'gemini-key',
    VITE_GEMINI_MODEL: 'gemini-2.5-flash',
    VITE_COPILOT_PROVIDER: 'Copilot',
    VITE_COPILOT_BASE_URL: 'https://copilot.example.com',
    VITE_COPILOT_API_KEY: 'copilot-key',
    VITE_COPILOT_MODEL: 'copilot-chat',
  });

  const requests = [];
  axios.post = async (_url, body) => {
    requests.push(body);
    if (requests.length === 1) {
      throw makeAxiosError(503, 'gemini temporarily unavailable');
    }
    return {
      data: {
        answer: 'fallback answer',
        model: 'copilot-chat',
      },
    };
  };

  const response = await askChatWithConfig({
    query: 'hello',
    llm: {
      provider: 'DeepSeek',
      apiKey: 'deepseek-key',
      model: 'deepseek-chat',
      baseUrl: 'https://deepseek.example.com',
      temperature: 0.7,
      topP: 0.9,
      maxTokens: 512,
      systemPrompt: '',
    },
  });

  assert.equal(response.answer, 'fallback answer');
  assert.deepEqual(response.fallback, {
    attemptedProvider: 'Gemini',
    activeProvider: 'Copilot',
  });
  assert.equal(requests.length, 2);
  assert.equal(requests[0].llm.provider, 'Gemini');
  assert.equal(requests[0].llm.model, 'gemini-2.5-flash');
  assert.equal(requests[1].llm.provider, 'Copilot');
  assert.equal(requests[1].llm.model, 'copilot-chat');
});

test('askChatWithConfig falls back to Copilot when Gemini config is invalid before the request can succeed', async () => {
  applyEnv({
    VITE_GEMINI_PROVIDER: 'Gemini',
    VITE_GEMINI_BASE_URL: 'https://gemini.example.com',
    VITE_GEMINI_API_KEY: '',
    VITE_GEMINI_MODEL: 'gemini-2.5-flash',
    VITE_COPILOT_PROVIDER: 'Copilot',
    VITE_COPILOT_BASE_URL: 'https://copilot.example.com',
    VITE_COPILOT_API_KEY: 'copilot-key',
    VITE_COPILOT_MODEL: 'copilot-chat',
  });

  const requests = [];
  axios.post = async (_url, body) => {
    requests.push(body);
    if (requests.length === 1) {
      throw makeAxiosError(400, '未配置可用的 API Key: provider=Gemini');
    }
    return {
      data: {
        answer: 'copilot rescue',
        model: 'copilot-chat',
      },
    };
  };

  const response = await askChatWithConfig({
    query: 'hello',
    llm: {
      provider: 'Gemini',
      apiKey: '',
      model: 'gemini-2.5-flash',
      baseUrl: 'https://gemini.example.com',
      temperature: 0.7,
      topP: 0.9,
      maxTokens: 512,
      systemPrompt: '',
    },
  });

  assert.equal(response.answer, 'copilot rescue');
  assert.deepEqual(response.fallback, {
    attemptedProvider: 'Gemini',
    activeProvider: 'Copilot',
  });
  assert.equal(requests.length, 2);
  assert.equal(requests[0].llm.provider, 'Gemini');
  assert.equal(requests[1].llm.provider, 'Copilot');
});
