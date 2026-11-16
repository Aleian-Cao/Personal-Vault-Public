import React from 'react';
import type { ImportPreviewResult } from '../types';
import { X, Check, FileText, AlertTriangle, PlusCircle, Ban } from 'lucide-react';

interface ImportModalProps {
  fileName: string;
  /** Exactly one of preview / error is set. */
  preview: ImportPreviewResult | null;
  error: string | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

const MAX_ROWS = 200;

export const ImportModal: React.FC<ImportModalProps> = ({ fileName, preview, error, busy, onClose, onConfirm }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fadeIn">
    <div role="dialog" aria-modal="true" aria-labelledby="import-title" className="w-full max-w-2xl bg-white border border-slate-200 rounded-xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-5 h-5 text-blue-600 shrink-0" />
          <h2 id="import-title" className="text-base font-semibold text-slate-900">Xem trước dữ liệu nhập</h2>
          <span className="text-xs font-mono text-slate-500 truncate">{fileName}</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Đóng hộp thoại" className="w-8 h-8 rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-800 flex items-center justify-center transition">
          <X className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div className="p-6">
          <div role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-start gap-2">
            <Ban className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
          <p className="text-xs text-slate-500 mt-3">
            Hỗ trợ: .txt, .csv, .json, .ps1/.bat (chỉ đọc dòng chú thích dữ liệu, không bao giờ thực thi).
          </p>
        </div>
      )}

      {preview && (
        <>
          <div className="px-6 py-3 bg-slate-50 border-b border-slate-100 flex flex-wrap gap-3 text-xs font-medium">
            <span className="text-slate-600 py-0.5">Tổng: <strong className="text-slate-900">{preview.total}</strong></span>
            <span className="text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 flex items-center gap-1">
              <PlusCircle className="w-3.5 h-3.5" />
              Mới: <strong>{preview.newCount}</strong>
            </span>
            <span className="text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" />
              Trùng: <strong>{preview.duplicateCount}</strong>
            </span>
            <span className="text-red-700 bg-red-50 px-2 py-0.5 rounded border border-red-200 flex items-center gap-1">
              <Ban className="w-3.5 h-3.5" />
              Không hợp lệ: <strong>{preview.invalidCount}</strong>
            </span>
          </div>

          <div className="flex-1 overflow-y-auto p-6">
            <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    <th className="px-4 py-2.5">Tài khoản</th>
                    <th className="px-4 py-2.5">Tên đăng nhập</th>
                    <th className="px-4 py-2.5">Trạng thái</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-sm">
                  {preview.records.slice(0, MAX_ROWS).map((r, i) => (
                    <tr key={i} className="hover:bg-slate-50 transition">
                      <td className="px-4 py-2.5 font-medium text-slate-900">{r.entry.account}</td>
                      <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{r.entry.name}</td>
                      <td className="px-4 py-2.5 text-xs">
                        {r.status === 'new' ? (
                          <span className="inline-flex px-2 py-0.5 rounded-full font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">Sẽ nhập</span>
                        ) : (
                          <span className="inline-flex px-2 py-0.5 rounded-full font-medium bg-amber-50 text-amber-700 border border-amber-200">Bỏ qua (đã có)</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.records.length > MAX_ROWS && (
              <p className="text-xs text-slate-500 mt-2">Hiển thị {MAX_ROWS}/{preview.records.length} dòng đầu; tất cả đều được xử lý.</p>
            )}
          </div>
        </>
      )}

      <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">Chưa có gì được ghi vào két sắt cho đến khi bạn xác nhận.</p>
        <div className="flex items-center gap-3 shrink-0">
          <button type="button" onClick={onClose} className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-semibold transition">
            {preview ? 'Hủy bỏ' : 'Đóng'}
          </button>
          {preview && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy || preview.newCount === 0}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 transition shadow-sm"
            >
              <Check className="w-4 h-4" />
              Nhập {preview.newCount} tài khoản
            </button>
          )}
        </div>
      </div>
    </div>
  </div>
);
