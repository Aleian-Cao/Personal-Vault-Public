import React, { useState } from 'react';
import { host } from '../lib/host';
import { errorText } from '../lib/errors';
import { TriangleAlert, FolderOpen, RefreshCw, Plus } from 'lucide-react';
import { ScreenShell, ErrorNote, PathChip, primaryBtn, secondaryBtn } from './ScreenShell';

interface Props {
  /** The remembered vault path that no longer exists. */
  path: string;
  onPicked: (path: string) => void;
  onRetry: () => void;
  onCreate: () => void;
}

export const RecoveryScreen: React.FC<Props> = ({ path, onPicked, onRetry, onCreate }) => {
  const [error, setError] = useState<string | null>(null);

  const pick = async () => {
    try {
      const p = await host().pickVaultToOpen();
      if (p) onPicked(p);
    } catch (e) {
      setError(errorText(e, 'Không mở được hộp thoại chọn file.'));
    }
  };

  return (
    <ScreenShell>
      <div className="flex items-start gap-3">
        <TriangleAlert className="w-6 h-6 text-amber-600 shrink-0" />
        <div>
          <h2 className="text-lg font-bold text-slate-900 tracking-tight">Không tìm thấy file két sắt</h2>
          <p className="text-xs text-slate-600 leading-relaxed mt-1">
            File có thể đã bị di chuyển, đổi tên hoặc nằm trên ổ đĩa chưa kết nối. Ứng dụng sẽ không tự tạo mới hay ghi đè.
          </p>
        </div>
      </div>

      <div className="my-4"><PathChip path={path} /></div>

      <div className="space-y-3">
        <button type="button" onClick={pick} className={primaryBtn}>
          <FolderOpen className="w-4 h-4" />
          Chọn file két sắt khác…
        </button>
        <button type="button" onClick={onRetry} className={secondaryBtn}>
          <RefreshCw className="w-4 h-4 text-slate-500" />
          Kiểm tra lại
        </button>
        <button type="button" onClick={onCreate} className={secondaryBtn}>
          <Plus className="w-4 h-4 text-slate-500" />
          Tạo két sắt mới
        </button>
      </div>

      {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}
    </ScreenShell>
  );
};
