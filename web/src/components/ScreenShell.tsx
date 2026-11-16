import React from 'react';

/** Brand lockup + centered card shared by Welcome / Create / Unlock / Recovery / Error. */
export const ScreenShell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="min-h-screen bg-[#F9FAFB] flex flex-col justify-center items-center px-4 sm:px-6">
    <div className="w-full max-w-md">
      <div className="flex flex-col items-center mb-6">
        <img src="/logo-mark.png" alt="Personal Vault" className="w-20 h-20 object-contain mb-2" />
        <h1 className="text-xl font-bold text-slate-900 tracking-tight">Personal Vault</h1>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 sm:p-8">{children}</div>

    </div>
  </div>
);

export const ErrorNote: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
    {children}
  </div>
);

export const splitPath = (p: string) => {
  const i = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
  return { file: p.slice(i + 1), dir: i >= 0 ? p.slice(0, i) : '' };
};

export const PathChip: React.FC<{ path: string }> = ({ path }) => {
  const { file, dir } = splitPath(path);
  return (
    <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg min-w-0">
      <span className="block text-sm font-semibold text-slate-900 font-mono truncate">{file}</span>
      <span className="block text-[11px] text-slate-500 font-mono truncate mt-0.5" title={dir}>{dir}</span>
    </div>
  );
};

export const primaryBtn =
  'w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition shadow-sm';
export const secondaryBtn =
  'w-full py-2.5 px-4 bg-white border border-slate-200 hover:bg-slate-50 disabled:opacity-60 text-slate-700 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition';
export const inputCls =
  'w-full px-3 py-2.5 text-sm rounded-lg border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono';
export const labelCls = 'text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-1';
