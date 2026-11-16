import { invoke } from '@tauri-apps/api/core';
import { writeText } from '@tauri-apps/plugin-clipboard-manager';
import { open, save } from '@tauri-apps/plugin-dialog';
import { getCurrentWindow } from '@tauri-apps/api/window';
import type { ChatAnswer, Entry, HostBridge, ImportPreviewResult, SearchResult, StartupState } from '../types';

const call = <T = any>(method: string, params: Record<string, unknown> = {}) =>
  invoke<T>('invoke_sidecar', { method, params });

// Search/list rows never carry a password; the UI only ever sees metadata.
const toEntry = (e: any): Entry => ({
  id: e.id,
  account: e.account,
  name: e.name,
  aliases: e.aliases || [],
  description: e.description || '',
  tags: e.tags || [],
  url: e.url || '',
});

const failure = (err: any, fallback: string) => ({ success: false as const, error: err?.toString() || fallback });

export class ProductionTauriBridge implements HostBridge {
  version = '0.1.0-candidate';

  // Errors propagate on purpose: a dead sidecar must never look like "no vault" or "locked".
  getStartupState(): Promise<StartupState> {
    return call<StartupState>('startup_state');
  }

  async pickVaultToOpen(): Promise<string | null> {
    const selected = await open({
      title: 'Chọn file két sắt (.pvault)',
      multiple: false,
      filters: [{ name: 'Personal Vault', extensions: ['pvault'] }],
    });
    return typeof selected === 'string' ? selected : null;
  }

  async pickVaultToSave(): Promise<string | null> {
    let dir = '';
    try {
      dir = (await call<{ dir: string }>('default_dir'))?.dir || '';
    } catch {
      // fall back to the dialog's own default
    }
    return save({
      title: 'Chọn vị trí lưu két sắt mới',
      defaultPath: dir ? `${dir}\\personal-vault.pvault` : 'personal-vault.pvault',
      filters: [{ name: 'Personal Vault', extensions: ['pvault'] }],
    });
  }

  async unlock(password: string, vaultPath: string) {
    try {
      const res = await call('unlock', { path: vaultPath, password });
      return { success: !!res?.success };
    } catch (err: any) {
      return failure(err, 'Không thể mở khóa két sắt.');
    }
  }

  async lock(): Promise<void> {
    try {
      await call('lock');
    } catch {
      // sidecar already gone = nothing left to lock
    }
  }

  async touch(): Promise<void> {
    try {
      await call('touch');
    } catch {
      // best effort
    }
  }

  async createVault(password: string, vaultPath: string) {
    try {
      const res = await call('create', { path: vaultPath, password, demo: false });
      return { success: !!res?.success, path: res?.path };
    } catch (err: any) {
      return failure(err, 'Không thể tạo két sắt.');
    }
  }

  async openDemo() {
    try {
      const res = await call('open_demo');
      return { success: !!res?.success };
    } catch (err: any) {
      return failure(err, 'Không thể mở dữ liệu mẫu.');
    }
  }

  async getEntries(): Promise<Entry[]> {
    return (await call<any[]>('get_entries')).map(toEntry);
  }

  async search(query: string): Promise<SearchResult> {
    const res = await call('search', { query });
    return { kind: res.kind, sessionGeneration: res.session_generation, items: (res.items || []).map(toEntry) };
  }

  async chatSearch(query: string): Promise<ChatAnswer> {
    const r = await call('chat_search', { query });
    return {
      route: r.route,
      status: r.status,
      entries: (r.entries || []).map(toEntry),
      total: r.total ?? (r.entries || []).length,
      message: r.message,
      clarify: !!r.clarify,
      suggestedAction: r.suggested_action ?? null,
      sessionGeneration: r.session_generation,
    };
  }

  async revealPassword(entryId: string): Promise<string> {
    return (await call('reveal', { entry_id: entryId }))?.password ?? '';
  }

  async copyToClipboard(text: string) {
    try {
      await writeText(text);
      return { success: true };
    } catch {
      return { success: false };
    }
  }

  async copyPassword(entryId: string) {
    try {
      return await invoke<{ success: boolean; clearedIn?: number }>('copy_password', { entryId });
    } catch {
      return { success: false };
    }
  }

  async saveEntry(entry: Partial<Entry> & { account: string; name: string }) {
    try {
      await call('save_entry', { entry_data: entry });
      return { success: true };
    } catch (err: any) {
      return failure(err, 'Lỗi khi lưu tài khoản.');
    }
  }

  async deleteEntry(entryId: string) {
    try {
      await call('delete_entry', { entry_id: entryId });
      return { success: true };
    } catch (err: any) {
      return failure(err, 'Lỗi khi xóa tài khoản.');
    }
  }

  async inspectImport(fileContent: string, extension: string): Promise<ImportPreviewResult> {
    const res = await call('inspect_import', { content: fileContent, extension });
    return {
      total: res.total,
      newCount: res.newCount,
      duplicateCount: res.duplicateCount,
      invalidCount: res.invalidCount ?? 0,
      records: res.records.map((r: any) => ({ entry: toEntry(r.entry), status: r.status })),
    };
  }

  async confirmImport() {
    try {
      const res = await call('confirm_import');
      return { success: true, importedCount: res?.importedCount, skippedCount: res?.skippedCount };
    } catch (err: any) {
      return failure(err, 'Lỗi khi nhập dữ liệu.');
    }
  }

  async backupVault() {
    try {
      let dir = '';
      try {
        dir = (await call<{ dir: string }>('default_dir'))?.dir || '';
      } catch {
        // ignore
      }
      const backupPath = await save({
        title: 'Lưu bản sao lưu mã hóa (.pvault)',
        defaultPath: dir ? `${dir}\\personal-vault-backup.pvault` : 'personal-vault-backup.pvault',
        filters: [{ name: 'Personal Vault', extensions: ['pvault'] }],
      });
      if (!backupPath) return { success: false, error: 'Chưa chọn vị trí lưu bản sao lưu.' };
      const res = await call('backup', { path: backupPath });
      return { success: true, path: res?.path };
    } catch (err: any) {
      return failure(err, 'Lỗi khi tạo bản sao lưu.');
    }
  }

  async hideWindow(): Promise<void> {
    await getCurrentWindow().hide();
  }

  async showMainWindow(): Promise<void> {
    await invoke('show_main_window');
  }
}
