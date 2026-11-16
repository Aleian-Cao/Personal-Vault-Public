import React, { useState } from 'react';
import { host } from '../lib/host';
import { errorText } from '../lib/errors';
import { ArrowLeft, FolderOpen, Plus } from 'lucide-react';
import { ScreenShell, ErrorNote, PathChip, primaryBtn, secondaryBtn, inputCls, labelCls } from './ScreenShell';

interface Props {
  onBack: () => void;
  onCreated: () => void;
}

const MIN_LEN = 12;
const CLOUD_SYNC = /onedrive|dropbox|google ?drive|icloud/i;

export const CreateVaultScreen: React.FC<Props> = ({ onBack, onCreated }) => {
  const [pw, setPw] = useState('');
  const [cf, setCf] = useState('');
  const [path, setPath] = useState<string | null>(null);
  const [touched, setTouched] = useState({ pw: false, cf: false });
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Validation is computed always but only *shown* after the user touched the field or submitted.
  const pwErr = pw.length < MIN_LEN ? `Mật khẩu chính cần tối thiểu ${MIN_LEN} ký tự.` : null;
  const cfErr = cf !== pw ? 'Mật khẩu xác nhận không khớp.' : null;
  const pathErr = path ? null : 'Chọn vị trí lưu file két sắt.';
  const showPw = submitted || touched.pw;
  const showCf = submitted || touched.cf;

  const pick = async () => {
    try {
      const p = await host().pickVaultToSave();
      if (p) setPath(p);
    } catch (e) {
      setError(errorText(e, 'Không mở được hộp thoại chọn vị trí lưu.'));
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    if (pwErr || cfErr || pathErr || !path) return;
    setBusy(true);
    const res = await host().createVault(pw, path);
    setBusy(false);
    if (res.success) onCreated();
    else setError(errorText(res.error, 'Không thể tạo két sắt.'));
  };

  return (
    <ScreenShell>
      <button type="button" onClick={onBack} className="text-xs font-semibold text-slate-500 hover:text-slate-800 flex items-center gap-1 mb-3">
        <ArrowLeft className="w-3.5 h-3.5" />
        Quay lại
      </button>
      <h2 className="text-lg font-bold text-slate-900 tracking-tight">Tạo két sắt mới</h2>
      <p className="text-xs text-slate-600 leading-relaxed mt-1 mb-5">
        Tạo file <code className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-800 font-mono">.pvault</code> trống, mã hóa bằng AES-256-GCM và Argon2id.
        Master Password không được lưu và không thể khôi phục nếu quên.
      </p>

      <form onSubmit={submit} noValidate className="space-y-4">
        <div>
          <label htmlFor="cv-pw" className={labelCls}>Master Password</label>
          <input
            id="cv-pw" type="password" autoFocus autoComplete="new-password" value={pw}
            onChange={(e) => setPw(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, pw: true }))}
            placeholder={`Tối thiểu ${MIN_LEN} ký tự`}
            aria-invalid={showPw && !!pwErr}
            className={inputCls}
          />
          {showPw && pwErr && <p role="alert" className="text-xs text-red-600 mt-1">{pwErr}</p>}
        </div>

        <div>
          <label htmlFor="cv-cf" className={labelCls}>Xác nhận Master Password</label>
          <input
            id="cv-cf" type="password" autoComplete="new-password" value={cf}
            onChange={(e) => setCf(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, cf: true }))}
            placeholder="Nhập lại mật khẩu"
            aria-invalid={showCf && !!cfErr}
            className={inputCls}
          />
          {showCf && cfErr && <p role="alert" className="text-xs text-red-600 mt-1">{cfErr}</p>}
        </div>

        <div>
          <span className={labelCls}>Vị trí lưu</span>
          {path && <div className="mb-2"><PathChip path={path} /></div>}
          <button type="button" onClick={pick} className={secondaryBtn}>
            <FolderOpen className="w-4 h-4 text-slate-500" />
            {path ? 'Đổi vị trí…' : 'Chọn vị trí lưu…'}
          </button>
          {submitted && pathErr && <p role="alert" className="text-xs text-red-600 mt-1">{pathErr}</p>}
          {path && CLOUD_SYNC.test(path) && (
            <p className="text-xs text-amber-700 mt-1">Thư mục này có vẻ được đồng bộ lên cloud. Nên lưu két sắt ở nơi không đồng bộ.</p>
          )}
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}

        <button type="submit" disabled={busy} className={primaryBtn}>
          <Plus className="w-4 h-4" />
          {busy ? 'Đang tạo…' : 'Tạo két sắt'}
        </button>
      </form>
    </ScreenShell>
  );
};
