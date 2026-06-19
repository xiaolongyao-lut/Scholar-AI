/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_FLAG_RESEARCH_WORKBENCH?: string;
  readonly VITE_SMART_READ_DEBUG?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  pywebview?: {
    api?: {
      minimize_window?: () => void;
      maximize_window?: () => void;
      close_window?: () => void;
      save_dialog?: (defaultName?: string) => Promise<string | null>;
      save_bytes?: (defaultName: string, contentBase64: string) => Promise<string | null>;
      open_dialog?: (fileTypes?: string[]) => Promise<string | null>;
      folder_dialog?: () => Promise<string | null>;
    };
  };
}
