// Control experiment (no admin, no changes to the machine): does a BARE WebView2 runtime process, with a throw-away profile and
// no app / no sidecar of ours, also attempt outbound connections ~60-80 s after start on THIS machine?
// Same sampler as net_verify.mjs (non-loopback TCP of the process tree, with role/start time/command line).
// Usage (from web/): node e2e/bare_webview2_probe.mjs --label bare1 --out <dir> [--duration 240] [--args "--disable-gpu ..."]
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const LABEL = arg('label', 'bare');
const OUT = path.resolve(arg('out', '.'));
const DURATION = Number(arg('duration', '240'));
const EXTRA = (arg('args', '') || '').split(' ').filter(Boolean);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PS1 = path.join(HERE, 'win.ps1');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ps = (action, a1 = '', a2 = '') => execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS1, '-Action', action, '-Arg1', a1, '-Arg2', a2], { encoding: 'utf8', timeout: 60000 }).trim();
fs.mkdirSync(OUT, { recursive: true });

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-bare-'));
const reg = execFileSync('powershell', ['-NoProfile', '-Command', "(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}').pv"], { encoding: 'utf8' }).trim();
const exe = `C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\${reg}\\msedgewebview2.exe`;
if (!fs.existsSync(exe)) throw new Error('WebView2 runtime exe not found: ' + exe);
// Same Chromium switches the app uses (without the debug port), so any difference is not caused by our flags being absent.
const flags = ['--headless=new', `--user-data-dir=${path.join(root, 'ud')}`, '--no-first-run', '--disable-background-networking', '--disable-component-update',
  '--disable-domain-reliability', '--disable-sync', '--no-pings', '--disable-breakpad', '--no-proxy-server', ...EXTRA, 'about:blank'];
const t0 = Date.now();
const child = spawn(exe, flags, { stdio: 'ignore' });
await sleep(1500);

const seen = new Map(); const samples = []; const info = new Map();
while (Date.now() - t0 < DURATION * 1000) {
  const tree = JSON.parse(ps('memtree', String(child.pid)) || '[]');
  const roles = Object.fromEntries(tree.map((t) => [t.pid, `${t.name}(${t.role})`]));
  const net = JSON.parse(ps('tcp', tree.map((t) => t.pid).join(',')) || '[]');
  const foreign = net.filter((n) => !/^(127\.|\[?::1)/.test(n.remote) && !n.remote.startsWith('0.0.0.0'));
  for (const n of foreign) {
    if (!info.has(n.pid)) { try { info.set(n.pid, JSON.parse(ps('procinfo', String(n.pid)))); } catch { info.set(n.pid, {}); } }
    const k = `${n.pid}|${n.local}|${n.remote}|${n.state}`;
    if (!seen.has(k)) seen.set(k, { ...n, process: roles[n.pid], firstSeenS: Math.round((Date.now() - t0) / 1000), procInfo: info.get(n.pid) });
  }
  samples.push({ tSec: Math.round((Date.now() - t0) / 1000), processes: tree.length, sockets: net.length, foreign: foreign.length });
  await sleep(3000);
}
const report = { label: LABEL, exe, runtimeVersion: reg, flags, durationS: DURATION, samples: samples.length, foreignSockets: [...seen.values()],
  note: 'Bare WebView2 runtime, headless, throw-away profile, no app/sidecar. Observation only.' };
fs.writeFileSync(path.join(OUT, `bare_webview2_${LABEL}.json`), JSON.stringify(report, null, 2));
try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ }
console.log(`bare WebView2 ${LABEL} (${reg}): ${samples.length} samples over ${DURATION}s; foreign sockets: ${report.foreignSockets.length}`);
for (const f of report.foreignSockets) console.log('  ', JSON.stringify({ at: f.firstSeenS, proc: f.process, remote: f.remote, state: f.state }));
