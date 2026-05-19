/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_GEMINI_PROVIDER?: string;
  readonly VITE_GEMINI_BASE_URL?: string;
  readonly VITE_GEMINI_API_KEY?: string;
  readonly VITE_GEMINI_MODEL?: string;
  readonly VITE_COPILOT_PROVIDER?: string;
  readonly VITE_COPILOT_BASE_URL?: string;
  readonly VITE_COPILOT_API_KEY?: string;
  readonly VITE_COPILOT_MODEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
