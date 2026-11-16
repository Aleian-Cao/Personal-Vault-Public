import type { ChatAnswer, Entry, HostBridge, ImportPreviewResult, SearchResult, StartupState } from '../types';

// Dev/test double for the Tauri+sidecar host. Never used inside the desktop app (host.ts selects it
// only when Tauri is absent). Mirrors the backend contract: vault files + a remembered pointer,
// a separate demo store, passwords never leave via list/search.

export const SYNTHETIC_SEED: Entry[] = [
  { id: 'syn-001', account: 'Facebook — Demo Personal', name: 'demo.personal@example.invalid', password: 'CANARY_DEMO_FB', aliases: ['fb chính', 'facebook cá nhân'], description: 'Dữ liệu giả lập thử nghiệm', tags: ['mạng xã hội', 'cá nhân'], url: 'https://facebook.com' },
  { id: 'syn-002', account: 'Facebook — Demo Shop', name: 'demo.shop@example.invalid', password: 'CANARY_DEMO_SHOP', aliases: ['fb bán hàng', 'shop online'], description: 'Trang bán hàng demo', tags: ['kinh doanh', 'fb'], url: 'https://business.facebook.com' },
  { id: 'syn-003', account: 'ETAP Server 15', name: 'demo15', password: 'CANARY_DEMO_15', aliases: ['etap 15', 'server15'], description: 'Máy chủ mô phỏng tính toán hệ thống điện', tags: ['kỹ thuật', 'etap'], url: 'etap://192.168.1.15:8000' },
  { id: 'syn-004', account: 'PSCAD Demo 1', name: 'pscad1', password: 'CANARY_DEMO_PSCAD_1', aliases: ['pscad máy 1', 'pscad workstation'], description: 'Workspace mô phỏng điện từ EMT', tags: ['pscad', 'emt'], url: '' },
  { id: 'syn-005', account: 'PSCAD Demo 2', name: 'pscad2', password: 'CANARY_DEMO_PSCAD_2', aliases: ['pscad máy 2'], description: 'Workspace tính toán quá điện áp TRV', tags: ['pscad', 'trv'], url: '' },
  { id: 'syn-006', account: 'ETAP Server 1', name: 'etap1', password: 'CANARY_DEMO_ETAP_1', aliases: ['etap 1', 'server1'], description: 'Máy chủ tính ngắn mạch', tags: ['etap'], url: '' },
  { id: 'syn-007', account: 'ETAP Server 5', name: 'etap5', password: 'CANARY_DEMO_ETAP_5', aliases: ['etap 5', 'server5'], description: 'Máy chủ tính trào lưu công suất', tags: ['etap'], url: '' },
  { id: 'syn-008', account: 'Internal Wiki — Engineering', name: 'engineer@example.invalid', password: 'CANARY_DEMO_WIKI', aliases: ['wiki nội bộ', 'tài liệu kỹ thuật'], description: 'Kho tri thức quy trình kỹ thuật mẫu', tags: ['nội bộ', 'wiki'], url: 'https://wiki.example.invalid' },
];

export const DEMO_COUNT = 500;
const demoEntries = (): Entry[] => [
  ...SYNTHETIC_SEED.map((e) => ({ ...e })),
  ...Array.from({ length: DEMO_COUNT - SYNTHETIC_SEED.length }, (_, i) => ({
    id: `demo-${i + 1}`, account: `Synthetic Account ${i + 1}`, name: `demo${i + 1}`, password: `CANARY_DEMO_${i + 1}`,
    aliases: [], description: '', tags: [], url: '',
  })),
];

const MOCK_PATH = 'C:\\Users\\Synthetic\\Documents\\my-vault.pvault';
const OTHER_PATH = 'D:\\Synthetic\\other-vault.pvault';
const SAVE_PATH = 'C:\\Users\\Synthetic\\Documents\\personal-vault.pvault';
const MOCK_PW = 'Synthetic-Master-Only-123!';
const IMPORT_EXT = new Set(['.txt', '.csv', '.json', '.ps1', '.bat']);
const REJECT = 'Import rejected: unsupported format, invalid field, missing data or duplicate record.';

type Stored = Entry & { password: string };
interface VaultFile { password: string; entries: Stored[] }

const key = (e: Entry) => `${e.account.toLowerCase()}:::${e.name}`;
const strip = ({ password: _p, ...rest }: Entry): Entry => rest;

export class MemoryMockBridge implements HostBridge {
  version = '0.1.0-preview';

  // ---- observation hooks for tests (window.__mock) ----
  saved: any[] = [];
  lastCopied: string | null = null;
  hidden = false;

