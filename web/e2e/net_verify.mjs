// WebView2 / process-tree network verification (SYNTHETIC ONLY; observation, no firewall changes).
// Samples every TCP connection and UDP endpoint owned by the whole app process tree for DURATION seconds while the app
// goes through: startup, Welcome, unlocked Chat, a few searches, Quick Access, idle. Also diffs the Windows DNS client
// cache before/after (any name resolved by anything on the machine in that window; the app's own names would show up).
// Only the QA harness' own loopback CDP port is excluded. Result: net_verify_<label>.json
// Usage (from web/): node e2e/net_verify.mjs --exe <QA exe> --label <name> --out <dir> [--duration 180]
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
const DURATION = Number(arg('duration', '180'));
const PORT = 9333;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PS1 = path.join(HERE, 'win.ps1');
const PW = 'Synthetic-Net-Passphrase-1!';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ps = (action, a1 = '', a2 = '') => execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS1, '-Action', action, '-Arg1', a1, '-Arg2', a2], { encoding: 'utf8', timeout: 60000 }).trim();
const dns = () => { try { return new Set(JSON.parse(execFileSync('powershell', ['-NoProfile', '-Command', 'Get-DnsClientCache | Select-Object -ExpandProperty Entry | ConvertTo-Json -Compress'], { encoding: 'utf8' }) || '[]')); } catch { return new Set(); } };
fs.mkdirSync(OUT, { recursive: true });

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-net-'));
const local = path.join(root, 'local');
fs.mkdirSync(local, { recursive: true });
const vault = path.join(root, 'net.pvault');
const env = { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'wv') };

const dnsBefore = dns();
const t0 = Date.now();
const child = spawn(EXE, [], { env, stdio: 'ignore' });
let browser;
for (let i = 0; i < 80 && !browser; i++) { await sleep(500); try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* wait */ } }
if (!browser) { child.kill(); throw new Error('CDP not up'); }
let main, quick;
for (let i = 0; i < 60 && !(main && quick); i++) { for (const p of browser.contexts().flatMap((c) => c.pages())) { if (p.url().includes('#quick')) quick = p; else if (p.url().includes('tauri.localhost')) main = p; } if (!(main && quick)) await sleep(500); }
const ipc = (m, p = {}) => main.evaluate(([a, b]) => window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: a, params: b }), [m, p]);

const seen = new Map();
const samples = [];
function sample(tag) {
  const tree = JSON.parse(ps('memtree', String(child.pid)) || '[]');  // memtree also tells the role (browser / network / gpu / renderer ...)
  const names = Object.fromEntries(tree.map((t) => [t.pid, `${t.name}(${t.role})`]));
  const net = JSON.parse(ps('tcp', tree.map((t) => t.pid).join(',')) || '[]');
  const foreign = net.filter((n) => !(n.local.endsWith(`:${PORT}`) || n.remote.endsWith(`:${PORT}`)));
  const info = (globalThis.__pinfo ||= new Map());
  for (const n of foreign) { if (!info.has(n.pid)) { try { info.set(n.pid, JSON.parse(ps('procinfo', String(n.pid)))); } catch { info.set(n.pid, {}); } } n.procInfo = info.get(n.pid);
    const k = `${names[n.pid] || n.pid}|${n.proto}|${n.local}|${n.remote}|${n.state}`; if (!seen.has(k)) seen.set(k, { ...n, process: names[n.pid], firstSeenS: Math.round((Date.now() - t0) / 1000), tag }); }
  samples.push({ tSec: Math.round((Date.now() - t0) / 1000), tag, processes: tree.length, sockets: net.length, foreign: foreign.length });
}

try {
  await main.getByRole('heading', { name: 'Chào mừng đến Personal Vault' }).waitFor({ timeout: 20000 });
  sample('welcome');
  await ipc('create', { path: vault, password: PW, demo: false });
  for (let i = 0; i < 5; i++) await ipc('save_entry', { entry_data: { account: `Net Synthetic ${i}`, name: `u${i}`, password: `CANARY_NET_${i}` } });
  await ipc('lock');
  await main.reload();
  await main.getByLabel('Master Password').fill(PW);
  await main.getByRole('button', { name: 'Mở khóa', exact: true }).click();
  await main.getByLabel('Câu hỏi').waitFor({ timeout: 20000 });
  const end = t0 + DURATION * 1000;
  let i = 0;
  while (Date.now() < end) {
    const phase = i < 4 ? 'chat-active' : i < 8 ? 'quick-access' : 'idle';
    if (phase === 'chat-active') { await main.getByLabel('Câu hỏi').fill(`net synthetic ${i}`); await main.getByLabel('Câu hỏi').press('Enter'); }
    if (phase === 'quick-access' && i === 4) { ps('hotkey'); await sleep(1200); try { await quick.getByRole('combobox').fill('net'); } catch { /* window may not be visible */ } }
    if (phase === 'idle' && i === 8) { try { await quick.keyboard.press('Escape'); } catch { /* ignore */ } }
    sample(phase);
    i++;
    await sleep(3000);
  }
  sample('final');
} finally {
  const dnsAfter = dns();
  const newDns = [...dnsAfter].filter((x) => !dnsBefore.has(x));
  const report = {
    label: LABEL, exe: EXE, durationS: DURATION, samples: samples.length, startedAt: new Date(t0).toISOString(),
    foreignSockets: [...seen.values()], dnsNewEntriesOnMachineDuringWindow: newDns,
    note: 'Sampled observation, not an OS-enforced network deny. Foreign = anything except the QA harness loopback CDP port. DNS entries are machine-wide, so unrelated processes may appear.',
  };
  fs.writeFileSync(path.join(OUT, `net_verify_${LABEL}.json`), JSON.stringify(report, null, 2));
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await browser.close().catch(() => {});
  try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
  console.log(`net verify ${LABEL}: ${samples.length} samples over ${DURATION}s; non-harness sockets observed: ${report.foreignSockets.length}; new DNS entries machine-wide: ${newDns.length}`);
  for (const f of report.foreignSockets) console.log('  ', JSON.stringify(f));
}
