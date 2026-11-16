import React, { useState, useEffect, useRef, useCallback } from 'react';
import type { Entry, HostBridge, ImportPreviewResult, SearchResult } from '../types';
import { host } from '../lib/host';
import { errorText, isLockedError } from '../lib/errors';
import { EntryModal } from './EntryModal';
import { ImportModal } from './ImportModal';
import { useConfirmCopy } from './ConfirmCopy';
import { IconButton, DemoChip, HelpPopup } from './ui';
import {
  Search,
  Plus,
  Lock,
  Copy,
  Eye,
  EyeOff,
  Globe,
  Tag,
  KeyRound,
  Upload,
  Archive,
  Trash2,
  Edit3,
  CheckCircle2,
  AlertTriangle,
  Info,
  ChevronRight,
  MessageSquare,
} from 'lucide-react';

interface VaultManagerProps {
  /** True only for the separate synthetic demo vault; shows a permanent label. */
  demo: boolean;
  onLock: () => void;
  onChat: () => void;
}

type Tone = 'info' | 'success' | 'warn';
const TONE: Record<Tone, string> = {
  success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
  warn: 'bg-amber-50 border-amber-200 text-amber-800',
};
const REVEAL_MS = 15000;
const MANAGER_TIPS = [
  'Ctrl+K hoặc / để tìm nhanh trong danh sách.',
  'Nhập dữ liệu: .txt, .csv, .json, .ps1, .bat; bạn xem trước rồi mới xác nhận.',
  'Sao lưu tạo một bản mã hóa của két sắt.',
  'Mật khẩu chỉ hiện khi bạn bấm và tự ẩn sau 15 giây.',
];
const btnSecondary =
  'px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition';
const sectionLabel = 'text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-1';

