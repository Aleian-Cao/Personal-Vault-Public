// Real-EXE E2E (Windows). Drives the BUILT desktop candidate, not the browser preview:
//   fresh launch -> create empty vault (native Save dialog) -> add -> search -> edit(blank pw) -> native copy
//   -> lock -> reopen/unlock -> import -> Quick Access (real Ctrl+Alt+V) -> restart persistence
//   -> missing-vault recovery -> demo isolation -> process/network evidence.
// SYNTHETIC ONLY: runs with LOCALAPPDATA redirected to a temp dir; never touches real data.
// Usage (from web/): node e2e/exe_e2e.mjs --exe <PersonalVault.exe> --out <dir> [--shots <dir>]
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const EXE = path.resolve(arg('exe'));
const OUT = path.resolve(arg('out', '.'));
const SHOTS = path.resolve(arg('shots', path.join(OUT, 'shots')));
const PORT = 9333;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PS1 = path.join(HERE, 'win.ps1');
const PW = 'Synthetic-E2E-Passphrase-1!';
const T = 15000;
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });

const ps = (action, a1 = '', a2 = '') =>
  execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS1, '-Action', action, '-Arg1', a1, '-Arg2', a2],
    { encoding: 'utf8', timeout: 60000 }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha256 = (f) => execFileSync('powershell', ['-NoProfile', '-Command', `(Get-FileHash -Algorithm SHA256 '${f}').Hash`], { encoding: 'utf8' }).trim();

const report = { exe: EXE, exeSha256: sha256(EXE), startedAt: new Date().toISOString(), steps: [], metrics: {} };
function record(name, status, detail = '') {
  report.steps.push({ name, status, detail });
  console.log(`${status.padEnd(10)} ${name}${detail ? ' — ' + detail : ''}`);
}
async function step(name, fn) {
  try { const d = await fn(); record(name, 'PASS', typeof d === 'string' ? d : ''); return true; }
  catch (e) { record(name, 'FAIL', String(e?.message ?? e).split('\n')[0]); return false; }
}
function must(cond, msg) { if (!cond) throw new Error(msg); }

function shot(title, name) {
  const f = path.join(SHOTS, name);
  const r = ps('shot', title, f);
  must(r.startsWith('OK'), `screenshot ${name}: ${r}`);
  return f;
}

