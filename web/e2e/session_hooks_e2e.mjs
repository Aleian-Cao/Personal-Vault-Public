// EXPERIMENTAL-build EXE E2E (QA hooks only; the release sidecar has no hooks). SYNTHETIC ONLY.
//  H1 simulated Windows session lock (lock file)  -> backend locks, UI follows, no stale data, re-unlock works
//  H2 simulated suspend/resume (wall-clock skew)  -> same
//  H3 idle soak with a short idle window (PVAULT_TEST_IDLE_SECONDS): N idle-only runs + runs with activity, with attribution of
//     every idle-window refresh from the backend's own activity log AND the page's event counter. A run that does not lock is a FAIL.
// This validates the plumbing (watcher thread -> lock -> UI poll) and the idle logic under repetition; the REAL OS detector is covered
// by the Windows Sandbox run (qa-sandbox) and the 300 s release run (idle_e2e.mjs).
// Usage (from web/): node e2e/session_hooks_e2e.mjs --exe <QA exe next to the EXPERIMENTAL sidecar> --out <dir> [--idle 40] [--runs 5]
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const EXE = path.resolve(arg('exe'));
const OUT = path.resolve(arg('out', '.'));
const IDLE = Number(arg('idle', '40'));
const RUNS = Number(arg('runs', '5'));
const PORT = 9333;
const PW = 'Synthetic-Hooks-Passphrase-1!';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const rep = { exe: EXE, idleSeconds: IDLE, startedAt: new Date().toISOString(), steps: [], soak: [] };
const rec = (name, ok, detail = '') => { rep.steps.push({ name, status: ok ? 'PASS' : 'FAIL', detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`); return ok; };

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-hooks-'));
const local = path.join(root, 'local');
fs.mkdirSync(local, { recursive: true });
const vault = path.join(root, 'hooks.pvault');
const lockFile = path.join(root, 'lock.flag');
const suspendFile = path.join(root, 'suspend.flag');
const env = { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'wv'), PVAULT_TEST_IDLE_SECONDS: String(IDLE),
  PVAULT_TEST_LOCK_FILE: lockFile, PVAULT_TEST_SUSPEND_FILE: suspendFile };
const child = spawn(EXE, [], { env, stdio: 'ignore' });

let browser;
for (let i = 0; i < 80 && !browser; i++) { await sleep(500); try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* wait */ } }
if (!browser) { child.kill(); throw new Error('CDP not up'); }
const ctx = browser.contexts()[0];
await ctx.addInitScript(() => {
  const real = window.setTimeout.bind(window);
  window.setTimeout = (fn, ms, ...a) => (ms === 300000 ? 0 : real(fn, ms, ...a)); // UI's own idle timer off: only the sidecar may lock
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
const unlockUi = async () => {
  await main.getByLabel('Master Password').fill(PW);
  await main.getByRole('button', { name: 'Mở khóa', exact: true }).click();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
};
const waitState = async (pred, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (pred(await state())) return (Date.now() - t0) / 1000; await sleep(500); } return null; };
const unlockedHeadingGone = (name) => main.getByRole('heading', { name }).waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false);

try {
  await main.getByRole('heading', { name: 'Chào mừng đến Personal Vault' }).waitFor({ timeout: 20000 });
  await ipc('create', { path: vault, password: PW, demo: false });
  await ipc('save_entry', { entry_data: { account: 'Hooks Synthetic', name: 'hooks.user', password: 'CANARY_HOOKS_PW' } });
  await ipc('lock');
  await main.reload();
  await unlockUi();
  rec('H0 setup: hooks active in the experimental sidecar (debug_activity allowed)', (await ipc('debug_activity')).ok === true);

  // H1 simulated session lock
  fs.writeFileSync(lockFile, '1');
  const t1 = await waitState((s) => s !== 'unlocked', 8000);
  rec(`H1a backend locked by the (simulated) session lock in ${t1}s`, t1 !== null && t1 <= 4);
  rec('H1b UI followed to the Unlock screen with no user action', await unlockedHeadingGone('Mở khóa két sắt'));
  const calls = await Promise.all(['chat_search', 'get_entries', 'reveal'].map(async (m) => [m, await ipc(m, m === 'chat_search' ? { query: 'hooks' } : m === 'reveal' ? { entry_id: 'x' } : {})]));
  rec('H1c IPC refused while locked', calls.every(([, r]) => !r.ok && /locked/i.test(r.err)));
  rec('H1d no secret / card left in the DOM', (await main.getByRole('article').count()) === 0 && !(await main.content()).includes('CANARY_HOOKS'));
  fs.rmSync(lockFile);
  await sleep(1500);
  await unlockUi();
  await main.getByLabel('Câu hỏi').fill('hooks synthetic'); await main.getByLabel('Câu hỏi').press('Enter');
  rec('H1e after the session is "unlocked" again, the master password reopens the vault with data intact', await main.getByRole('article', { name: 'Hooks Synthetic' }).waitFor({ timeout: 10000 }).then(() => true).catch(() => false));

  // H2 simulated suspend/resume
  fs.writeFileSync(suspendFile, '60');
  const t2 = await waitState((s) => s !== 'unlocked', 8000);
  rec(`H2a backend locked by the (simulated) suspend/resume gap in ${t2}s`, t2 !== null && t2 <= 4);
  rec('H2b UI followed to the Unlock screen', await unlockedHeadingGone('Mở khóa két sắt'));
  await unlockUi();

  // H3 idle soak
  for (let run = 1; run <= RUNS + 2; run++) {
    const withActivity = run > RUNS; // the last two runs include one real input at IDLE-5 s that must push the lock out (an input <30 s after the last touch is NOT forwarded by the UI throttle, so it cannot extend the window: that was the first, mistaken expectation)
    await main.evaluate(() => { window.__act = []; });
    const act0 = (await ipc('debug_activity')).res;
    const tStart = Date.now();
    let activityAt = null;
    if (withActivity) { await sleep((IDLE - 5) * 1000); await main.keyboard.press('Shift'); activityAt = (Date.now() - tStart) / 1000; } // > 30 s after the last forwarded touch (UI throttle) and < IDLE
    let locked = null;
    for (let i = 0; i < 240 && locked === null; i++) { if ((await state()) !== 'unlocked') locked = (Date.now() - tStart) / 1000; else await sleep(500); }
    const act = (await ipc('debug_activity')).res;
    const refreshes = act.events.filter(([t]) => t > act0.now).map(([t, k]) => `${t}:${k}`);
    const pageEvents = (await main.evaluate(() => window.__act || [])).filter(([, , trusted]) => trusted).length;
    const expect = IDLE + (activityAt ?? 0);
    const ok = locked !== null && Math.abs(locked - expect) <= 6;
    rep.soak.push({ run, withActivity, lockedAfterS: locked, expectedS: expect, refreshesDuringRun: refreshes, trustedPageEvents: pageEvents });
    rec(`H3.${run} ${withActivity ? 'activity at ' + activityAt.toFixed(0) + ' s, ' : ''}backend locked after ${locked?.toFixed(1)} s (expected ~${expect.toFixed(0)} s); refreshes: ${refreshes.length ? refreshes.join(' ') : 'none'}; real page events: ${pageEvents}`, ok);
    await main.getByRole('heading', { name: 'Mở khóa két sắt' }).waitFor({ timeout: 15000 }).catch(() => {});
    await unlockUi();
  }
} catch (e) {
  rec('UNEXPECTED ERROR (the run did not complete): ' + String((e && e.stack) || e).slice(0, 600), false);
} finally {
  rep.finishedAt = new Date().toISOString();
  rep.summary = { PASS: rep.steps.filter((s) => s.status === 'PASS').length, FAIL: rep.steps.filter((s) => s.status === 'FAIL').length };
  fs.writeFileSync(path.join(OUT, 'session_hooks_report.json'), JSON.stringify(rep, null, 2));
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await browser.close().catch(() => {});
  try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
  console.log(`session hooks E2E: ${rep.summary.PASS} PASS / ${rep.summary.FAIL} FAIL`);
  process.exit(rep.summary.FAIL ? 1 : 0);
}
