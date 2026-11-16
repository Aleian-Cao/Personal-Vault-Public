import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { Entry } from '../types';
import { host, isTauriEnvironment } from '../lib/host';
import { isLockedError } from '../lib/errors';
import { Search, Lock, CheckCircle2 } from 'lucide-react';

const MAX_ROWS = 8;
const HIDE_AFTER_COPY_MS = 600;

/** Compact, search-first window opened by Ctrl+Alt+V. CRUD/import/backup stay in Vault Manager. */
export const QuickAccess: React.FC = () => {
  const [locked, setLocked] = useState<boolean | null>(null);
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Entry[]>([]);
  const [sel, setSel] = useState(0);
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null); // entry id awaiting the second Enter
  const pendingRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqId = useRef(0);

  const setPend = (id: string | null) => { pendingRef.current = id; setPending(id); };

  const close = useCallback(() => { host().hideWindow(); }, []);

  // Re-check the backend every time the window is shown; never trust a previous session's view.
  const reset = useCallback(async () => {
    reqId.current++;
    setQuery(''); setItems([]); setSel(0); setStatus(null); pendingRef.current = null; setPending(null);
    try {
      setLocked((await host().getStartupState()).state !== 'unlocked');
    } catch {
      setLocked(true);
    }
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  // Lock state only (keeps what the user typed): a window that is shown WITHOUT the hotkey event (focus, ShowWindow, restore)
  // must never keep displaying a stale locked/unlocked view.
  const refreshLock = useCallback(async () => {
    try {
      setLocked((await host().getStartupState()).state !== 'unlocked');
    } catch {
      setLocked(true);
    }
  }, []);

  useEffect(() => {
    reset();
    const onVisible = () => { if (document.visibilityState === 'visible') reset(); };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', refreshLock);
    // Also while visible: a window shown without focus (ShowWindow, restore) fires no focus event. Cheap IPC, does not count as user activity.
    const poll = window.setInterval(() => { if (document.visibilityState === 'visible') void refreshLock(); }, 2000);
    let unlisten: (() => void) | undefined;
    if (isTauriEnvironment()) {
      import('@tauri-apps/api/event').then(({ listen }) => listen('quick-access-open', reset)).then((u) => { unlisten = u; });
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (pendingRef.current) { pendingRef.current = null; setPending(null); setStatus('Đã hủy, chưa sao chép gì.'); } else close();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', refreshLock);
      window.clearInterval(poll);
      window.removeEventListener('keydown', onKey);
      unlisten?.();
    };
  }, [reset, close, refreshLock]);

  const onChange = async (value: string) => {
    setQuery(value);
    setStatus(null);
    setPend(null);
    const id = ++reqId.current;
    if (!value.trim()) { setItems([]); setSel(0); return; }
    try {
      const res = await host().search(value);
      if (id !== reqId.current) return; // stale response (query changed, window re-shown, or locked)
      setItems(res.items.slice(0, MAX_ROWS));
      setSel(0);
    } catch (e) {
      if (isLockedError(e)) setLocked(true);
    }
  };

  const current = items[sel];

  const copyPassword = async () => {
    if (!current) return;
    if (pendingRef.current !== current.id) { // explicit confirmation: the first Enter only arms the copy
      setPend(current.id);
      setStatus(`Nhấn Enter lần nữa để sao chép mật khẩu «${current.account}» (Esc: hủy). Lịch sử clipboard của Windows có thể giữ bản sao.`);
      return;
    }
    setPend(null);
    const res = await host().copyPassword(current.id);
    if (res.success) {
      setStatus(`Đã sao chép mật khẩu của "${current.account}" — tự xóa sau ${res.clearedIn ?? 20} giây.`);
      setTimeout(close, HIDE_AFTER_COPY_MS);
    } else {
      setStatus('Không sao chép được mật khẩu.');
    }
  };

  const copyUsername = async () => {
    if (!current) return;
    setPend(null);
    const res = await host().copyToClipboard(current.name);
    setStatus(res.success ? `Đã sao chép tên đăng nhập: ${current.name}` : 'Không sao chép được tên đăng nhập.');
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setPend(null); setSel((s) => Math.min(s + 1, items.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setPend(null); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (e.shiftKey) copyUsername(); else copyPassword(); }
  };

  const shell = 'h-screen flex flex-col bg-white text-slate-700 border border-slate-200';
  const header = (
    <div data-tauri-drag-region className="h-8 px-3 flex items-center justify-between bg-slate-50 border-b border-slate-100 text-[11px] font-semibold text-slate-500 uppercase tracking-wider select-none">
      <span data-tauri-drag-region>Truy cập nhanh</span>
      <span data-tauri-drag-region className="normal-case font-medium">Ctrl+Alt+V</span>
    </div>
  );

  if (locked === null) return <div className={shell}>{header}</div>;

  if (locked) {
    return (
      <div className={shell}>
        {header}
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
          <Lock className="w-8 h-8 text-slate-400" />
          <p className="text-sm font-semibold text-slate-900">Két sắt đang khóa</p>
          <p className="text-xs text-slate-500">Mở khóa trong cửa sổ chính để dùng Truy cập nhanh.</p>
          <button
            type="button"
            onClick={async () => { await host().showMainWindow(); close(); }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition shadow-sm"
          >
            Mở cửa sổ chính
          </button>
          <p className="text-[11px] text-slate-400">Esc để đóng</p>
        </div>
      </div>
    );
  }

  return (
    <div className={shell}>
      {header}
      <div className="p-3 border-b border-slate-100">
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded={items.length > 0}
            aria-controls="qa-list"
            aria-activedescendant={current ? `qa-opt-${sel}` : undefined}
            aria-label="Tìm tài khoản"
            aria-describedby={pending ? 'qa-status' : undefined}
            autoFocus
            value={query}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Tìm tài khoản, bí danh… (vd: fb chính, etap 15)"
            className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
      </div>

      <div id="qa-list" role="listbox" aria-label="Kết quả" className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {items.map((it, i) => (
          <div
            key={it.id}
            id={`qa-opt-${i}`}
            role="option"
            aria-selected={i === sel}
            onMouseDown={(e) => { e.preventDefault(); setPend(null); setSel(i); inputRef.current?.focus(); }}
            className={`px-4 py-2.5 cursor-pointer border-l-4 ${i === sel ? 'bg-blue-50/70 border-blue-600' : 'border-transparent hover:bg-slate-50'}`}
          >
            <div className="text-sm font-semibold text-slate-900 truncate">{it.account}</div>
            <div className="text-xs text-slate-500 font-mono truncate">{it.name}</div>
            {it.aliases.length > 0 && <div className="text-[11px] text-blue-600 truncate mt-0.5">{it.aliases.join(' • ')}</div>}
          </div>
        ))}
        {query.trim() && items.length === 0 && (
          <p className="p-6 text-center text-xs text-slate-400">Không tìm thấy tài khoản phù hợp.</p>
        )}
        {!query.trim() && (
          <p className="p-6 text-center text-xs text-slate-400">Gõ để tìm. Mật khẩu luôn được che; chỉ sao chép khi bạn nhấn Enter.</p>
        )}
      </div>

      <div className="px-4 py-2 border-t border-slate-100 bg-slate-50 text-[11px] text-slate-500 space-y-1">
        {status && (
          <p id="qa-status" role="status" className={`flex items-center gap-1.5 font-medium ${pending ? 'text-amber-700' : 'text-emerald-700'}`}>
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            {status}
          </p>
        )}
        <p>↑↓ chọn · Enter ×2: sao chép mật khẩu · Shift+Enter: sao chép tên đăng nhập · Esc: đóng</p>
      </div>
    </div>
  );
};
