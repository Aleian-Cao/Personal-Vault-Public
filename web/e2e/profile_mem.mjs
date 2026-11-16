// Memory profile of the whole desktop process tree per UI state (SYNTHETIC ONLY, temp profile dirs).
// Metrics per process: Working Set (counts shared pages in EVERY process that maps them), Private Bytes (commit),
// Private Working Set (resident pages that are not shared). Sum over the tree is reported for all three.
// Usage (from web/): node e2e/profile_mem.mjs --exe <QA exe with CDP port 9333> --label <name> --out <dir>
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const EXE = path.resolve(arg('exe'));
const LABEL = arg('label', 'run');
const OUT = path.resolve(arg('out', '.'));
const PORT = 9333;
const FAST = arg('fast', '') !== '';
const SETTLE = Number(arg('settle', FAST ? '5000' : '7000'));
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PS1 = path.join(HERE, 'win.ps1');
const PW = 'Synthetic-Profile-Passphrase-1!';
fs.mkdirSync(OUT, { recursive: true });

const ps = (action, a1 = '', a2 = '') =>
  execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS1, '-Action', action, '-Arg1', a1, '-Arg2', a2], { encoding: 'utf8', timeout: 60000 }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const QTITLE = 'Personal Vault - Quick Access';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-mem-'));
const local = path.join(root, 'local');
fs.mkdirSync(local, { recursive: true });
const vault = path.join(root, 'profile.pvault');
const env = { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'wv') };
const child = spawn(EXE, [], { env, stdio: 'ignore' });

let browser;
for (let i = 0; i < 80 && !browser; i++) { await sleep(500); try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* wait */ } }
if (!browser) { child.kill(); throw new Error('CDP not up'); }
let main, quick;
for (let i = 0; i < 60 && !(main && quick); i++) {
  for (const p of browser.contexts().flatMap((c) => c.pages())) { if (p.url().includes('#quick')) quick = p; else if (p.url().includes('tauri.localhost')) main = p; }
  if (!(main && quick)) await sleep(500);
}

const invoke = (page, method, params) => page.evaluate(([m, p]) => window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: m, params: p }), [method, params]);
const btn = (p, n, exact = false) => p.getByRole('button', { name: n, exact });

function sample(state) {
  const rows = JSON.parse(ps('memtree', String(child.pid)) || '[]');
  const sum = (k) => Math.round(rows.reduce((s, r) => s + (r[k] || 0), 0) * 10) / 10;
  const byRole = {};
  for (const r of rows) {
    const k = r.role;
    byRole[k] = byRole[k] || { n: 0, wsMB: 0, privateMB: 0, wsPrivateMB: 0 };
    byRole[k].n++; byRole[k].wsMB += r.wsMB; byRole[k].privateMB += r.privateMB; byRole[k].wsPrivateMB += r.wsPrivateMB || 0;
  }
  for (const v of Object.values(byRole)) for (const k of ['wsMB', 'privateMB', 'wsPrivateMB']) v[k] = Math.round(v[k] * 10) / 10;
  const rec = { state, processes: rows.length, wsMB: sum('wsMB'), privateMB: sum('privateMB'), wsPrivateMB: sum('wsPrivateMB'), byRole, rows };
  console.log(`${state.padEnd(34)} procs=${String(rows.length).padStart(2)}  WS=${String(rec.wsMB).padStart(6)} MB  Private=${String(rec.privateMB).padStart(6)} MB  PrivateWS=${String(rec.wsPrivateMB).padStart(6)} MB`);
  return rec;
}
const settleThenSample = async (state) => { await sleep(SETTLE); return sample(state); };

const report = { label: LABEL, exe: EXE, machine: { cpus: os.cpus().length, totalGB: Math.round(os.totalmem() / 2 ** 30) }, startedAt: new Date().toISOString(), samples: [] };
const add = (r) => report.samples.push(r);

try {
  await main.getByRole('heading', { name: 'Chào mừng đến Personal Vault' }).waitFor({ timeout: 20000 });
  add(await settleThenSample('1 welcome (no vault)'));

  await invoke(main, 'create', { path: vault, password: PW, demo: false });
  for (let i = 0; i < 20; i++) await invoke(main, 'save_entry', { entry_data: { account: `Profile Synthetic ${i}`, name: `user${i}`, password: `CANARY_PROF_${i}` } });
  await invoke(main, 'lock', {});
  await main.reload();
  await main.getByRole('heading', { name: 'Mở khóa két sắt' }).waitFor({ timeout: 20000 });
  add(await settleThenSample('2 locked (Unlock screen)'));

  await main.getByLabel('Master Password').fill(PW);
  const peak = { privateMB: 0, wsMB: 0 };
  const sampler = (async () => { for (let i = 0; i < 6; i++) { const rows = JSON.parse(ps('memtree', String(child.pid)) || '[]'); const sc = rows.filter((r) => r.role.startsWith('sidecar')); peak.privateMB = Math.max(peak.privateMB, sc.reduce((s, r) => s + r.privateMB, 0)); peak.wsMB = Math.max(peak.wsMB, sc.reduce((s, r) => s + r.wsMB, 0)); } })();
  await btn(main, 'Mở khóa', true).click();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
  await sampler;
  report.unlockPeakSidecar = peak;
  console.log(`sidecar peak during unlock (Argon2): Private=${peak.privateMB} MB WS=${peak.wsMB} MB`);
  add(await settleThenSample('3 unlocked, chat (20 entries)'));

  if (!FAST) {
  await main.getByLabel('Câu hỏi').fill('profile synthetic 7');
  await main.getByLabel('Câu hỏi').press('Enter');
  await main.getByRole('article').first().waitFor({ timeout: 10000 });
  add(await settleThenSample('4 chat with an answer card'));

  await btn(main, /Quản lý két sắt/).click();
  await main.getByText(/Tổng cộng: 20/).waitFor({ timeout: 10000 });
  add(await settleThenSample('5 manager (20 entries)'));
  }

  ps('hotkey');
  const t0 = Date.now(); let shown = false;
  while (Date.now() - t0 < 4000 && !shown) { shown = ps('winvisible', QTITLE) === 'True'; await sleep(250); }
  if (!shown) ps('showwin', QTITLE);
  await sleep(800);
  await quick.getByRole('combobox').fill('profile');
  add(await settleThenSample('6 Quick Access visible'));
  await quick.keyboard.press('Escape');
  add(await settleThenSample('7 Quick Access hidden'));

  if (!FAST) {
  await btn(main, /Khóa két sắt/).click();
  await invoke(main, 'open_demo', {});
  await main.reload();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
  await btn(main, /Quản lý két sắt/).click();
  await main.getByText('Tổng cộng: 500 tài khoản').waitFor({ timeout: 15000 });
  add(await settleThenSample('8 manager, demo 500 entries'));

  await btn(main, /Trò chuyện/).click();
  await main.getByLabel('Câu hỏi').fill('etap server 15');
  await main.getByLabel('Câu hỏi').press('Enter');
  await main.getByRole('article').first().waitFor({ timeout: 10000 });
  add(await settleThenSample('9 chat, demo 500 entries'));

  // idle trend: is anything still growing?
  await sleep(30000);
  add(sample('10 same state after +30 s idle'));
  }
} finally {
  report.finishedAt = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, `memory_profile_${LABEL}.json`), JSON.stringify(report, null, 2));
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await browser.close().catch(() => {});
  try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
}
