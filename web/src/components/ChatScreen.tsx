import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatAnswer, Entry } from '../types';
import { host } from '../lib/host';
import { errorText, isLockedError } from '../lib/errors';
import { useConfirmCopy } from './ConfirmCopy';
import { Send, Lock, Settings2, Copy, Eye, EyeOff, CheckCircle2, MessageSquare, Plus, Upload, ChevronRight, ChevronLeft, KeyRound, User, SearchX } from 'lucide-react';
import { IconButton, DemoChip, HelpPopup } from './ui';

export type ChatMessage =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'assistant'; answer: ChatAnswer }
  | { id: number; role: 'error'; text: string };

interface Props {
  demo: boolean;
  /** Transcript lives in the Workspace (RAM only); it is dropped when the vault locks. */
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  onLock: () => void;
  onManage: () => void;
}

const REVEAL_MS = 15000;
const EXAMPLES = ['fb chính', 'ETAP server 15', 'PSCAD', 'cho tôi tài khoản wifi'];
const TIPS = [
  'Hỏi bằng tên, bí danh hoặc số máy: fb chính, ETAP 15, PSCAD máy 3.',
  'Chọn một dòng trong danh sách để mở tài khoản.',
  'Mật khẩu luôn bị che; chỉ hiện khi bạn bấm và tự ẩn sau 15 giây.',
  'Ctrl+Alt+V mở Truy cập nhanh từ bất kỳ đâu.',
];

let nextId = 1;

