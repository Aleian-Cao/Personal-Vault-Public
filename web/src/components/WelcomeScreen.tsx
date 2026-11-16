import React, { useState } from 'react';
import { host } from '../lib/host';
import { errorText } from '../lib/errors';
import { Plus, FolderOpen, Sparkles } from 'lucide-react';
import { ScreenShell, ErrorNote } from './ScreenShell';

interface Props {
  onCreate: () => void;
  onPicked: (path: string) => void;
  onEntered: () => void;
}

export const WelcomeScreen: React.FC<Props> = ({ onCreate, onPicked, onEntered }) => {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const openExisting = async () => {
    setError(null);
    try {
      const p = await host().pickVaultToOpen();
      if (p) onPicked(p);
    } catch (e) {
      setError(errorText(e, 'Không mở được hộp thoại chọn file.'));
    }
  };

  const demo = async () => {
    setBusy(true);
    setError(null);
    const res = await host().openDemo();
    setBusy(false);
    if (res.success) onEntered();
    else setError(errorText(res.error, 'Không thể mở dữ liệu mẫu.'));
  };

  return (
    <ScreenShell>
      <h2 className="sr-only">Chào mừng đến Personal Vault</h2>
      <button type="button" onClick={onCreate} className="w-full py-3.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-base font-semibold flex items-center justify-center gap-2 shadow-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
        <Plus className="w-5 h-5" />
        Tạo két sắt mới
      </button>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" onClick={openExisting} title="Chọn file .pvault đã tạo trước đó hoặc bản sao lưu" className="py-2.5 px-3 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-sm font-semibold flex items-center justify-center gap-2 transition focus:outline-none focus:ring-2 focus:ring-blue-500">
          <FolderOpen className="w-4 h-4 text-slate-500" />
          Mở két sắt có sẵn
        </button>
        <button type="button" onClick={demo} disabled={busy} title="500 tài khoản giả lập, tách biệt hoàn toàn khỏi két sắt của bạn" className="py-2.5 px-3 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-60 text-slate-700 text-sm font-semibold flex items-center justify-center gap-2 transition focus:outline-none focus:ring-2 focus:ring-blue-500">
          <Sparkles className="w-4 h-4 text-blue-600" />
          Dùng thử demo
        </button>
      </div>

      {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}
    </ScreenShell>
  );
};