export const VaultManager: React.FC<VaultManagerProps> = ({ demo, onLock, onChat }) => {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ text: string; tone: Tone } | null>(null);

  const [entryModal, setEntryModal] = useState<{ entry: Entry | null } | null>(null);
  const [importState, setImportState] = useState<{ fileName: string; preview: ImportPreviewResult | null; error: string | null } | null>(null);
  const [importBusy, setImportBusy] = useState(false);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const revealTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchSeq = useRef(0);

  const currentList = searchResult ? searchResult.items : entries;
  const selectedEntry = currentList.find((e) => e.id === selectedId) ?? null;

  const { confirm: confirmCopy, dialog: copyDialog } = useConfirmCopy();
  const say = (text: string, tone: Tone = 'success') => setStatusMessage({ text, tone });

  // Any host call can hit a backend that locked behind our back (idle, crash, restart):
  // go back through the startup state machine instead of showing stale data or crashing.
  const guard = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    try {
      return await fn();
    } catch (e) {
      if (isLockedError(e)) onLock();
      else setStatusMessage({ text: errorText(e), tone: 'warn' });
      return undefined;
    }
  }, [onLock]);

  const clearReveal = () => {
    setRevealedPassword(null);
    if (revealTimerRef.current) clearTimeout(revealTimerRef.current);
  };

  const loadAllEntries = useCallback(async () => {
    const data = await guard(() => host().getEntries());
    if (!data) return;
    setEntries(data);
    setSelectedId((cur) => (cur && data.some((e) => e.id === cur) ? cur : data[0]?.id ?? null));
  }, [guard]);

  useEffect(() => { loadAllEntries(); }, [loadAllEntries]);
  useEffect(() => () => { if (revealTimerRef.current) clearTimeout(revealTimerRef.current); }, []);

  // Ctrl+K or "/" focuses the search box
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey && e.key.toLowerCase() === 'k') || (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName ?? ''))) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const handleSearch = async (val: string) => {
    setQuery(val);
    const seq = ++searchSeq.current;
    if (!val.trim()) {
      setSearchResult(null);
      return;
    }
    const res = await guard(() => host().search(val));
    if (!res || seq !== searchSeq.current) return; // stale response
    setSearchResult(res);
    setSelectedId(res.items[0]?.id ?? null);
    clearReveal();
  };

  const handleSelect = (entry: Entry) => {
    setSelectedId(entry.id);
    clearReveal();
  };

  const handleReveal = async () => {
    if (!selectedEntry) return;
    if (revealedPassword) return clearReveal();
    const pw = await guard(() => host().revealPassword(selectedEntry.id));
    if (pw === undefined) return;
    setRevealedPassword(pw);
    revealTimerRef.current = setTimeout(() => setRevealedPassword(null), REVEAL_MS);
  };

  const flashCopied = (field: string) => {
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2500);
  };

  const handleCopy = async (field: 'name' | 'password' | 'url') => {
    if (!selectedEntry) return;
    if (field === 'password') {
      if (!(await confirmCopy(selectedEntry.account))) return;
      const res = await guard(() => host().copyPassword(selectedEntry.id)); // native: password never enters JS
      if (res?.success) {
        flashCopied(field);
        say(`Đã sao chép mật khẩu · tự xóa sau ${res.clearedIn ?? 20} giây.`);
      } else if (res) say('Không sao chép được mật khẩu.', 'warn');
      return;
    }
    const res = await host().copyToClipboard(field === 'name' ? selectedEntry.name : selectedEntry.url);
    if (res.success) {
      flashCopied(field);
      say(field === 'name' ? 'Đã sao chép tên đăng nhập.' : 'Đã sao chép URL/Host (không tự mở).');
    } else say('Không sao chép được.', 'warn');
  };

  const handleDelete = async () => {
    if (!selectedEntry) return;
    if (!window.confirm(`Xóa tài khoản "${selectedEntry.account}" khỏi két sắt? Thao tác này không thể hoàn tác.`)) return;
    const res = await guard(() => host().deleteEntry(selectedEntry.id));
    if (!res) return;
    if (res.success) say('Đã xóa tài khoản.', 'info');
    else say(errorText(res.error), 'warn');
    await loadAllEntries();
    if (searchResult) handleSearch(query);
  };

  const handleSaveModal = async (data: Parameters<HostBridge['saveEntry']>[0]): Promise<string | null> => {
    try {
      const res = await host().saveEntry(data);
      if (!res.success) return errorText(res.error, 'Không thể lưu tài khoản.');
    } catch (e) {
      if (isLockedError(e)) { onLock(); return errorText(e); }
      return errorText(e, 'Không thể lưu tài khoản.');
    }
    say('Đã lưu tài khoản vào két sắt.');
    await loadAllEntries();
    if (searchResult) handleSearch(query);
    return null;
  };

  // ---- import: real file chooser -> preview -> explicit confirm -> reported result ----
  const handleFilePicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow picking the same file again
    if (!file) return;
    const dot = file.name.lastIndexOf('.');
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
    try {
      const content = await file.text(); // read as text only; nothing is executed
      const preview = await host().inspectImport(content, ext);
      setImportState({ fileName: file.name, preview, error: null });
    } catch (err) {
      if (isLockedError(err)) return onLock();
      setImportState({ fileName: file.name, preview: null, error: errorText(err, 'Không đọc được file.') });
    }
  };

  const handleConfirmImport = async () => {
    setImportBusy(true);
    const res = await guard(() => host().confirmImport());
    setImportBusy(false);
    if (!res) return;
    setImportState(null);
    if (res.success) {
      const skipped = res.skippedCount ? `; bỏ qua ${res.skippedCount} bản trùng` : '';
      say(`Đã nhập ${res.importedCount ?? 0} tài khoản mới${skipped}.`);
    } else say(errorText(res.error), 'warn');
    await loadAllEntries();
  };

  const handleBackup = async () => {
    const res = await guard(() => host().backupVault());
    if (!res) return;
    if (res.success) say(`Đã tạo bản sao lưu mã hóa tại ${res.path}`);
    else say(errorText(res.error, 'Không tạo được bản sao lưu.'), 'warn');
  };

  const emptyVault = entries.length === 0 && !query.trim();

  return (
    <div className="flex flex-col h-screen bg-[#F9FAFB] text-slate-700">
      <header className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-2.5">
          <img src="/logo-mark.png" alt="Personal Vault" className="w-8 h-8 object-contain" />
          {demo && <DemoChip />}
        </div>

        <div className="flex items-center gap-1">
          <button onClick={() => setEntryModal({ entry: null })} className="px-3.5 py-2 mr-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 transition shadow-sm">
            <Plus className="w-4 h-4" />
            Thêm mới
          </button>
          <HelpPopup tips={MANAGER_TIPS} version={host().version} />
          <IconButton label="Trò chuyện" onClick={onChat}><MessageSquare className="w-[18px] h-[18px]" /></IconButton>
          <IconButton label="Nhập dữ liệu" onClick={() => fileInputRef.current?.click()}><Upload className="w-[18px] h-[18px]" /></IconButton>
          <input ref={fileInputRef} type="file" accept=".txt,.csv,.json,.ps1,.bat" onChange={handleFilePicked} className="hidden" aria-hidden="true" tabIndex={-1} />
          <IconButton label="Sao lưu" onClick={handleBackup}><Archive className="w-[18px] h-[18px]" /></IconButton>
          <IconButton label="Khóa két sắt" onClick={onLock}><Lock className="w-[18px] h-[18px]" /></IconButton>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div className="w-80 md:w-96 border-r border-slate-200 bg-white flex flex-col shrink-0">
          <div className="p-3 border-b border-slate-100">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
              <input
                ref={searchInputRef}
                type="text"
                value={query}
                onChange={(e) => handleSearch(e.target.value)}
                placeholder="Tìm tài khoản…"
                aria-label="Tìm tài khoản"
                className="w-full pl-9 pr-8 py-1.5 text-xs rounded-lg border border-slate-200 bg-slate-50 text-slate-900 placeholder:text-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition"
              />
              {query && (
                <button onClick={() => handleSearch('')} aria-label="Xóa nội dung tìm kiếm" className="absolute right-2.5 top-2 text-xs text-slate-400 hover:text-slate-600">✕</button>
              )}
            </div>

            <div className="flex items-center justify-between mt-2 px-1 text-[11px] text-slate-400 font-medium">
              <span>{query ? `Kết quả: ${currentList.length}` : `Tổng cộng: ${entries.length} tài khoản`}</span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
            {currentList.length === 0 ? (
              <div className="p-8 text-center text-xs text-slate-400 flex flex-col items-center">
                <Info className="w-6 h-6 text-slate-300 mb-2" />
                {emptyVault ? 'Két sắt đang trống.' : `Không tìm thấy tài khoản phù hợp với "${query}".`}
              </div>
            ) : (
              currentList.map((item) => {
                const isSelected = selectedId === item.id;
                return (
                  <div
                    key={item.id}
                    onClick={() => handleSelect(item)}
                    className={`p-3 cursor-pointer transition flex items-center justify-between ${isSelected ? 'bg-blue-50/70 border-l-4 border-blue-600' : 'hover:bg-slate-50 border-l-4 border-transparent'}`}
                  >
                    <div className="min-w-0 pr-2">
                      <div className="text-xs font-semibold text-slate-900 truncate">{item.account}</div>
                      <div className="text-[11px] text-slate-500 font-mono truncate mt-0.5">{item.name}</div>
                      {item.aliases.length > 0 && (
                        <div className="text-[10px] text-blue-600 truncate mt-1">{item.aliases.join(' • ')}</div>
                      )}
                    </div>
                    <ChevronRight className={`w-3.5 h-3.5 shrink-0 transition ${isSelected ? 'text-blue-600 translate-x-0.5' : 'text-slate-300'}`} />
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="flex-1 bg-[#F9FAFB] overflow-y-auto p-6 md:p-8 flex flex-col items-center">
          {statusMessage && (
            <div role="status" className={`w-full max-w-2xl mb-4 p-3 rounded-lg border text-xs font-medium flex items-center justify-between animate-fadeIn ${TONE[statusMessage.tone]}`}>
              <div className="flex items-center gap-2">
                {statusMessage.tone === 'warn' ? <AlertTriangle className="w-4 h-4 shrink-0" /> : <CheckCircle2 className="w-4 h-4 shrink-0" />}
                <span>{statusMessage.text}</span>
              </div>
              <button onClick={() => setStatusMessage(null)} aria-label="Đóng thông báo" className="opacity-70 hover:opacity-100">✕</button>
            </div>
          )}

          {selectedEntry ? (
            <div className="w-full max-w-2xl bg-white border border-slate-200 rounded-xl shadow-sm p-6 space-y-6">
              <div className="flex items-start justify-between pb-4 border-b border-slate-100">
                <h2 className="text-lg font-bold text-slate-900 tracking-tight">{selectedEntry.account}</h2>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setEntryModal({ entry: selectedEntry })}
                    className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-600 transition"
                    title="Chỉnh sửa tài khoản" aria-label="Chỉnh sửa tài khoản"
                  >
                    <Edit3 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={handleDelete}
                    className="p-1.5 rounded-lg border border-slate-200 hover:bg-red-50 text-slate-600 hover:text-red-600 transition"
                    title="Xóa tài khoản" aria-label="Xóa tài khoản"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className={sectionLabel}>Tên đăng nhập / Email</label>
                  <div className="flex gap-2">
                    <input readOnly value={selectedEntry.name} className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 bg-slate-50 text-slate-900 font-mono" />
                    <button onClick={() => handleCopy('name')} className={`${btnSecondary} py-2 shrink-0`}>
                      {copiedField === 'name' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5 text-slate-500" />}
                      Sao chép
                    </button>
                  </div>
                </div>

                <div>
                  <label className={sectionLabel}>Mật khẩu</label>
                  <div className="flex gap-2">
                    <input
                      readOnly
                      type={revealedPassword ? 'text' : 'password'}
                      value={revealedPassword || '••••••••••••'}
                      aria-label="Mật khẩu"
                      className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 bg-slate-50 text-slate-900 font-mono tracking-wider"
                    />
                    <button onClick={handleReveal} className={`${btnSecondary} py-2 shrink-0`}>
                      {revealedPassword ? <EyeOff className="w-3.5 h-3.5 text-slate-500" /> : <Eye className="w-3.5 h-3.5 text-slate-500" />}
                      {revealedPassword ? 'Ẩn' : 'Hiện 15 giây'}
                    </button>
                    <button onClick={() => handleCopy('password')} className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition shrink-0 shadow-sm">
                      {copiedField === 'password' ? <CheckCircle2 className="w-3.5 h-3.5 text-white" /> : <Copy className="w-3.5 h-3.5" />}
                      Sao chép mật khẩu
                    </button>
                  </div>
                </div>
              </div>

              <div className="pt-2 space-y-4 border-t border-slate-100">
                {selectedEntry.aliases.length > 0 && (
                  <div>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedEntry.aliases.map((a) => (
                        <span key={a} className="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700 border border-blue-100">{a}</span>
                      ))}
                    </div>
                  </div>
                )}

                {selectedEntry.description && (
                  <div>
                    <p className="text-xs text-slate-600 leading-relaxed">{selectedEntry.description}</p>
                  </div>
                )}

                {selectedEntry.tags.length > 0 && (
                  <div>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedEntry.tags.map((t) => (
                        <span key={t} className="px-2 py-0.5 rounded-full text-[11px] bg-slate-100 text-slate-700 border border-slate-200 flex items-center gap-1">
                          <Tag className="w-2.5 h-2.5" />
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {selectedEntry.url && (
                  <div>
                    {/* Text + copy only: a stored URL/host/custom scheme is never opened or executed. */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-700 flex items-center gap-1 font-mono min-w-0">
                        <Globe className="w-3.5 h-3.5 shrink-0 text-slate-400" />
                        <span className="truncate">{selectedEntry.url}</span>
                      </span>
                      <button onClick={() => handleCopy('url')} className={`${btnSecondary} shrink-0`}>
                        {copiedField === 'url' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5 text-slate-500" />}
                        Sao chép URL
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="text-center text-xs text-slate-400 mt-20 max-w-xs">
              <KeyRound className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              {emptyVault ? 'Thêm tài khoản đầu tiên.' : 'Chọn một tài khoản.'}
            </div>
          )}
        </div>
      </div>

      {copyDialog}
      {entryModal && (
        <EntryModal entry={entryModal.entry} onClose={() => setEntryModal(null)} onSave={handleSaveModal} />
      )}
      {importState && (
        <ImportModal
          fileName={importState.fileName}
          preview={importState.preview}
          error={importState.error}
          busy={importBusy}
          onClose={() => setImportState(null)}
          onConfirm={handleConfirmImport}
        />
      )}
    </div>
  );
};
