import React, { useState } from 'react';
import { host } from '../lib/host';
import { errorText } from '../lib/errors';
import { Lock, KeyRound, FolderOpen } from 'lucide-react';
import { ScreenShell, ErrorNote, PathChip, primaryBtn, inputCls, labelCls } from './ScreenShell';

interface UnlockScreenProps {
  /** Vault to unlock (the remembered one, or one the user just picked). */
  path: string;
  onUnlocked: () => void;
}

export const UnlockScreen: React.FC<UnlockScreenProps> = ({ path: initialPath, onUnlocked }) => {
  const [path, setPath] = useState(initialPath);
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const chooseAnother = async () => {
    try {
      const p = await host().pickVaultToOpen();
      if (p) {
        setPath(p);
        setError(null);
      }
    } catch (e) {
      setError(errorText(e, 'Không mở được hộp thoại chọn file.'));
    }
  };

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError('Vui lòng nhập Master Password.');
      return;
    }
    setLoading(true);
    setError(null);
    const res = await host().unlock(password, path);
    setLoading(false);
    if (res.success) onUnlocked();
    else setError(errorText(res.error, 'Mật khẩu không đúng hoặc file két sắt không hợp lệ.'));
  };

  return (
    <ScreenShell>
      <h2 className="sr-only">Mở khóa két sắt</h2>
      <div className="mb-4 space-y-2">
        <PathChip path={path} />
        <button type="button" onClick={chooseAnother} className="text-xs font-semibold text-blue-600 hover:text-blue-800 flex items-center gap-1.5">
          <FolderOpen className="w-3.5 h-3.5" />
          Chọn két sắt khác…
        </button>
      </div>

      <form onSubmit={handleUnlock} className="space-y-4">
        <div>
          <label htmlFor="ul-pw" className={labelCls}>Master Password</label>
          <div className="relative">
            <input
              id="ul-pw" type="password" autoFocus value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nhập mật khẩu mở khóa…"
              className={inputCls}
            />
            <KeyRound className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
          </div>
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}

        <button type="submit" disabled={loading} className={primaryBtn}>
          <Lock className="w-4 h-4" />
          {loading ? 'Đang giải mã…' : 'Mở khóa'}
        </button>
      </form>
    </ScreenShell>
  );
};