  private files = new Map<string, VaultFile>();
  private remembered: string | null = null;
  private active: { path: string; demo: boolean } | null = null;
  private demo: Stored[] = [];
  private pending: Stored[] | null = null;
  private generation = 0;
  private crashed = false; // simulates a dead sidecar: first call fails, the next process starts fresh and LOCKED
  private chatCtx: Entry[] = []; // RAM-only follow-up context, cleared on lock/open

  constructor() {
    const mode = new URLSearchParams(globalThis.location?.search ?? '').get('mock') ?? 'fresh';
    this.files.set(OTHER_PATH, { password: MOCK_PW, entries: [] });
    if (mode === 'locked' || mode === 'open') {
      this.files.set(MOCK_PATH, { password: MOCK_PW, entries: SYNTHETIC_SEED.map((e) => ({ ...e }) as Stored) });
      this.remembered = MOCK_PATH;
    }
    if (mode === 'missing') this.remembered = MOCK_PATH;
    if (mode === 'open') this.active = { path: MOCK_PATH, demo: false };
  }

  fileCount = () => this.files.size;
  entryCount = () => this.store().length;
  forceCrash = () => { this.crashed = true; };
  private respawn() { this.crashed = false; this.active = null; this.pending = null; this.chatCtx = []; this.generation++; }
  forceLock = () => { this.active = null; this.chatCtx = []; this.generation++; };
  passwordOf = (id: string) => this.store().find((e) => e.id === id)?.password;
  passwordOfAccount = (account: string) => this.store().find((e) => e.account === account)?.password;

  private store(): Stored[] {
    if (!this.active) return [];
    return this.active.demo ? this.demo : this.files.get(this.active.path)!.entries;
  }
  private need(): Stored[] {
    if (this.crashed) { this.respawn(); throw new Error('Failed to write to sidecar: The pipe is being closed.'); }
    if (!this.active) throw new Error('Vault is locked.');
    return this.store();
  }
  private open(path: string, demo: boolean) {
    this.active = { path, demo };
    this.pending = null;
    this.chatCtx = [];
    this.generation++;
  }

  async getStartupState(): Promise<StartupState> {
    if (this.crashed) this.respawn(); // the host restarts a dead sidecar transparently; it comes back locked
    const g = this.generation;
    if (this.active) return { state: 'unlocked', path: this.active.path, demo: this.active.demo, generation: g };
    if (!this.remembered) return { state: 'fresh', path: null, demo: false, generation: g };
    return { state: this.files.has(this.remembered) ? 'locked' : 'missing', path: this.remembered, demo: false, generation: g };
  }

  async pickVaultToOpen() { return OTHER_PATH; }
  async pickVaultToSave() { return SAVE_PATH; }

  async unlock(password: string, vaultPath: string) {
    const f = this.files.get(vaultPath);
    if (!f) return { success: false, error: 'Vault file not found.' };
    if (f.password !== password) return { success: false, error: 'Cannot unlock: wrong password, invalid vault, or unreadable file.' };
    this.open(vaultPath, false);
    this.remembered = vaultPath;
    return { success: true };
  }

  async lock() { this.active = null; this.pending = null; this.chatCtx = []; this.generation++; }
  async touch() {}

  async createVault(password: string, vaultPath: string) {
    if (password.length < 12) return { success: false, error: 'Use a master password of at least 12 characters.' };
    if (this.files.has(vaultPath)) return { success: false, error: 'Vault already exists.' };
    this.files.set(vaultPath, { password, entries: [] });
    this.open(vaultPath, false);
    this.remembered = vaultPath;
    return { success: true, path: vaultPath };
  }

  async openDemo() {
    this.demo = demoEntries() as Stored[];
    this.open('(demo)', true); // separate store, never remembered
    return { success: true };
  }

  async getEntries(): Promise<Entry[]> { return this.need().map(strip); }

  async search(query: string): Promise<SearchResult> {
    const list = this.need();
    const q = query.trim().toLowerCase();
    if (!q) return { kind: 'none', items: [] };
    const items = list.filter((e) =>
      [e.account, e.name, e.description, ...e.aliases, ...e.tags].some((s) => s.toLowerCase().includes(q)));
    const kind: SearchResult['kind'] = items.length === 1 ? 'exact' : items.length > 1 ? 'ambiguous' : q.length >= 3 ? 'suggestion' : 'none';
    return { kind, items: items.map(strip), sessionGeneration: this.generation };
  }

