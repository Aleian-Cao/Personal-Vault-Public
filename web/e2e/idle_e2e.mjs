// Real-EXE idle auto-lock E2E (5 real minutes). SYNTHETIC ONLY.
// Proves the BACKEND locks on its own: the UI's own 5-minute timer is disabled via an init script, so the only thing
// that can lock is the sidecar's idle timer; the UI then follows through its state poll. Also proves that activity
// resets the idle window and that the 3 s state poll itself does NOT count as activity.
// Usage (from web/): node e2e/idle_e2e.mjs --exe <QA exe> --out <dir>
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const EXE = path.resolve(arg('exe'));
const OUT = path.resolve(arg('out', '.'));
const PORT = 9333;
const PW = 'Synthetic-Idle-Passphrase-1!';
const IDLE_S = 300;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const rep = { exe: EXE, startedAt: new Date().toISOString(), steps: [], timeline: {} };
const rec = (name, ok, detail = '') => { rep.steps.push({ name, status: ok ? 'PASS' : 'FAIL', detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`); };

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-idle-'));
const local = path.join(root, 'local');
fs.mkdirSync(local, { recursive: true });
const vault = path.join(root, 'idle.pvault');
const env = { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'wv') };
const child = spawn(EXE, [], { env, stdio: 'ignore' });

let browser;
for (let i = 0; i < 80 && !browser; i++) { await sleep(500); try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* wait */ } }
if (!browser) { child.kill(); throw new Error('CDP not up'); }
const ctx = browser.contexts()[0];
// Disable ONLY the UI's own idle timer (setTimeout with exactly IDLE_MS) so the sidecar is the sole locker under test.
await ctx.addInitScript(() => {
  const real = window.setTimeout.bind(window);
  window.setTimeout = (fn, ms, ...a) => (ms === 300000 ? 0 : real(fn, ms, ...a));
  // attribute every activity event the page sees (so a reset by real mouse/keyboard input is visible in the report)
  window.__act = [];
  for (const ev of ['keydown', 'mousedown', 'mousemove', 'wheel']) window.addEventListener(ev, (e) => { if (window.__act.length < 2000) window.__act.push([Date.now(), ev, e.isTrusted]); }, { capture: true, passive: true });
});
let main;
for (let i = 0; i < 60 && !main; i++) { main = ctx.pages().find((p) => p.url().includes('tauri.localhost') && !p.url().includes('#quick')); if (!main) await sleep(500); }

const ipc = (method, params = {}) => main.evaluate(async ([m, p]) => {
  try { return { ok: true, res: await window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: m, params: p }) }; }
  catch (e) { return { ok: false, err: String(e) }; }
}, [method, params]);
const state = async () => (await ipc('startup_state')).res?.state;

try {
  await main.getByRole('heading', { name: 'Chào mừng đến Personal Vault' }).waitFor({ timeout: 20000 });
  await ipc('create', { path: vault, password: PW, demo: false });
  await ipc('save_entry', { entry_data: { account: 'Idle Synthetic', name: 'idle.user', password: 'CANARY_IDLE_PW' } });
  await ipc('lock');
  await main.reload(); // init script is active from here on
  await main.getByLabel('Master Password').fill(PW);
  await main.getByRole('button', { name: 'Mở khóa', exact: true }).click();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
  const t0 = Date.now();
  const at = (s) => sleep(Math.max(0, t0 + s * 1000 - Date.now()));
  rec('I1 unlocked into Chat; UI idle timer disabled (only the sidecar can lock)', (await state()) === 'unlocked');

  await at(120);
  rec('I2 t=120 s: still unlocked in backend and UI (state polls do not lock)', (await state()) === 'unlocked' && (await main.getByLabel('Câu hỏi').count()) === 1);

  await at(200);
  await main.keyboard.press('Shift'); // real input event in the page -> activity -> touch()
  const lastActivity = Date.now();
  rep.timeline.activityAtS = Math.round((lastActivity - t0) / 1000);
  rec('I3 t=200 s: user activity sent (resets the idle window)', true);

  await at(200 + 280);
  const stillOpen = (await state()) === 'unlocked';
  rec('I4 280 s after the activity (> 200 s since unlock, would have locked at 300 without it): still unlocked', stillOpen);

  let lockedAt = null;
  for (let i = 0; i < 90 && lockedAt === null; i++) { if ((await state()) !== 'unlocked') lockedAt = Date.now(); else await sleep(2000); }
  const idleS = lockedAt ? Math.round((lockedAt - lastActivity) / 100) / 10 : null;
  rep.timeline.backendLockedAfterIdleS = idleS;
  rec(`I5 backend locked by itself ${idleS} s after the last activity (expected ~${IDLE_S} s, tolerance +25 s: 1 s watcher tick, 30 s activity throttle)`,
    idleS !== null && idleS >= IDLE_S - 31 && idleS <= IDLE_S + 25, `idle=${idleS}s`);

  await main.getByRole('heading', { name: 'Mở khóa két sắt' }).waitFor({ timeout: 15000 }).then(() => rec('I6 UI followed the backend lock to the Unlock screen with no user action', true)).catch(() => rec('I6 UI followed the backend lock', false));
  rec('I7 no account card or secret left in the DOM', (await main.getByRole('article').count()) === 0 && !(await main.content()).includes('CANARY_IDLE'));

  const calls = await Promise.all(['chat_search', 'get_entries', 'search', 'reveal'].map(async (m) => [m, await ipc(m, m === 'chat_search' || m === 'search' ? { query: 'idle' } : m === 'reveal' ? { entry_id: 'x' } : {})]));
  const acts = await main.evaluate(() => window.__act || []).catch(() => []);
  const rel = acts.map(([t, ev, trusted]) => [Math.round((t - t0) / 1000), ev, trusted]);
  rep.timeline.activityEvents = rel.filter(([sec]) => sec > 205);  // everything after our own t=200 s keypress
  rec(`I8a page activity events after our own t=200 s keypress: ${rep.timeline.activityEvents.length}`, rep.timeline.activityEvents.length === 0, JSON.stringify(rep.timeline.activityEvents.slice(0, 8)));
  rec('I8 direct IPC after idle lock is refused (fail-closed, independent of the UI)', calls.every(([, r]) => !r.ok && /locked/i.test(r.err)), calls.map(([m, r]) => `${m}:${r.ok ? 'OK!' : 'locked'}`).join(' '));
} catch (e) {
  rec('UNEXPECTED ERROR (the run did not complete): ' + String((e && e.stack) || e).slice(0, 600), false);
} finally {
  if (rep.steps.length < 9 && !rep.steps.some((x) => x.status === 'FAIL')) rec('INCOMPLETE: only ' + rep.steps.length + ' of 9 steps ran', false);
  rep.finishedAt = new Date().toISOString();
  rep.summary = { PASS: rep.steps.filter((s) => s.status === 'PASS').length, FAIL: rep.steps.filter((s) => s.status === 'FAIL').length };
  fs.writeFileSync(path.join(OUT, 'idle_e2e_report.json'), JSON.stringify(rep, null, 2));
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await browser.close().catch(() => {});
  try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
  console.log(`idle E2E: ${rep.summary.PASS} PASS / ${rep.summary.FAIL} FAIL`);
  process.exit(rep.summary.FAIL ? 1 : 0);
}
