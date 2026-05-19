/**
 * Wizard state persistence (S4b / plan 2026-05-20 Decision #8).
 *
 * When the user needs to leave the install wizard to create a new
 * credential (which lives on a different settings tab), the wizard
 * serializes its current state to sessionStorage. On return to the MCP
 * tab the wrapper rehydrates and re-opens the wizard at the step that
 * was active. v1 explicitly does NOT allow inline credential create.
 */

import type {
  McpPackageScanResult,
  McpInstallationInstallResponse,
} from '@/services/mcpInstallApi';

export type WizardStep =
  | 'source'        // user pasting / picking a local path
  | 'scanning'      // scan API in flight
  | 'candidate'     // pick a launch candidate (skipped if exactly one)
  | 'config'        // fill non-secret config_fields
  | 'credentials'   // bind required_credentials
  | 'review'        // confirm + trust checkbox + install
  | 'installing'    // install API in flight
  | 'done'          // success card
  | 'error';        // recoverable failure card

export interface WizardState {
  version: 1;
  step: WizardStep;
  source_path: string;
  template_hint?: string;
  scan_result?: McpPackageScanResult;
  selected_candidate_sha?: string;
  server_slug: string;
  display_name: string;
  config_values: Record<string, string>;
  credential_bindings: Record<string, string>;
  trust_to_probe: boolean;
  enable_for_session: boolean;
  install_result?: McpInstallationInstallResponse;
  install_error_code?: string;
  install_error_message?: string;
}

export const WIZARD_STORAGE_KEY = 'mcp.installer.wizard.v1';

export function defaultWizardState(): WizardState {
  return {
    version: 1,
    step: 'source',
    source_path: '',
    template_hint: undefined,
    scan_result: undefined,
    selected_candidate_sha: undefined,
    server_slug: '',
    display_name: '',
    config_values: {},
    credential_bindings: {},
    trust_to_probe: false,
    enable_for_session: true,
    install_result: undefined,
    install_error_code: undefined,
    install_error_message: undefined,
  };
}

/** Persist for the cross-tab credential creation round-trip. */
export function saveWizardState(state: WizardState): void {
  try {
    sessionStorage.setItem(WIZARD_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // sessionStorage may be unavailable (incognito quirks); swallow.
  }
}

/** Rehydrate after the user navigates back. Returns null on absent/invalid. */
export function loadWizardState(): WizardState | null {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(WIZARD_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as WizardState;
    if (parsed.version !== 1) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearWizardState(): void {
  try {
    sessionStorage.removeItem(WIZARD_STORAGE_KEY);
  } catch {
    // ignore
  }
}
