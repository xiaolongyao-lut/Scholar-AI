/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_FLAG_RESEARCH_WORKBENCH?: string;
  readonly VITE_SMART_READ_DEBUG?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
