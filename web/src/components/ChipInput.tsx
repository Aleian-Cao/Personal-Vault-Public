import React, { useState } from 'react';
import { X } from 'lucide-react';

interface Props {
  label: string;
  /** Singular noun for accessible names, e.g. "bí danh" -> "Thêm bí danh" / "Xóa bí danh X". */
  noun: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

/** Chip editor: Enter / ";" / "," adds, Backspace on empty removes the last, × removes one. */
export const ChipInput: React.FC<Props> = ({ label, noun, values, onChange, placeholder }) => {
  const [draft, setDraft] = useState('');

  const commit = (raw: string) => {
    const v = raw.trim();
    setDraft('');
    if (v && !values.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...values, v]);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ';' || e.key === ',') {
      e.preventDefault(); // Enter must not submit the surrounding form
      commit(draft);
    } else if (e.key === 'Backspace' && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div>
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-1">{label}</span>
      <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5 rounded-lg border border-slate-200 bg-white focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700 border border-blue-100">
            <span>{v}</span>
            <button
              type="button"
              aria-label={`Xóa ${noun} ${v}`}
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="w-4 h-4 rounded-full hover:bg-blue-100 flex items-center justify-center"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        <input
          aria-label={`Thêm ${noun}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => commit(draft)}
          placeholder={values.length ? '' : placeholder}
          className="flex-1 min-w-[8rem] py-1 text-sm text-slate-900 placeholder:text-slate-400 bg-transparent focus:outline-none"
        />
      </div>
    </div>
  );
};
