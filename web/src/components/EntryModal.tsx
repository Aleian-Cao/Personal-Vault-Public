import React, { useState } from 'react';
import type { Entry } from '../types';
import { X, Check } from 'lucide-react';
import { ChipInput } from './ChipInput';

interface EntryModalProps {
  /** Entry being edited; omit for "add new". Render the modal only while open (remount per use). */
  entry?: Entry | null;
  onClose: () => void;
  /** Resolves to an error message, or null on success. */
  onSave: (data: Partial<Entry> & { account: string; name: string }) => Promise<string | null>;
}

const label = 'text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-1';
const field =
  'w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500';

export const EntryModal: React.FC<EntryModalProps> = ({ entry, onClose, onSave }) => {
  const [account, setAccount] = useState(entry?.account || '');
  const [name, setName] = useState(entry?.name || '');
  const [password, setPassword] = useState(''); // never pre-filled: blank on edit = keep the stored secret
  const [aliases, setAliases] = useState<string[]>(entry?.aliases || []);
  const [description, setDescription] = useState(entry?.description || '');
  const [tags, setTags] = useState<string[]>(entry?.tags || []);
  const [url, setUrl] = useState(entry?.url || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!account.trim() || !name.trim()) {
      setError('Vui lòng điền đủ Tài khoản và Tên đăng nhập.');
      return;
    }
    if (!entry && !password) {
      setError('Vui lòng nhập mật khẩu cho tài khoản mới.');
      return;
    }
    setLoading(true);
    setError(null);
    const err = await onSave({
      id: entry?.id,
      account: account.trim(),
      name: name.trim(),
      ...(password ? { password } : {}), // only a newly typed password is ever sent
      aliases,
      description: description.trim(),
      tags,
      url: url.trim(),
    });
    setLoading(false);
    if (err) setError(err);
    else onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fadeIn">
      <div role="dialog" aria-modal="true" aria-labelledby="entry-title" className="w-full max-w-lg bg-white border border-slate-200 rounded-xl shadow-2xl overflow-hidden max-h-[92vh] flex flex-col">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <h2 id="entry-title" className="text-base font-semibold text-slate-900">
            {entry ? 'Chỉnh sửa tài khoản' : 'Thêm tài khoản mới'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng hộp thoại"
            className="w-8 h-8 rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-800 flex items-center justify-center transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="p-6 space-y-4 overflow-y-auto">
          {error && (
            <div role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="em-account" className={label}>Tài khoản / Ứng dụng *</label>
              <input id="em-account" type="text" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="VD: Facebook, ETAP…" className={field} />
            </div>
            <div>
              <label htmlFor="em-name" className={label}>Tên đăng nhập / Email *</label>
              <input id="em-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="user@example.invalid" className={`${field} font-mono`} />
            </div>
          </div>

          <div>
            <label htmlFor="em-pw" className={label}>Mật khẩu {entry ? '' : '*'}</label>
            <input
              id="em-pw"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={entry ? 'Để trống = giữ mật khẩu cũ' : 'Nhập mật khẩu…'}
              className={`${field} font-mono`}
            />
            {entry && <p className="text-[11px] text-slate-500 mt-1">Chỉ nhập khi muốn đổi mật khẩu.</p>}
          </div>

          <ChipInput label="Bí danh tìm kiếm" noun="bí danh" values={aliases} onChange={setAliases} placeholder="VD: fb chính — gõ rồi nhấn Enter" />

          <div>
            <label htmlFor="em-desc" className={label}>Mô tả / Ghi chú</label>
            <textarea id="em-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Ghi chú về tài khoản…" className={field} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <ChipInput label="Thẻ (tag)" noun="tag" values={tags} onChange={setTags} placeholder="kỹ thuật, nội bộ" />
            <div>
              <label htmlFor="em-url" className={label}>URL / Host</label>
              <input id="em-url" type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className={`${field} font-mono`} />
              <p className="text-[11px] text-slate-500 mt-1">Chỉ lưu và sao chép, không tự mở.</p>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-100">
            <button type="button" onClick={onClose} className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-semibold transition">
              Hủy
            </button>
            <button type="submit" disabled={loading} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 transition shadow-sm">
              <Check className="w-4 h-4" />
              {loading ? 'Đang lưu…' : 'Lưu vào két sắt'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
