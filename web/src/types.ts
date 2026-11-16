export interface Entry {
  id: string;
  account: string;
  name: string;
  /** Never populated by the host for list/search; only set by the edit form when the user types a new one. */
  password?: string;
  aliases: string[];
  description: string;
  tags: string[];
  url: string;
}

export type SearchKind = 'none' | 'ambiguous' | 'suggestion' | 'match' | 'exact';

export interface SearchResult {
  kind: SearchKind;
  items: Entry[];
  sessionGeneration?: number;
}

export interface ImportPreviewRecord {
  entry: Entry;
  status: 'new' | 'duplicate';
}

export interface ImportPreviewResult {
  total: number;
  newCount: number;
  duplicateCount: number;
  invalidCount: number;
  records: ImportPreviewRecord[];
}

export interface ChatAnswer {
  route: 'deterministic' | 'qwen' | 'fallback';
  status: 'exact' | 'ambiguous' | 'suggested' | 'none';
  entries: Entry[];
  total: number;
  message: string;
  clarify: boolean;
  suggestedAction: string | null;
  sessionGeneration?: number;
}

/** Single source of truth for which screen to show at startup; answered by the backend. */
export interface StartupState {
  state: 'fresh' | 'locked' | 'missing' | 'unlocked';
  path: string | null;
  demo: boolean;
  generation: number;
}

export interface HostBridge {
  version: string;
  getStartupState: () => Promise<StartupState>;
  pickVaultToOpen: () => Promise<string | null>;
  pickVaultToSave: () => Promise<string | null>;
  unlock: (password: string, vaultPath: string) => Promise<{ success: boolean; error?: string }>;
  lock: () => Promise<void>;
  /** Idle-timer keep-alive; the backend enforces the actual auto-lock. */
  touch: () => Promise<void>;
  createVault: (password: string, vaultPath: string) => Promise<{ success: boolean; path?: string; error?: string }>;
  openDemo: () => Promise<{ success: boolean; error?: string }>;
  getEntries: () => Promise<Entry[]>;
  /** Chatbot search: backend pipeline returns metadata only; secrets stay behind reveal/copy. */
  chatSearch: (query: string) => Promise<ChatAnswer>;
  search: (query: string) => Promise<SearchResult>;
  revealPassword: (entryId: string) => Promise<string>;
  /** Non-secret text only (username, URL). */
  copyToClipboard: (text: string) => Promise<{ success: boolean }>;
  /** Native copy: the password never enters JS. Cleared after ~20s if the clipboard still holds it. */
  copyPassword: (entryId: string) => Promise<{ success: boolean; clearedIn?: number }>;
  saveEntry: (entry: Partial<Entry> & { account: string; name: string }) => Promise<{ success: boolean; error?: string }>;
  deleteEntry: (entryId: string) => Promise<{ success: boolean; error?: string }>;
  inspectImport: (fileContent: string, extension: string) => Promise<ImportPreviewResult>;
  confirmImport: () => Promise<{ success: boolean; importedCount?: number; skippedCount?: number; error?: string }>;
  backupVault: () => Promise<{ success: boolean; path?: string; error?: string }>;
  hideWindow: () => Promise<void>;
  showMainWindow: () => Promise<void>;
}