export const ChatScreen: React.FC<Props> = ({ demo, messages, setMessages, onLock, onManage }) => {
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [reveal, setReveal] = useState<{ id: string; pw: string } | null>(null); // never part of the transcript
  const [note, setNote] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<number, string>>({}); // row chosen in an ambiguous/suggested list (UI only)
  const alive = useRef(true);
  const seq = useRef(0);
  const revealTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const hideReveal = useCallback(() => {
    setReveal(null);
    if (revealTimer.current) clearTimeout(revealTimer.current);
  }, []);

  useEffect(() => {
    alive.current = true;
    host().getEntries().then((e) => alive.current && setCount(e.length)).catch((e) => isLockedError(e) && onLock());
    inputRef.current?.focus();
    return () => { alive.current = false; if (revealTimer.current) clearTimeout(revealTimer.current); };
  }, [onLock]);

  useEffect(() => { endRef.current?.scrollIntoView?.({ block: 'end' }); }, [messages, busy]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput('');
    setNote(null);
    hideReveal();
    const mySeq = ++seq.current;
    setMessages((m) => [...m, { id: nextId++, role: 'user', text: q }]);
    setBusy(true);
    try {
      const answer = await host().chatSearch(q);
      if (!alive.current || mySeq !== seq.current) return; // stale: locked/unmounted/superseded
      setMessages((m) => [...m, { id: nextId++, role: 'assistant', answer }]);
    } catch (e) {
      if (isLockedError(e)) return onLock();
      if (alive.current) setMessages((m) => [...m, { id: nextId++, role: 'error', text: errorText(e, 'Không tìm được. Thử lại.') }]);
    } finally {
      if (alive.current && mySeq === seq.current) setBusy(false);
      inputRef.current?.focus();
    }
  };

  const toggleReveal = async (e: Entry) => {
    if (reveal?.id === e.id) return hideReveal();
    try {
      const pw = await host().revealPassword(e.id);
      setReveal({ id: e.id, pw });
      if (revealTimer.current) clearTimeout(revealTimer.current);
      revealTimer.current = setTimeout(() => setReveal(null), REVEAL_MS);
    } catch (err) {
      if (isLockedError(err)) onLock();
    }
  };

  const { confirm: confirmCopy, dialog: copyDialog } = useConfirmCopy();

  const copyPw = async (e: Entry) => {
    if (!(await confirmCopy(e.account))) return;
    try {
      const r = await host().copyPassword(e.id);
      setNote(r.success ? `Đã sao chép mật khẩu của "${e.account}"; tự xóa sau ${r.clearedIn ?? 20} giây.` : 'Không sao chép được mật khẩu.');
    } catch (err) {
      if (isLockedError(err)) onLock();
    }
  };

  const copyUser = async (e: Entry) => {
    const r = await host().copyToClipboard(e.name);
    setNote(r.success ? `Đã sao chép tên đăng nhập của "${e.account}".` : 'Không sao chép được.');
  };

  const Card = ({ e }: { e: Entry }) => (
    <article aria-label={e.account} title={e.description || undefined} className="bg-white border border-slate-200 rounded-2xl shadow-sm p-4 space-y-3">
      <div className="min-w-0">
        <h3 className="text-base font-bold text-slate-900 truncate">{e.account}</h3>
        <div className="flex items-center gap-1 mt-0.5">
          <p className="text-xs text-slate-500 font-mono truncate flex items-center gap-1.5 min-w-0"><User className="w-3 h-3 shrink-0" /><span className="truncate">{e.name}</span></p>
          <IconButton label="Sao chép tên đăng nhập" onClick={() => copyUser(e)} size="sm"><Copy className="w-3.5 h-3.5" /></IconButton>
        </div>
      </div>
      <div className="flex items-center gap-2 pl-3 pr-1 py-1 rounded-lg bg-slate-50 border border-slate-100">
        <KeyRound className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span className="font-mono tracking-wider text-sm text-slate-900 truncate flex-1" data-testid="card-pass">
          {reveal?.id === e.id ? reveal.pw : '••••••••'}
        </span>
        <IconButton label={reveal?.id === e.id ? 'Ẩn' : 'Hiện 15 giây'} onClick={() => toggleReveal(e)} pressed={reveal?.id === e.id} size="sm">
          {reveal?.id === e.id ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </IconButton>
      </div>
      {e.aliases.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {e.aliases.slice(0, 4).map((a) => <span key={a} className="px-2 py-0.5 rounded-full text-[11px] bg-blue-50 text-blue-700 border border-blue-100">{a}</span>)}
        </div>
      )}
      <button type="button" onClick={() => copyPw(e)} className="w-full py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition shadow-sm">
        <Copy className="w-4 h-4" />
        Sao chép mật khẩu
      </button>
    </article>
  );

  /** Ambiguous / suggested: pick a row, then the full card opens. Choosing is the confirmation. */
  const Choices = ({ m, a }: { m: Extract<ChatMessage, { role: 'assistant' }>; a: ChatAnswer }) => {
    const chosen = a.entries.find((x) => x.id === picked[m.id]);
    if (chosen) {
      return (
        <div className="space-y-2">
          <Card e={chosen} />
          {a.entries.length > 1 && (
            <button type="button" onClick={() => { hideReveal(); setPicked((p) => { const n = { ...p }; delete n[m.id]; return n; }); }} className="text-xs font-semibold text-slate-500 hover:text-slate-800 flex items-center gap-1">
              <ChevronLeft className="w-3.5 h-3.5" />
              Chọn khác
            </button>
          )}
        </div>
      );
    }
    return (
      <div className="space-y-1.5">
        {a.status === 'suggested' && <p className="text-xs font-semibold text-slate-500">Có phải ý bạn?</p>}
        <ul className="bg-white border border-slate-200 rounded-2xl shadow-sm divide-y divide-slate-100 overflow-hidden" aria-label="Chọn tài khoản">
          {a.entries.map((e) => (
            <li key={e.id}>
              <button type="button" onClick={() => { hideReveal(); setPicked((p) => ({ ...p, [m.id]: e.id })); }} className="w-full text-left px-4 py-2.5 flex items-center justify-between gap-3 hover:bg-blue-50/60 focus:outline-none focus-visible:bg-blue-50 transition">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-900 truncate">{e.account}</span>
                  <span className="block text-xs text-slate-500 font-mono truncate">{e.name}</span>
                </span>
                <ChevronRight className="w-4 h-4 text-slate-300 shrink-0" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  const emptyChat = messages.length === 0 && count !== 0;
  const askForm = (
    <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className={emptyChat ? 'w-full' : 'border-t border-slate-200 bg-white px-4 py-3'}>
      <div className={`${emptyChat ? '' : 'max-w-2xl mx-auto'} flex gap-2`}>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          aria-label="Câu hỏi"
          placeholder="Hỏi về tài khoản…"
          autoComplete="off"
          className={`flex-1 px-4 ${emptyChat ? 'py-3.5 text-base shadow-sm' : 'py-2.5 text-sm'} rounded-xl border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500`}
        />
        <button type="submit" aria-label="Gửi" title="Gửi" disabled={busy || !input.trim()} className={`${emptyChat ? 'w-12' : 'w-11'} bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white rounded-xl flex items-center justify-center shadow-sm transition`}>
          <Send className="w-4 h-4" />
        </button>
      </div>
    </form>
  );

  return (
    <div className="flex flex-col h-screen bg-[#F9FAFB] text-slate-700">
      <header className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-2.5">
          <img src="/logo-mark.png" alt="Personal Vault" className="w-8 h-8 object-contain" />
          {demo && <DemoChip />}
        </div>
        <div className="flex items-center gap-0.5">
          <HelpPopup tips={TIPS} version={host().version} />
          <IconButton label="Quản lý két sắt" onClick={onManage}><Settings2 className="w-[18px] h-[18px]" /></IconButton>
          <IconButton label="Khóa két sắt" onClick={onLock}><Lock className="w-[18px] h-[18px]" /></IconButton>
        </div>
      </header>

      <div className={`flex-1 overflow-y-auto px-4 ${emptyChat ? 'flex flex-col justify-center' : 'py-6'}`}>
        <div className="max-w-2xl mx-auto w-full space-y-4" aria-live="polite">
          {messages.length === 0 && count === 0 && (
            <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center space-y-4">
              <KeyRound className="w-8 h-8 text-slate-300 mx-auto" />
              <p className="text-sm font-semibold text-slate-900">Két sắt đang trống.</p>
              <div className="flex justify-center gap-2">
                <button type="button" onClick={onManage} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 shadow-sm">
                  <Plus className="w-4 h-4" />
                  Thêm tài khoản
                </button>
                <button type="button" onClick={onManage} className="px-3 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-semibold flex items-center gap-1.5">
                  <Upload className="w-4 h-4 text-slate-500" />
                  Nhập dữ liệu
                </button>
              </div>
            </div>
          )}

          {emptyChat && (
            <div className="space-y-4">
              <MessageSquare className="w-8 h-8 text-slate-300 mx-auto" />
              {askForm}
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((x) => (
                  <button key={x} type="button" onClick={() => ask(x)} className="px-3 py-1 rounded-full text-xs bg-white border border-slate-200 hover:bg-slate-50 text-slate-700">{x}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => {
            if (m.role === 'user') {
              return <div key={m.id} className="flex justify-end"><div className="max-w-[80%] px-3.5 py-2 rounded-2xl rounded-br-sm bg-blue-600 text-white text-sm">{m.text}</div></div>;
            }
            if (m.role === 'error') {
              return <div key={m.id} role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{m.text}</div>;
            }
            const a = m.answer;
            return (
              <div key={m.id} className="space-y-2">
                {a.entries.length === 0 && <p className="text-sm text-slate-500 px-1 flex items-center gap-2"><SearchX className="w-4 h-4 text-slate-400 shrink-0" />{a.message}</p>}
                {a.entries.length > 0 && a.status === 'exact' && a.entries.map((e) => <Card key={e.id} e={e} />)}
                {a.entries.length > 0 && a.status !== 'exact' && <Choices m={m} a={a} />}
                {a.total > a.entries.length && <p className="text-[11px] text-slate-400 px-1">+{a.total - a.entries.length} nữa — hỏi cụ thể hơn.</p>}
              </div>
            );
          })}

          {busy && <p role="status" className="text-xs text-slate-400 px-1">Đang tìm…</p>}
          {note && (
            <p role="status" className="text-xs text-emerald-700 font-medium flex items-center gap-1.5 px-1">
              <CheckCircle2 className="w-3.5 h-3.5" />
              {note}
            </p>
          )}
          <div ref={endRef} />
        </div>
      </div>

      {!emptyChat && askForm}
      {copyDialog}
    </div>
  );
};
