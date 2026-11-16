// Probe (QA only, SYNTHETIC): what does the Quick Access page know after the window is shown by Win32 ShowWindow (no focus, no hotkey event)?
// Usage (from web/): node e2e/quick_show_probe.mjs --exe <QA exe> --out <dir>
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const EXE = path.resolve(arg('exe'));
const OUT = path.resolve(arg('out', '.'));
const PS1 = path.join(path.dirname(fileURLToPath(import.meta.url)), 'win.ps1');
const ps = (a, x = '') => execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS1, '-Action', a, '-Arg1', x], { encoding: 'utf8', timeout: 60000 }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });
const PW = 'Synthetic-Probe-Passphrase-1!';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-qprobe-'));
const local = path.join(root, 'local'); fs.mkdirSync(local, { recursive: true });
const child = spawn(EXE, [], { env: { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'wv') }, stdio: 'ignore' });
let browser;
for (let i = 0; i < 80 && !browser; i++) { await sleep(500); try { browser = await chromium.connectOverCDP('http://127.0.0.1:9333'); } catch { /* wait */ } }
const out = { steps: [] };
try {
  const ctx = browser.contexts()[0];
  const find = (q) => ctx.pages().find((p) => p.url().includes('tauri.localhost') && (q ? p.url().includes('#quick') : !p.url().includes('#quick')));
  let main, quick;
  for (let i = 0; i < 60 && !(main && quick); i++) { main = find(false); quick = find(true); if (!(main && quick)) await sleep(500); }
  const ipc = (m, p = {}) => main.evaluate(async ([a, b]) => { try { return { ok: true, res: await window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: a, params: b }) }; } catch (e) { return { ok: false, err: String(e) }; } }, [m, p]);
  await main.getByRole('heading', { name: 'Chào mừng đến Personal Vault' }).waitFor({ timeout: 20000 });
  await ipc('create', { path: path.join(root, 'p.pvault'), password: PW, demo: false });
  await ipc('save_entry', { entry_data: { account: 'Probe Synthetic', name: 'probe.user', password: 'CANARY_PROBE' } });
  await ipc('lock'); await main.reload();
  await main.getByLabel('Master Password').fill(PW);
  await main.getByRole('button', { name: 'Mở khóa', exact: true }).click();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
  const snap = (label) => quick.evaluate(() => ({ vis: document.visibilityState, focus: document.hasFocus(), text: document.body.innerText.slice(0, 80).replace(/\s+/g, ' '), combobox: !!document.querySelector('[role=combobox]') })).then((s) => out.steps.push({ label, ...s }));
  await snap('quick page, vault unlocked in main, window never shown');
  console.log(ps('showwin', 'Personal Vault - Quick Access'));
  for (const t of [300, 1000, 3000, 8000]) { await sleep(t === 300 ? 300 : t - (t === 1000 ? 300 : t === 3000 ? 1000 : 3000)); await snap(`after ShowWindow +${t} ms`); }
} finally {
  fs.writeFileSync(path.join(OUT, 'quick_show_probe.json'), JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out.steps, null, 1));
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await browser?.close().catch(() => {});
  try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
}
