import React, { useEffect, useRef, useState } from 'react';
import { HelpCircle, FlaskConical } from 'lucide-react';

/** Icon-only button: the label is a tooltip (hover/focus) and the accessible name, never visible text. */
export const IconButton: React.FC<{
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  tone?: 'plain' | 'danger';
  pressed?: boolean;
  disabled?: boolean;
  size?: 'md' | 'sm';
  hideTip?: boolean;
}> = ({ label, onClick, children, tone = 'plain', pressed, disabled, size = 'md', hideTip }) => (
  <span className="relative group inline-flex">
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      className={`${size === 'sm' ? 'w-7 h-7' : 'w-9 h-9'} rounded-lg flex items-center justify-center border border-transparent transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 ${
        tone === 'danger' ? 'text-slate-500 hover:text-red-600 hover:bg-red-50' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'
      }`}
    >
      {children}
    </button>
    <span
      role="tooltip"
      className={`${hideTip ? 'hidden' : ''} pointer-events-none absolute top-full mt-1.5 right-0 z-30 whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition group-hover:opacity-100 group-focus-within:opacity-100`}
    >
      {label}
    </span>
  </span>
);

/** Fixed marker of the synthetic demo vault (kept as visible text: a demo must never look like a personal vault). */
export const DemoChip: React.FC = () => (
  <span title="Dữ liệu mẫu giả lập, tách biệt khỏi két sắt của bạn" className="text-[10px] font-bold tracking-wider bg-amber-100 text-amber-800 px-2 py-0.5 rounded border border-amber-300 flex items-center gap-1">
    <FlaskConical className="w-3 h-3" />
    DEMO
  </span>
);

/** Non-essential guidance lives here, not on the screen. */
export const HelpPopup: React.FC<{ tips: string[]; version?: string }> = ({ tips, version }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey); };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <IconButton label="Trợ giúp" onClick={() => setOpen((o) => !o)} pressed={open} hideTip={open}>
        <HelpCircle className="w-[18px] h-[18px]" />
      </IconButton>
      {open && (
        <div role="dialog" aria-label="Trợ giúp" className="absolute right-0 top-full mt-2 z-40 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
          <ul className="space-y-1.5 text-xs text-slate-700">
            {tips.map((t) => <li key={t} className="flex gap-2"><span className="text-blue-600">•</span><span>{t}</span></li>)}
          </ul>
          {version && <p className="mt-2 pt-2 border-t border-slate-100 text-[10px] font-mono text-slate-400">v{version}</p>}
        </div>
      )}
    </div>
  );
};
