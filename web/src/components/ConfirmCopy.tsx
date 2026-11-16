import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ShieldAlert } from 'lucide-react';

/** Explicit confirmation before a password goes to the clipboard (SPEC FR-07). Asked every time, never remembered. */
const Dialog: React.FC<{ account: string; onResult: (ok: boolean) => void }> = ({ account, onResult }) => {
  const okRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onResult(false); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onResult]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="cc-title" className="w-full max-w-sm bg-white border border-slate-200 rounded-xl shadow-2xl p-5 space-y-3">
        <div className="flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-2">
            <h2 id="cc-title" className="text-sm font-bold text-slate-900">Sao chép mật khẩu?</h2>
            <p className="text-xs text-slate-700">
              «{account}» sẽ nằm trong clipboard và tự xóa sau 20 giây nếu clipboard chưa bị thay đổi.
            </p>
            <p className="text-xs text-amber-700">
              Lịch sử clipboard của Windows (Win+V) hoặc đồng bộ đám mây, nếu đang bật, có thể vẫn giữ bản sao.
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={() => onResult(false)} className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold">
            Hủy
          </button>
          <button ref={okRef} type="button" onClick={() => onResult(true)} className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-sm">
            Sao chép
          </button>
        </div>
      </div>
    </div>
  );
};

export function useConfirmCopy() {
  const [req, setReq] = useState<{ account: string; resolve: (ok: boolean) => void } | null>(null);
  const confirm = useCallback(
    (account: string) => new Promise<boolean>((resolve) => setReq({ account, resolve })),
    [],
  );
  const dialog = req ? (
    <Dialog account={req.account} onResult={(ok) => { req.resolve(ok); setReq(null); }} />
  ) : null;
  return { confirm, dialog };
}