  async chatSearch(query: string): Promise<ChatAnswer> {
    this.need(); // fail closed when locked
    const q = query.trim().toLowerCase();
    const follow = q.match(/^(?:máy|may|server)\s*(?:thứ\s*)?(\d+)$/);
    let items: Entry[];
    if (follow && this.chatCtx.length) {
      items = this.chatCtx.filter((e) => [e.account, ...e.aliases].some((s) => new RegExp(`(^|\\D)${follow[1]}(\\D|$)`).test(s)));
    } else {
      items = (await this.search(query)).items;
    }
    if (items.length > 1) this.chatCtx = items; else if (!follow) this.chatCtx = [];
    const status = items.length === 1 ? 'exact' : items.length > 1 ? 'ambiguous' : 'none';
    return {
      route: 'deterministic', status, entries: items, total: items.length, clarify: status !== 'exact',
      message: status === 'exact' ? 'Tìm thấy 1 tài khoản phù hợp.' : status === 'ambiguous'
        ? `Có ${items.length} tài khoản phù hợp. Hãy chọn đúng tài khoản.` : 'Không tìm thấy tài khoản phù hợp. Thử tên khác hoặc bí danh.',
      suggestedAction: null, sessionGeneration: this.generation,
    };
  }

  async revealPassword(entryId: string) {
    const e = this.need().find((x) => x.id === entryId);
    if (!e) throw new Error('Entry not found.');
    return e.password;
  }

  async copyToClipboard(text: string) { this.lastCopied = text; return { success: true }; }

  async copyPassword(entryId: string) {
    const e = this.need().find((x) => x.id === entryId);
    if (!e) return { success: false };
    this.lastCopied = e.password;
    return { success: true, clearedIn: 20 };
  }

  async saveEntry(entry: Partial<Entry> & { account: string; name: string }) {
    const list = this.need();
    this.saved.push(JSON.parse(JSON.stringify(entry)));
    const i = entry.id ? list.findIndex((e) => e.id === entry.id) : -1;
    if (i >= 0) {
      list[i] = { ...list[i], ...entry, password: entry.password || list[i].password } as Stored;
    } else {
      if (!entry.password) return { success: false, error: 'Password is required for new entry.' };
      list.push({ aliases: [], description: '', tags: [], url: '', ...entry, id: 'new-' + Date.now(), password: entry.password } as Stored);
    }
    return { success: true };
  }

  async deleteEntry(entryId: string) {
    const list = this.need();
    const i = list.findIndex((e) => e.id === entryId);
    if (i >= 0) list.splice(i, 1);
    return { success: true };
  }

  async inspectImport(content: string, ext: string): Promise<ImportPreviewResult> {
    const list = this.need();
    this.pending = null;
    if (!IMPORT_EXT.has(ext.toLowerCase())) throw new Error(REJECT);
    const recs: Stored[] = [];
    for (const block of content.split(/\r?\n\s*\r?\n/)) {
      if (!block.trim()) continue;
      const d: Record<string, string> = {};
      for (const line of block.split(/\r?\n/).filter((l) => l.trim())) {
        const m = line.match(/^\s*([A-Za-z]+)\s*:[ \t]?(.*)$/);
        if (!m) throw new Error(REJECT);
        d[m[1].toLowerCase()] = m[2];
      }
      if (!d.account || !d.name || !d.pass) throw new Error(REJECT);
      const parts = (s?: string) => (s ? s.split(';').map((x) => x.trim()).filter(Boolean) : []);
      recs.push({ id: 'imp-' + Math.random().toString(36).slice(2, 8), account: d.account, name: d.name, password: d.pass,
        aliases: parts(d.aliases), description: d.description || '', tags: parts(d.tags), url: d.url || '' });
    }
    if (!recs.length) throw new Error(REJECT);
    const have = new Set(list.map(key));
    const records = recs.map((e) => ({ entry: strip(e), status: (have.has(key(e)) ? 'duplicate' : 'new') as 'new' | 'duplicate' }));
    this.pending = recs.filter((e) => !have.has(key(e)));
    return { total: records.length, newCount: this.pending.length, duplicateCount: records.length - this.pending.length, invalidCount: 0, records };
  }

  async confirmImport() {
    const list = this.need();
    if (!this.pending) return { success: false, error: 'No import preview pending.' };
    const have = new Set(list.map(key));
    const add = this.pending.filter((e) => !have.has(key(e)));
    list.push(...add);
    this.pending = null;
    return { success: true, importedCount: add.length, skippedCount: 0 };
  }

  async backupVault() {
    this.need();
    return { success: true, path: 'C:\\Users\\Synthetic\\Documents\\personal-vault-backup.pvault' };
  }

  async hideWindow() { this.hidden = true; }
  async showMainWindow() {}
}