// ---------------------------------------------------------------- app lifecycle
async function launch(local) {
  fs.mkdirSync(local, { recursive: true });
  // Own WebView2 profile per run: a private browser process that honours the debug port (QA harness only).
  const env = { ...process.env, LOCALAPPDATA: local, WEBVIEW2_USER_DATA_FOLDER: path.join(local, 'webview2'),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${PORT}` };
  const t0 = Date.now();
  const child = spawn(EXE, [], { env, stdio: 'ignore' });
  let browser;
  for (let i = 0; i < 80 && !browser; i++) {
    await sleep(500);
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* not up yet */ }
  }
  if (!browser) { try { child.kill(); } catch { /* already gone */ } }
  must(browser, 'WebView2 CDP endpoint never came up');
  let main, quick;
  for (let i = 0; i < 60 && !(main && quick); i++) {
    for (const p of browser.contexts().flatMap((c) => c.pages())) {
      if (p.url().includes('#quick')) quick = p; else if (p.url().includes('tauri.localhost') || p.url().startsWith('http')) main = p;
    }
    if (!(main && quick)) await sleep(500);
  }
  must(main, 'main window page not found');
  return { child, browser, main, quick, t0 };
}

function alive(pid) { try { process.kill(pid, 0); return true; } catch { return false; } }

async function closeGracefully(app) {
  const pid = app.child.pid;
  execFileSync('powershell', ['-NoProfile', '-Command', `$p = Get-Process -Id ${pid} -ErrorAction SilentlyContinue; if ($p) { [void]$p.CloseMainWindow() }`]);
  for (let i = 0; i < 20 && alive(pid); i++) await sleep(500);
  const graceful = !alive(pid);
  if (!graceful) execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  await app.browser.close().catch(() => {});
  await sleep(1500);
  return graceful;
}

function sidecarsRunning() {
  const out = execFileSync('powershell', ['-NoProfile', '-Command', "(Get-Process pvault-sidecar -ErrorAction SilentlyContinue | Measure-Object).Count"], { encoding: 'utf8' });
  return parseInt(out.trim(), 10) || 0;
}

const ask = async (page, q) => { await page.getByLabel('Câu hỏi').fill(q); await page.getByLabel('Câu hỏi').press('Enter'); };
// Real Ctrl+Alt+V if the session lets us inject input; otherwise show the (real) quick window directly
// and record that the global-hotkey *trigger* itself was not exercised.
const QTITLE = 'Personal Vault - Quick Access';
async function quickVisible(want, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if ((ps('winvisible', QTITLE) === 'True') === want) return true; await sleep(250); }
  return false;
}
async function openQuick(app) {
  ps('hotkey');
  report.metrics.hotkeyTriggerWorked = await quickVisible(true, 4000);
  if (!report.metrics.hotkeyTriggerWorked) {
    ps('showwin', QTITLE);
    must(await quickVisible(true), 'quick window did not become visible');
  }
  await sleep(500);
}
const confirmCopy = async (p) => {  // explicit confirmation before a password reaches the clipboard
  const d = p.getByRole('dialog', { name: /Sao chép mật khẩu\?/ });
  await d.waitFor({ state: 'visible', timeout: 15000 });
  await d.getByRole('button', { name: 'Sao chép', exact: true }).click();
};
const vis = (loc) => loc.waitFor({ state: 'visible', timeout: T });
const heading = (p, n) => vis(p.getByRole('heading', { name: n }));
const btn = (p, n, exact = false) => p.getByRole('button', { name: n, exact });

// ---------------------------------------------------------------- scenario A: personal vault lifecycle
async function personalFlow() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-e2e-'));
  const local = path.join(root, 'local');
  const docs = path.join(root, 'docs');
  fs.mkdirSync(docs, { recursive: true });
  const vaultPath = path.join(docs, 'e2e-vault.pvault');
  let app;

  if (!await step('A1 fresh launch shows Welcome (no password prompt)', async () => {
    app = await launch(local);
    await heading(app.main, 'Chào mừng đến Personal Vault');
    must(await app.main.locator('input[type=password]').count() === 0, 'password field on first launch');
    report.metrics.startupToWelcomeMs = Date.now() - app.t0;
    shot('Personal Vault', '01_welcome.png');
    return `startup→Welcome ${report.metrics.startupToWelcomeMs} ms`;
  })) return { root };

  await step('A2 Create screen: no validation errors before interaction', async () => {
    await btn(app.main, /Tạo két sắt mới/).click();
    await heading(app.main, 'Tạo két sắt mới');
    must(await app.main.getByRole('alert').count() === 0, 'alert shown before interaction');
    shot('Personal Vault', '02_create.png');
  });

  await step('A3 native Save dialog picks the location (real dialog, real keystrokes)', async () => {
    await btn(app.main, /Chọn vị trí lưu/).click();
    const d = ps('dialog', 'Chọn vị trí lưu két sắt mới', vaultPath); // UI Automation on the real native dialog
    must(d === 'OK', `native dialog automation: ${d}`);
    await vis(app.main.getByText('e2e-vault.pvault'));
  });

  await step('A4 confirmation mismatch is blocked (nothing written)', async () => {
    await app.main.getByLabel('Master Password', { exact: true }).fill(PW);
    const cf = app.main.getByLabel('Xác nhận Master Password', { exact: true });
    await cf.fill('Synthetic-E2E-Different-9!');
    await cf.blur();
    await vis(app.main.getByText('Mật khẩu xác nhận không khớp.'));
    await btn(app.main, 'Tạo két sắt', true).click();
    await sleep(800);
    must(!fs.existsSync(vaultPath), 'vault file was created despite mismatch');
    await cf.fill(PW);
  });

  await step('A5 create empty vault -> Empty Vault screen; file exists on disk, encrypted', async () => {
    await btn(app.main, 'Tạo két sắt', true).click();
    await vis(btn(app.main, /Khóa két sắt/));
    await vis(app.main.getByText('Két sắt đang trống.')); // Chat is the landing screen; it guides add/import
    await vis(btn(app.main, /Thêm tài khoản/));
    must(fs.existsSync(vaultPath), 'vault file missing');
    const raw = fs.readFileSync(vaultPath);
    must(raw.length > 49 && !raw.toString('latin1').includes('[]'), 'vault does not look like a ciphertext container');
    shot('Personal Vault', '03_empty_vault.png');
    await btn(app.main, /Quản lý két sắt/).click();
    await vis(app.main.getByText('Tổng cộng: 0 tài khoản'));
    shot('Personal Vault', '03b_empty_vault_manager.png');
    return `${raw.length} bytes`;
  });

  await step('A6 add account via modal (alias chip) and find it by search', async () => {
    await btn(app.main, /Thêm mới/).click();
    await heading(app.main, 'Thêm tài khoản mới');
    await app.main.getByLabel(/Tài khoản \/ Ứng dụng/).fill('E2E Synthetic Mail');
    await app.main.getByLabel(/Tên đăng nhập/).fill('e2e.user@example.invalid');
    await app.main.getByRole('dialog').getByLabel(/Mật khẩu/).fill('CANARY_E2E_PW_1');
    await app.main.getByLabel('Thêm bí danh').fill('mail e2e');
    await app.main.getByLabel('Thêm bí danh').press('Enter');
    await btn(app.main, 'Lưu vào két sắt').click();
    await vis(app.main.getByText('Tổng cộng: 1 tài khoản'));
    await app.main.getByPlaceholder(/Tìm tài khoản/).fill('mail e2e');
    await vis(app.main.getByText('Kết quả: 1'));
    await vis(app.main.getByRole('heading', { name: 'E2E Synthetic Mail' }));
  });

  await step('A7 reveal shows the real secret; edit with blank password keeps it', async () => {
    await btn(app.main, /Hiện 15 giây/).click();
    const pw = app.main.getByLabel('Mật khẩu', { exact: true });
    await sleep(300);
    must(await pw.inputValue() === 'CANARY_E2E_PW_1', 'reveal did not return the stored password');
    await btn(app.main, 'Chỉnh sửa tài khoản').click();
    await heading(app.main, 'Chỉnh sửa tài khoản');
    await app.main.getByLabel('Mô tả / Ghi chú').fill('đã sửa qua E2E');
    await btn(app.main, 'Lưu vào két sắt').click();
    await vis(app.main.getByText('Đã lưu tài khoản vào két sắt.'));
    await btn(app.main, /Hiện 15 giây/).click();
    await sleep(300);
    must(await app.main.getByLabel('Mật khẩu', { exact: true }).inputValue() === 'CANARY_E2E_PW_1', 'blank-password edit changed the secret');
    await btn(app.main, 'Ẩn').click();
  });

  await step('A8 native copy puts the password on the clipboard; auto-clears after ~20s', async () => {
    await btn(app.main, /Sao chép mật khẩu/).click();
    await vis(app.main.getByRole('dialog', { name: /Sao chép mật khẩu\?/ }));
    shot('Personal Vault', '10_copy_confirmation.png');
    await app.main.getByRole('dialog').getByRole('button', { name: 'Hủy', exact: true }).click();
    await sleep(500);
    must(ps('clip') !== 'CANARY_E2E_PW_1', 'password copied although the user cancelled');
    await btn(app.main, /Sao chép mật khẩu/).click();
    await confirmCopy(app.main);
    await sleep(700);
    must(ps('clip') === 'CANARY_E2E_PW_1', 'clipboard does not hold the password');
    await sleep(21500);
    must(ps('clip') === '', 'clipboard not cleared after 20 s');
  });

  await step('A9 lock -> Unlock screen shows the vault (not Welcome)', async () => {
    await btn(app.main, /Khóa két sắt/).click();
    await heading(app.main, 'Mở khóa két sắt');
    await vis(app.main.getByText('e2e-vault.pvault'));
    must(await app.main.getByRole('alert').count() === 0, 'error shown before submit');
    shot('Personal Vault', '04_unlock.png');
  });

  await step('A10 wrong password rejected; correct password reopens with data intact', async () => {
    await app.main.getByLabel('Master Password').fill('wrong-e2e-password-9');
    await btn(app.main, 'Mở khóa', true).click();
    await vis(app.main.getByRole('alert'));
    await app.main.getByLabel('Master Password').fill(PW);
    await btn(app.main, 'Mở khóa', true).click();
    await vis(app.main.getByLabel('Câu hỏi')); // lands on Chat, not Manager
    await sleep(400);
    shot('Personal Vault', '09a_chatbot_empty.png'); // vault with data, nothing asked yet: the question box is the screen
  });

  await step('A10b chatbot: natural question -> masked account card; native copy; no secret in DOM', async () => {
    await ask(app.main, 'cho tôi tài khoản mail e2e');
    const card = app.main.getByRole('article', { name: 'E2E Synthetic Mail' });
    await vis(card);
    must(/••••••••/.test(await card.innerText()), 'password not masked on the card');
    must(!(await app.main.content()).includes('CANARY_E2E'), 'secret present in DOM before explicit action');
    shot('Personal Vault', '09_chatbot.png');
    await card.getByRole('button', { name: /Sao chép mật khẩu/ }).click();
    await confirmCopy(app.main);
    await sleep(700);
    must(ps('clip') === 'CANARY_E2E_PW_1', 'chat card native copy failed');
    await ask(app.main, 'zzqxj không tồn tại');
    await vis(app.main.getByText(/Không tìm thấy tài khoản phù hợp/));
    await btn(app.main, /Quản lý két sắt/).click();
    await vis(app.main.getByText('Tổng cộng: 1 tài khoản'));
  });

  await step('A11 import: real file chooser -> preview (new/duplicate/invalid) -> confirm -> reported', async () => {
    const f = path.join(root, 'import_synthetic.txt');
    fs.writeFileSync(f, [
      'Account: E2E Synthetic Mail', 'Name: e2e.user@example.invalid', 'Pass: CANARY_DUP', '',
      'Account: E2E Synthetic Wiki', 'Name: wiki@example.invalid', 'Pass: CANARY_E2E_WIKI', 'Aliases: wiki e2e; docs', 'URL: etap://10.0.0.15:8000', '',
      'Account: E2E Synthetic PSCAD 2', 'Name: pscad2', 'Pass: CANARY_E2E_PSCAD', '',
    ].join('\n'), 'utf8');
    await app.main.setInputFiles('input[type=file]', f);
    await heading(app.main, 'Xem trước dữ liệu nhập');
    for (const t of ['Tổng: 3', 'Mới: 2', 'Trùng: 1', 'Không hợp lệ: 0']) await vis(app.main.getByText(t));
    shot('Personal Vault', '06_import_preview.png');
    await btn(app.main, /Nhập 2 tài khoản/).click();
    await vis(app.main.getByText(/Đã nhập 2 tài khoản mới/));
    await vis(app.main.getByText('Tổng cộng: 3 tài khoản'));
  });

  await step('A12 import rejects an invalid file and writes nothing', async () => {
    const f = path.join(root, 'bad.bat');
    fs.writeFileSync(f, 'echo this must never run\r\n', 'utf8');
    await app.main.setInputFiles('input[type=file]', f);
    await vis(app.main.getByText(/File bị từ chối/));
    await btn(app.main, 'Đóng', true).click();
    await app.main.getByPlaceholder(/Tìm tài khoản/).fill('');
    await vis(app.main.getByText('Tổng cộng: 3 tài khoản'));
  });

  await step('A13 imported password is the real secret (not a mask) and URL is copy-only', async () => {
    await app.main.getByPlaceholder(/Tìm tài khoản/).fill('wiki e2e');
    await vis(app.main.getByRole('heading', { name: 'E2E Synthetic Wiki' }));
    await btn(app.main, /Hiện 15 giây/).click();
    await sleep(300);
    must(await app.main.getByLabel('Mật khẩu', { exact: true }).inputValue() === 'CANARY_E2E_WIKI', 'imported password is wrong');
    must(await app.main.locator('a[href]').count() === 0, 'URL rendered as a link');
    await app.main.getByPlaceholder(/Tìm tài khoản/).fill('');
  });

  await step('A13b real-EXE UI states: ambiguous = visual list (no cards before a choice), choosing opens the card, not found = one short line, manager', async () => {
    await btn(app.main, /Trò chuyện/).click();
    await vis(app.main.getByLabel('Câu hỏi'));
    await ask(app.main, 'e2e');
    const list = app.main.getByRole('list', { name: 'Chọn tài khoản' });
    await vis(list);
    must((await list.getByRole('button').count()) >= 2, 'the ambiguous answer should offer at least two accounts');
    must((await app.main.getByRole('article').count()) === 1, 'only the earlier exact card may be on screen before a choice is made');
    must((await app.main.getByText(/Có \d+ tài khoản phù hợp/).count()) === 0, 'the bot repeats the list in words');
    await sleep(300);
    shot('Personal Vault', '12_chatbot_ambiguous.png');
    await list.getByRole('button').first().click();
    await vis(app.main.getByRole('article').nth(1));
    await ask(app.main, 'zzqxj không tồn tại');
    await vis(app.main.getByText(/Không tìm thấy tài khoản phù hợp/));
    await sleep(300);
    shot('Personal Vault', '13_chatbot_not_found.png');
    await btn(app.main, /Quản lý két sắt/).click();
    await vis(app.main.getByText('Tổng cộng: 3 tài khoản'));
    await sleep(300);
    shot('Personal Vault', '14_vault_manager.png');
  });

  let quickOk = false;
  await step('A14 Quick Access: real Ctrl+Alt+V opens compact window, search-first, keyboard copy, Esc closes', async () => {
    must(app.quick, 'quick window page not found');
    report.metrics.hotkeyRegistered = ps('hotkeycheck');
    must(report.metrics.hotkeyRegistered.includes('registered_by_other=True'), `Ctrl+Alt+V not registered: ${report.metrics.hotkeyRegistered}`);
    await openQuick(app);
    const input = app.quick.getByRole('combobox');
    await vis(input);
    must(await input.evaluate((el) => el === document.activeElement), 'search box not focused');
    await input.fill('wiki');
    await vis(app.quick.getByRole('option').first());
    shot('Personal Vault - Quick Access', '05_quick_access.png');
    await input.press('Shift+Enter');
    await sleep(500);
    must(ps('clip') === 'wiki@example.invalid', 'username not copied');
    await input.press('Enter'); // first Enter only arms the copy
    await vis(app.quick.getByText(/Nhấn Enter lần nữa/));
    await sleep(500);
    must(ps('clip') === 'wiki@example.invalid', 'first Enter copied the password without confirmation');
    await input.press('Enter');
    await sleep(700);
    must(ps('clip') === 'CANARY_E2E_WIKI', 'password not copied natively');
    must(await quickVisible(false), 'quick window did not hide');
    await openQuick(app);
    await app.quick.keyboard.press('Escape');
    must(await quickVisible(false), 'quick window did not hide');
    quickOk = true;
  });

  await step('A15 Quick Access while locked is fail-closed (no search box)', async () => {
    await btn(app.main, /Khóa két sắt/).click();
    await heading(app.main, 'Mở khóa két sắt');
    await openQuick(app);
    await vis(app.quick.getByText('Két sắt đang khóa'));
    must(await app.quick.getByRole('combobox').count() === 0, 'search box shown while locked');
    shot('Personal Vault - Quick Access', '05b_quick_locked.png');
    await app.quick.keyboard.press('Escape');
  });

  await step('A16 process tree + network evidence (unlocked app)', async () => {
    await app.main.getByLabel('Master Password').fill(PW);
    await btn(app.main, 'Mở khóa', true).click();
    await vis(app.main.getByLabel('Câu hỏi'));
    // Sample the whole process tree's sockets repeatedly (WebView2 traffic is bursty), idle + after activity.
    let tree = [], net = [];
    for (let i = 0; i < 8; i++) {
      tree = JSON.parse(ps('tree', String(app.child.pid)) || '[]');
      net.push(...JSON.parse(ps('tcp', tree.map((t) => t.pid).join(',')) || '[]'));
      if (i === 3) { await app.main.getByLabel('Câu hỏi').fill('wiki'); await app.main.getByLabel('Câu hỏi').press('Enter'); }
      await sleep(4000);
    }
    net = [...new Map(net.map((n) => [`${n.pid}|${n.proto}|${n.local}|${n.remote}|${n.state}`, n])).values()];
    report.metrics.processTree = tree;
    report.metrics.processTreeWorkingSetMB = Math.round(tree.reduce((s, t) => s + t.wsMB, 0) * 10) / 10;
    report.metrics.processNames = Object.fromEntries(tree.map((t) => [t.pid, t.name]));
    // Only the harness' own CDP debug port (127.0.0.1:PORT, QA-only) may exist; anything else is reported.
    report.metrics.network = net;
    const foreign = net.filter((n) => !(n.local.endsWith(`:${PORT}`) || n.remote.endsWith(`:${PORT}`)));
    report.metrics.networkOutsideHarness = foreign;
    return `${tree.length} procs, ${report.metrics.processTreeWorkingSetMB} MB WS; non-harness sockets: ${foreign.length}`;
  });

  await step('A17 close app gracefully: no orphan sidecar', async () => {
    const graceful = await closeGracefully(app);
    must(sidecarsRunning() === 0, 'orphan pvault-sidecar.exe still running');
    return graceful ? 'closed via WM_CLOSE' : 'needed taskkill';
  });

  await step('A18 restart: app remembers the vault -> Unlock -> unlock -> data persisted', async () => {
    app = await launch(local);
    await heading(app.main, 'Mở khóa két sắt');
    await vis(app.main.getByText('e2e-vault.pvault'));
    await app.main.getByLabel('Master Password').fill(PW);
    await btn(app.main, 'Mở khóa', true).click();
    await ask(app.main, 'wiki e2e');
    await vis(app.main.getByRole('article', { name: 'E2E Synthetic Wiki' }));
  });

  await step('A19 hard kill (crash) then relaunch: vault intact, can unlock again', async () => {
    execFileSync('taskkill', ['/PID', String(app.child.pid), '/T', '/F'], { stdio: 'ignore' });
    await app.browser.close().catch(() => {});
    await sleep(1500);
    app = await launch(local);
    await heading(app.main, 'Mở khóa két sắt');
    await app.main.getByLabel('Master Password').fill(PW);
    await btn(app.main, 'Mở khóa', true).click();
    await ask(app.main, 'pscad 2');
    // The query can be ambiguous (visual list): choosing a row is the confirmation that opens the card.
    const pick = app.main.getByRole('list', { name: 'Chọn tài khoản' }).getByRole('button', { name: /E2E Synthetic PSCAD 2/ });
    const card = app.main.getByRole('article', { name: 'E2E Synthetic PSCAD 2' });
    await Promise.race([pick.waitFor({ timeout: T }), card.waitFor({ timeout: T })]);
    if (await pick.count()) await pick.first().click();
    await vis(card);
  });

  await step('A20 missing vault: Recovery UI, nothing recreated; "Kiểm tra lại" finds the restored file', async () => {
    await closeGracefully(app);
    const moved = vaultPath + '.moved';
    fs.renameSync(vaultPath, moved);
    app = await launch(local);
    await heading(app.main, 'Không tìm thấy file két sắt');
    must(await app.main.locator('input[type=password]').count() === 0, 'password asked for a missing vault');
    shot('Personal Vault', '07_recovery_missing.png');
    must(!fs.existsSync(vaultPath), 'vault was recreated');
    fs.renameSync(moved, vaultPath);
    await btn(app.main, /Kiểm tra lại/).click();
    await heading(app.main, 'Mở khóa két sắt');
  });

  await closeGracefully(app).catch(() => {});

  await step('A21 canary scan: master password + secrets absent from profile, state dir, vault file and logs', async () => {
    const needles = [PW, 'CANARY_E2E_PW_1', 'CANARY_E2E_WIKI', 'CANARY_E2E_PSCAD']
      .flatMap((n) => [Buffer.from(n, 'utf8'), Buffer.from(n, 'utf16le')]);
    const hits = []; let files = 0, bytes = 0;
    const walk = (d) => {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const f = path.join(d, e.name);
        if (e.isDirectory()) { walk(f); continue; }
        try {
          const st = fs.statSync(f); if (st.size > 200 * 1024 * 1024) continue;
          const buf = fs.readFileSync(f); files++; bytes += buf.length;
          if (needles.some((n) => buf.includes(n))) hits.push(path.relative(root, f));
        } catch { /* locked/unreadable temp file */ }
      }
    };
    walk(local); walk(docs);  // WebView2 profile + app state + the vault file; the plaintext import sources are outside these
    report.metrics.canaryScan = { files, megabytes: Math.round(bytes / 1048576), hits };
    must(hits.length === 0, `secret found in: ${hits.join(', ')}`);
    return `${files} files / ${report.metrics.canaryScan.megabytes} MB scanned, 0 hits`;
  });
  return { root, quickOk };
}

// ---------------------------------------------------------------- scenario C: sidecar crash -> fail closed
async function crashFlow() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-e2e-crash-'));
  const local = path.join(root, 'local');
  const vaultPath = path.join(root, 'crash.pvault');
  let app;
  const sidecarPids = () => JSON.parse(ps('tree', String(app.child.pid)) || '[]').filter((t) => t.name === 'pvault-sidecar.exe').map((t) => t.pid);
  const killSidecar = () => { for (const pid of sidecarPids()) { try { execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ } } };
  const unlockInto = async () => {
    await app.main.getByLabel('Master Password').fill(PW);
    await btn(app.main, 'Mở khóa', true).click();
    await vis(app.main.getByLabel('Câu hỏi'));
  };

  await step('C1 setup: vault with one account, unlocked in Chat', async () => {
    app = await launch(local);
    await heading(app.main, 'Chào mừng đến Personal Vault');
    await app.main.evaluate(([v, pw]) => window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: 'create', params: { path: v, password: pw, demo: false } }), [vaultPath, PW]);
    await app.main.evaluate(() => window.__TAURI_INTERNALS__.invoke('invoke_sidecar', { method: 'save_entry', params: { entry_data: { account: 'Crash Synthetic', name: 'crash.user', password: 'CANARY_CRASH_PW' } } }));
    await app.main.reload();
    await vis(app.main.getByLabel('Câu hỏi'));
    await ask(app.main, 'crash synthetic');
    await vis(app.main.getByRole('article', { name: 'Crash Synthetic' }));
    report.metrics.sidecarPidsBeforeCrash = sidecarPids();
  });

  await step('C2 sidecar killed while idle: UI leaves the vault by itself (no stale card, no secret)', async () => {
    killSidecar();
    await heading(app.main, 'Mở khóa két sắt'); // the 3 s state poll restarts the sidecar, which comes back LOCKED
    must(await app.main.getByRole('article').count() === 0, 'stale account card after the sidecar died');
    must(!(await app.main.content()).includes('CANARY_CRASH'), 'secret in the DOM after the crash');
    const after = sidecarPids();
    must(after.length > 0 && !after.some((p) => report.metrics.sidecarPidsBeforeCrash.includes(p)), 'sidecar was not replaced by a fresh process');
    report.metrics.sidecarPidsAfterCrash = after;
    shot('Personal Vault', '11_after_sidecar_crash.png');
  });

  await step('C3 after the crash the vault needs the master password again; data intact', async () => {
    await unlockInto();
    await ask(app.main, 'crash synthetic');
    await vis(app.main.getByRole('article', { name: 'Crash Synthetic' }));
  });

  await step('C4 sidecar killed, then the user acts: the action fails closed (no result shown)', async () => {
    killSidecar();
    await ask(app.main, 'crash synthetic');
    await heading(app.main, 'Mở khóa két sắt');
    must(await app.main.getByRole('article').count() === 0, 'a result was rendered from a dead sidecar');
  });

  await step('C5 Quick Access after a crash is fail-closed too', async () => {
    await unlockInto();
    killSidecar();
    await openQuick(app);
    await vis(app.quick.getByText('Két sắt đang khóa'));
    must(await app.quick.getByRole('combobox').count() === 0, 'search box shown after the sidecar died');
    await app.quick.keyboard.press('Escape');
  });

  await closeGracefully(app).catch(() => {});
  must(sidecarsRunning() === 0, 'orphan sidecar after crash scenario');
  return root;
}

// ---------------------------------------------------------------- scenario B: demo isolation (own fresh profile)
async function demoFlow() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pv-e2e-demo-'));
  const local = path.join(root, 'local');
  let app;
  await step('B1 demo from Welcome: fixed DEMO label, exactly 500 accounts', async () => {
    app = await launch(local);
    await heading(app.main, 'Chào mừng đến Personal Vault');
    await btn(app.main, /Dùng thử demo/).click();
    await vis(app.main.getByText('DEMO', { exact: true }));
    await btn(app.main, /Quản lý két sắt/).click();
    await vis(app.main.getByText('Tổng cộng: 500 tài khoản'));
    shot('Personal Vault', '08_demo.png');
  });
  await step('B2 demo storage is separate; no personal pointer written; lock returns to Welcome', async () => {
    const dir = path.join(local, 'PersonalVault');
    const demoFiles = fs.readdirSync(path.join(dir, 'demo')).filter((f) => f.endsWith('.pvault'));
    must(demoFiles.length === 1, `expected 1 demo file, got ${demoFiles.length}`);
    must(!fs.existsSync(path.join(dir, 'last_vault.json')), 'demo wrote the personal vault pointer');
    await btn(app.main, /Khóa két sắt/).click();
    await heading(app.main, 'Chào mừng đến Personal Vault');
  });
  await closeGracefully(app).catch(() => {});
  return root;
}

const roots = [];
try {
  const a = await personalFlow(); roots.push(a.root);
  roots.push(await crashFlow());
  roots.push(await demoFlow());
} catch (e) {
  record('E2E harness', 'FAIL', String(e?.message ?? e));
}
report.finishedAt = new Date().toISOString();
report.summary = {
  PASS: report.steps.filter((s) => s.status === 'PASS').length,
  FAIL: report.steps.filter((s) => s.status === 'FAIL').length,
};
fs.writeFileSync(path.join(OUT, 'e2e_report.json'), JSON.stringify(report, null, 2));
console.log(`\nE2E summary: ${report.summary.PASS} PASS / ${report.summary.FAIL} FAIL  -> ${path.join(OUT, 'e2e_report.json')}`);
for (const r of roots) { try { fs.rmSync(r, { recursive: true, force: true }); } catch { /* temp cleanup best effort */ } }
process.exit(report.summary.FAIL ? 1 : 0);
