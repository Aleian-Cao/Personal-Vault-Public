// Regression: first-launch, vault lifecycle, edit/import contracts, Quick Access.
// SYNTHETIC data only (MemoryMockBridge). Run from web/:  node --test tests/
// Needs Playwright chromium. The real-EXE E2E lives in e2e/ (separate, drives the built app).
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

let server, browser, base;
const T = 8000;
const PW = 'Synthetic-Master-Only-123!';

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    server: { host: '127.0.0.1', port: 5199 },
    logLevel: 'silent',
  });
  await server.listen();
  base = server.resolvedUrls.local[0];
  browser = await chromium.launch();
});

after(async () => {
  await browser?.close();
  await server?.close();
});

async function open(mock, hash = '') {
  const page = await browser.newPage({ viewport: { width: 1040, height: 720 } });
  await page.goto(`${base}?mock=${mock}${hash}`);
  return page;
}
async function openManager(mockMode = 'open') {
  const page = await open(mockMode);
  await btn(page, /Quản lý két sắt/).click();
  await visible(btn(page, /Nhập dữ liệu/));
  return page;
}
const heading = (page, name) => page.getByRole('heading', { name }).waitFor({ state: 'visible', timeout: T });
const alerts = (page) => page.getByRole('alert');
const btn = (page, name, exact = false) => page.getByRole('button', { name, exact });
const mock = (page, fn, arg) => page.evaluate(fn, arg);
const visible = (loc) => loc.waitFor({ state: 'visible', timeout: T });

// ---------------------------------------------------------------- startup / lifecycle
test('fresh install: Welcome with 3 choices, no password prompt, no errors', async () => {
  const page = await open('fresh');
  await heading(page, 'Chào mừng đến Personal Vault');
  for (const n of [/Tạo két sắt mới/, /Mở két sắt có sẵn/, /Dùng thử demo/]) {
    assert.equal(await btn(page, n).count(), 1, `missing choice ${n}`);
  }
  assert.equal(await page.locator('input[type=password]').count(), 0, 'password asked before any vault exists');
  assert.equal(await alerts(page).count(), 0);
  await page.close();
});

test('fresh install: "Mở két sắt có sẵn" picks a file then goes to Unlock for that file', async () => {
  const page = await open('fresh');
  await heading(page, 'Chào mừng đến Personal Vault');
  await btn(page, /Mở két sắt có sẵn/).click();
  await heading(page, 'Mở khóa két sắt');
  await visible(page.getByText('other-vault.pvault'));
  assert.equal(await alerts(page).count(), 0);
  await page.close();
});

test('existing vault: Unlock shows the vault, can pick another, no error before submit', async () => {
  const page = await open('locked');
  await heading(page, 'Mở khóa két sắt');
  assert.ok(await page.getByText('my-vault.pvault').isVisible());
  assert.equal(await alerts(page).count(), 0, 'validation shown before any interaction');

  await btn(page, /Chọn két sắt khác/).click();
  await visible(page.getByText('other-vault.pvault'));

  await btn(page, 'Mở khóa', true).click(); // submit empty -> error allowed now
  await visible(alerts(page).first());

  await page.getByLabel('Master Password').fill(PW);
  await btn(page, 'Mở khóa', true).click();
  await visible(btn(page, /Khóa két sắt/));
  await page.close();
});

test('wrong password: error shown, stays on Unlock, correct password then works', async () => {
  const page = await open('locked');
  await heading(page, 'Mở khóa két sắt');
  await page.getByLabel('Master Password').fill('wrong-synthetic-pass-9');
  await btn(page, 'Mở khóa', true).click();
  await visible(alerts(page).first());
  assert.match(await alerts(page).first().innerText(), /không đúng/i);
  assert.equal(await btn(page, /Khóa két sắt/).count(), 0);
  await page.getByLabel('Master Password').fill(PW);
  await btn(page, 'Mở khóa', true).click();
  await visible(btn(page, /Khóa két sắt/));
  await page.close();
});

test('missing vault: Recovery UI, never auto-creates, lets user pick another file', async () => {
  const page = await open('missing');
  await heading(page, 'Không tìm thấy file két sắt');
  assert.ok(await page.getByText('my-vault.pvault').isVisible());
  assert.equal(await page.locator('input[type=password]').count(), 0);
  assert.equal(await alerts(page).count(), 0);
  assert.equal(await mock(page, () => window.__mock.fileCount()), 1, 'only the pre-existing other vault');
  assert.equal(await btn(page, /Kiểm tra lại/).count(), 1);

  await btn(page, /Chọn file két sắt khác/).click();
  await heading(page, 'Mở khóa két sắt');
  await visible(page.getByText('other-vault.pvault'));
  assert.equal(await mock(page, () => window.__mock.fileCount()), 1, 'recovery must not create files');
  await page.close();
});

test('create empty: untouched = no errors; mismatch blocked; then Empty Vault; lock -> Unlock -> reopen', async () => {
  const page = await open('fresh');
  await heading(page, 'Chào mừng đến Personal Vault');
  await btn(page, /Tạo két sắt mới/).click();
  await heading(page, 'Tạo két sắt mới');
  assert.equal(await alerts(page).count(), 0, 'validation shown before any interaction');

  const pw = page.getByLabel('Master Password', { exact: true });
  const cf = page.getByLabel('Xác nhận Master Password', { exact: true });
  await btn(page, /Chọn vị trí lưu/).click();
  await visible(page.getByText('personal-vault.pvault'));
  await pw.fill(PW);
  await cf.fill('Synthetic-Master-Only-999!');
  await cf.blur();
  await visible(page.getByText('Mật khẩu xác nhận không khớp.'));
  await btn(page, 'Tạo két sắt', true).click();
  assert.equal(await btn(page, /Khóa két sắt/).count(), 0, 'vault created despite mismatch');
  assert.equal(await mock(page, () => window.__mock.fileCount()), 1, 'file written despite mismatch');

  await cf.fill(PW);
  assert.equal(await alerts(page).count(), 0);
  await btn(page, 'Tạo két sắt', true).click();
  await visible(btn(page, /Khóa két sắt/));
  await visible(page.getByText('Két sắt đang trống.')); // chat empty state guides to add/import
  await visible(btn(page, /Thêm tài khoản/));
  assert.equal(await page.getByText(/DEMO/).count(), 0, 'a personal vault must never carry the demo label');
  assert.equal(await mock(page, () => window.__mock.fileCount()), 2);
  await btn(page, /Quản lý két sắt/).click();
  await visible(page.getByText('Tổng cộng: 0 tài khoản'));

  await btn(page, /Khóa két sắt/).click();
  await heading(page, 'Mở khóa két sắt');
  assert.ok(await page.getByText('personal-vault.pvault').isVisible());
  await page.getByLabel('Master Password').fill(PW);
  await btn(page, 'Mở khóa', true).click();
  await visible(btn(page, /Khóa két sắt/));
  await visible(page.getByText('Két sắt đang trống.'));
  await page.close();
});

test('create short password: error only after interaction', async () => {
  const page = await open('fresh');
  await btn(page, /Tạo két sắt mới/).click();
  await heading(page, 'Tạo két sắt mới');
  const pw = page.getByLabel('Master Password', { exact: true });
  await pw.fill('short');
  assert.equal(await alerts(page).count(), 0, 'error while still typing the first time');
  await pw.blur();
  await visible(page.getByText('Mật khẩu chính cần tối thiểu 12 ký tự.'));
  await page.close();
});

test('demo isolation: fixed DEMO label, exactly 500 accounts, lock returns to Welcome, no personal data mixed', async () => {
  const page = await open('fresh');
  await heading(page, 'Chào mừng đến Personal Vault');
  await btn(page, /Dùng thử demo/).click();
  await visible(btn(page, /Khóa két sắt/));
  assert.ok(await page.getByText(/DEMO/).first().isVisible(), 'demo vault not labelled (chat)');
  await btn(page, /Quản lý két sắt/).click();
  await visible(page.getByText('Tổng cộng: 500 tài khoản'));
  assert.ok(await page.getByText('DEMO', { exact: true }).first().isVisible(), 'demo vault not labelled (manager)');
  assert.equal(await mock(page, () => window.__mock.fileCount()), 1, 'demo must not write a personal vault file');
  await btn(page, /Khóa két sắt/).click();
  await heading(page, 'Chào mừng đến Personal Vault');
  await page.close();
});

test('stale IPC: backend locked behind the UI -> next action returns to Unlock, no crash', async () => {
  const page = await open('open');
  await visible(btn(page, /Khóa két sắt/));
  await mock(page, () => window.__mock.forceLock());
  await page.getByLabel('Câu hỏi').fill('fb');
  await page.getByLabel('Câu hỏi').press('Enter');
  await heading(page, 'Mở khóa két sắt');
  await page.close();
});

test('stale IPC (manager): same fail-closed return to Unlock', async () => {
  const page = await openManager();
  await mock(page, () => window.__mock.forceLock());
  await page.getByPlaceholder(/Tìm tài khoản/).fill('fb');
  await heading(page, 'Mở khóa két sắt');
  await page.close();
});

// ---------------------------------------------------------------- chatbot (default screen after unlock)
const ask = async (page, q) => {
  await page.getByLabel('Câu hỏi').fill(q);
  await page.getByLabel('Câu hỏi').press('Enter');
};

test('chat: default screen after unlock; exact answer = masked account card, secret only on explicit action', async () => {
  const page = await open('locked');
  await heading(page, 'Mở khóa két sắt');
  await page.getByLabel('Master Password').fill(PW);
  await btn(page, 'Mở khóa', true).click();
  await visible(page.getByLabel('Câu hỏi'));
  assert.equal(await btn(page, /Nhập dữ liệu/).count(), 0, 'landed in Vault Manager instead of Chat');

  await ask(page, 'wiki nội bộ');
  const card = page.getByRole('article', { name: 'Internal Wiki — Engineering' });
  await visible(card);
  assert.equal(await page.getByRole('article').count(), 1);
  assert.match(await card.innerText(), /••••••••/);
  assert.ok(!(await page.content()).includes('CANARY'), 'a secret is in the DOM before any explicit action');

  await card.getByRole('button', { name: /Sao chép mật khẩu/ }).click();
  await visible(page.getByRole('dialog', { name: /Sao chép mật khẩu\?/ }));
  await btn(page, 'Hủy', true).click();
  assert.equal(await mock(page, () => window.__mock.lastCopied), null, 'copied without confirmation');
  await card.getByRole('button', { name: /Sao chép mật khẩu/ }).click();
  await btn(page, 'Sao chép', true).click();
  await page.waitForFunction(() => window.__mock.lastCopied === 'CANARY_DEMO_WIKI');
  await card.getByRole('button', { name: /Hiện 15 giây/ }).click();
  await page.waitForFunction(() => document.body.innerText.includes('CANARY_DEMO_WIKI'));
  await ask(page, 'etap');
  await visible(page.getByRole('list', { name: 'Chọn tài khoản' }));
  assert.ok(!(await page.content()).includes('CANARY_DEMO_WIKI'), 'revealed secret survived the next question');
  await page.close();
});

test('chat: ambiguous -> visual choice list, choosing opens the card; follow-up "máy 5" narrows; none -> one short line', async () => {
  const page = await open('open');
  await ask(page, 'etap');
  const list = page.getByRole('list', { name: 'Chọn tài khoản' });
  await visible(list);
  assert.equal(await list.getByRole('button').count(), 3);
  assert.equal(await page.getByRole('article').count(), 0, 'account cards must not appear before the user chooses');
  assert.equal(await page.getByText(/Có 3 tài khoản phù hợp/).count(), 0, 'the bot repeats the list in words');

  await list.getByRole('button', { name: /ETAP Server 15/ }).click();                 // choosing = opening the card
  await visible(page.getByRole('article', { name: 'ETAP Server 15' }));
  assert.equal(await page.getByRole('list', { name: 'Chọn tài khoản' }).count(), 0);
  await btn(page, 'Chọn khác').click();                                                // ...and the list comes back
  await visible(page.getByRole('list', { name: 'Chọn tài khoản' }));
  assert.equal(await page.getByRole('article').count(), 0);

  await ask(page, 'máy 5');                                                            // exact -> the card, no sentence around it
  await visible(page.getByRole('article', { name: 'ETAP Server 5' }));
  assert.equal(await page.getByRole('article').count(), 1);
  assert.equal(await page.getByText(/Khớp chính xác|Tìm thấy «/).count(), 0, 'the bot repeats the card in words');

  await ask(page, 'zzzqq');
  await visible(page.getByText(/Không tìm thấy tài khoản phù hợp/));
  assert.equal(await page.getByRole('article').count(), 1, 'a failed question adds no card');
  await page.close();
});

test('chat: lock drops the transcript; nothing from the old session after unlock', async () => {
  const page = await open('open');
  await ask(page, 'fb chính');
  await visible(page.getByRole('article', { name: 'Facebook — Demo Personal' }));
  await btn(page, /Khóa két sắt/).click();
  await heading(page, 'Mở khóa két sắt');
  await page.getByLabel('Master Password').fill(PW);
  await btn(page, 'Mở khóa', true).click();
  await visible(page.getByLabel('Câu hỏi'));
  assert.equal(await page.getByRole('article').count(), 0);
  assert.equal(await page.getByText('Facebook — Demo Personal').count(), 0, 'old transcript survived lock');
  await page.close();
});

test('chat -> manager -> chat keeps the in-memory transcript', async () => {
  const page = await open('open');
  await ask(page, 'fb chính');
  await visible(page.getByRole('article', { name: 'Facebook — Demo Personal' }));
  await btn(page, /Quản lý két sắt/).click();
  await visible(btn(page, /Nhập dữ liệu/));
  await btn(page, /Trò chuyện/).click();
  await visible(page.getByRole('article', { name: 'Facebook — Demo Personal' }));
  await page.close();
});

// ---------------------------------------------------------------- edit / detail contracts
test('edit: blank password = keep old secret; masked value never sent; new password replaces', async () => {
  const page = await openManager();
  await visible(page.getByText('Facebook — Demo Personal').first());
  await btn(page, 'Chỉnh sửa tài khoản').click();
  await heading(page, 'Chỉnh sửa tài khoản');
  const values = await page.locator('[role=dialog] input, [role=dialog] textarea').evaluateAll((els) => els.map((e) => e.value));
  assert.ok(!values.some((v) => v.includes('•')), 'masked placeholder leaked into a field value');
  const pwField = page.getByRole('dialog').getByLabel(/Mật khẩu/);
  assert.equal(await pwField.inputValue(), '');
  assert.match((await pwField.getAttribute('placeholder')) || '', /giữ mật khẩu cũ/i);

  await page.getByLabel('Mô tả / Ghi chú').fill('đã sửa mô tả');
  await btn(page, 'Lưu vào két sắt').click();
  await page.waitForFunction(() => window.__mock.saved.length === 1);
  assert.equal(await mock(page, () => window.__mock.saved[0].password), undefined);
  assert.equal(await mock(page, () => window.__mock.passwordOf('syn-001')), 'CANARY_DEMO_FB');

  await btn(page, 'Chỉnh sửa tài khoản').click();
  await pwField.fill('Synthetic-New-456');
  await btn(page, 'Lưu vào két sắt').click();
  await page.waitForFunction(() => window.__mock.saved.length === 2);
  assert.equal(await mock(page, () => window.__mock.passwordOf('syn-001')), 'Synthetic-New-456');
  await page.close();
});

test('edit: aliases/tags are chips (add with Enter, remove with ×)', async () => {
  const page = await openManager();
  await visible(page.getByText('Facebook — Demo Personal').first());
  await btn(page, 'Chỉnh sửa tài khoản').click();
  await heading(page, 'Chỉnh sửa tài khoản');
  await btn(page, 'Xóa bí danh fb chính').click();
  await page.getByLabel('Thêm bí danh').fill('bí danh mới');
  await page.getByLabel('Thêm bí danh').press('Enter');
  await visible(page.getByText('bí danh mới'));
  await page.getByLabel('Thêm tag').fill('nhãn mới');
  await page.getByLabel('Thêm tag').press('Enter');
  await btn(page, 'Lưu vào két sắt').click();
  await page.waitForFunction(() => window.__mock.saved.length === 1);
  const saved = await mock(page, () => window.__mock.saved[0]);
  assert.ok(saved.aliases.includes('bí danh mới') && !saved.aliases.includes('fb chính'));
  assert.ok(saved.tags.includes('nhãn mới'));
  await page.close();
});

test('detail: internal ID hidden; URL/host is copy-only (no link, never executed)', async () => {
  const page = await openManager();
  await visible(page.getByText('Facebook — Demo Personal').first());
  assert.equal(await page.getByText('syn-001').count(), 0, 'internal ID visible');
  assert.equal(await page.getByText(/^ID:/).count(), 0);
  assert.equal(await page.locator('a[href]').count(), 0, 'URL rendered as a link');
  await btn(page, /Sao chép URL/).click();
  assert.equal(await mock(page, () => window.__mock.lastCopied), 'https://facebook.com');
  await page.close();
});

// ---------------------------------------------------------------- import
const IMPORT_OK = [
  'Account: Facebook — Demo Personal', 'Name: demo.personal@example.invalid', 'Pass: CANARY_DUP', '',
  'Account: Synthetic Wiki', 'Name: wiki@example.invalid', 'Pass: CANARY_WIKI_IMPORTED', 'URL: etap://10.0.0.15:8000', '',
].join('\n');

test('import: real file chooser -> preview with counts -> confirm -> result reported', async () => {
  const page = await openManager();
  await visible(page.getByText('Tổng cộng: 8 tài khoản'));
  await page.setInputFiles('input[type=file]', { name: 'accounts.txt', mimeType: 'text/plain', buffer: Buffer.from(IMPORT_OK) });
  await heading(page, 'Xem trước dữ liệu nhập');
  await visible(page.getByText('accounts.txt'));
  for (const t of ['Tổng: 2', 'Mới: 1', 'Trùng: 1', 'Không hợp lệ: 0']) await visible(page.getByText(t));
  assert.equal(await mock(page, () => window.__mock.entryCount()), 8, 'preview must not write');
  await btn(page, /Nhập 1 tài khoản/).click();
  await visible(page.getByText(/Đã nhập 1 tài khoản mới/));
  await visible(page.getByText('Tổng cộng: 9 tài khoản'));
  assert.equal(await mock(page, () => window.__mock.passwordOfAccount('Synthetic Wiki')), 'CANARY_WIKI_IMPORTED');
  await page.close();
});

test('import: invalid / unsupported files are rejected with a clear message and nothing is written', async () => {
  const page = await openManager();
  for (const [name, body] of [['bad.txt', 'xin chào không phải bản ghi'], ['tool.exe', 'MZ']]) {
    await page.setInputFiles('input[type=file]', { name, mimeType: 'application/octet-stream', buffer: Buffer.from(body) });
    await visible(page.getByText(/File bị từ chối/));
    assert.equal(await btn(page, /Nhập \d+ tài khoản/).count(), 0, `${name}: confirm offered for a rejected file`);
    await btn(page, 'Đóng', true).click();
  }
  assert.equal(await mock(page, () => window.__mock.entryCount()), 8);
  await page.close();
});

// ---------------------------------------------------------------- Quick Access
test('quick access: search-first, keyboard select, copy password / username, Esc closes', async () => {
  const page = await open('open', '#quick');
  const input = page.getByRole('combobox');
  await visible(input);
  assert.ok(await input.evaluate((el) => el === document.activeElement), 'search input not focused');
  assert.equal(await page.getByRole('option').count(), 0, 'results shown before typing');

  await input.fill('etap');
  await page.getByRole('option').first().waitFor({ state: 'visible', timeout: T });
  assert.equal(await page.getByRole('option').count(), 3);
  assert.equal(await page.getByRole('option').first().getAttribute('aria-selected'), 'true');

  await input.press('ArrowDown');
  assert.equal(await page.getByRole('option').nth(1).getAttribute('aria-selected'), 'true');
  await input.press('Shift+Enter');
  await page.waitForFunction(() => window.__mock.lastCopied === 'etap1');
  await input.press('Enter'); // first Enter only arms the copy
  await visible(page.getByText(/Nhấn Enter lần nữa/));
  assert.equal(await mock(page, () => window.__mock.lastCopied), 'etap1', 'first Enter copied the password');
  await input.press('Escape'); // cancels the pending copy; the window stays open
  await visible(page.getByText(/Đã hủy/));
  assert.equal(await mock(page, () => window.__mock.hidden), false);
  await input.press('Enter');
  await input.press('Enter');
  await page.waitForFunction(() => window.__mock.lastCopied === 'CANARY_DEMO_ETAP_1');
  await visible(page.getByText(/Đã sao chép mật khẩu/));
  await page.waitForFunction(() => window.__mock.hidden === true); // closes after password copy

  await mock(page, () => { window.__mock.hidden = false; });
  await input.press('Escape');
  await page.waitForFunction(() => window.__mock.hidden === true);
  await page.close();
});

test('quick access: locked vault -> fail-closed message, no search box, no results', async () => {
  const page = await open('locked', '#quick');
  await visible(page.getByText('Két sắt đang khóa'));
  assert.equal(await page.getByRole('combobox').count(), 0);
  assert.equal(await page.getByRole('option').count(), 0);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.__mock.hidden === true);
  await page.close();
});

// ---------------------------------------------------------------- confirmation, crash, backend-initiated lock
test('copy confirmation (manager): cancel copies nothing, confirm copies', async () => {
  const page = await openManager();
  await visible(page.getByText('Facebook — Demo Personal').first());
  await btn(page, /Sao chép mật khẩu/).click();
  await visible(page.getByRole('dialog', { name: /Sao chép mật khẩu\?/ }));
  assert.match(await page.getByRole('dialog').innerText(), /lịch sử clipboard/i, 'no clipboard-history warning');
  await page.keyboard.press('Escape');
  assert.equal(await mock(page, () => window.__mock.lastCopied), null);
  await btn(page, /Sao chép mật khẩu/).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Sao chép', exact: true }).click();
  await page.waitForFunction(() => window.__mock.lastCopied === 'CANARY_DEMO_FB');
  await page.close();
});

test('sidecar crash: next action fails closed to Unlock; no stale card, no secret', async () => {
  const page = await open('open');
  await ask(page, 'fb chính');
  await visible(page.getByRole('article', { name: 'Facebook — Demo Personal' }));
  await mock(page, () => window.__mock.forceCrash());
  await ask(page, 'etap');
  await heading(page, 'Mở khóa két sắt');
  assert.equal(await page.getByRole('article').count(), 0);
  assert.ok(!(await page.content()).includes('CANARY'));
  await page.close();
});

test('backend-initiated lock (session lock / suspend / idle) is followed by the UI without any user action', async () => {
  const page = await open('open');
  await visible(page.getByLabel('Câu hỏi'));
  await mock(page, () => window.__mock.forceLock());
  await page.getByRole('heading', { name: 'Mở khóa két sắt' }).waitFor({ state: 'visible', timeout: 8000 });
  await page.close();
});

test('quick access: a window shown without the hotkey event refreshes its lock state on focus (no stale view)', async () => {
  const page = await open('locked', '#quick');
  await visible(page.getByText('Két sắt đang khóa'));
  // the vault becomes unlocked while the quick window is hidden; then the window is shown/focused by something other than the hotkey
  await mock(page, () => window.__mock.unlock('Synthetic-Master-Only-123!', 'C:\\Users\\Synthetic\\Documents\\my-vault.pvault'));
  await visible(page.getByRole('combobox')); // no focus event at all (ShowWindow case): the visible-page poll must find it
  // ...and the other way round: locked behind its back -> the next focus shows the locked screen, never data
  await mock(page, () => window.__mock.forceLock());
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await visible(page.getByText('Két sắt đang khóa'));
  assert.equal(await page.getByRole('option').count(), 0);
  await page.close();
});

test('background polls never call touch(): only real input events do (throttled to one per 30 s)', async () => {
  const page = await open('open');
  await visible(page.getByLabel('Câu hỏi'));
  await page.evaluate(() => { const b = window.__mock; window.__touches = 0; const o = b.touch.bind(b); b.touch = async () => { window.__touches++; return o(); }; });
  await page.waitForTimeout(7500);   // > 2 main polls (3 s) with no input at all
  assert.equal(await page.evaluate(() => window.__touches), 0, 'a timer/poll called touch()');
  await page.mouse.move(200, 200); await page.mouse.move(210, 215); await page.keyboard.press('Shift');
  assert.equal(await page.evaluate(() => window.__touches), 0, 'input within 30 s of the touch at unlock is throttled (no extra touch)');
  await page.waitForTimeout(24000);  // > 30 s since the touch at unlock
  await page.mouse.move(300, 300);
  assert.equal(await page.evaluate(() => window.__touches), 1, 'positive control: a real input after 30 s must reach touch() exactly once (otherwise the counter proves nothing)');
  await page.close();
  const q = await open('open', '#quick');
  await visible(q.getByRole('combobox'));
  await q.evaluate(() => { const b = window.__mock; window.__touches = 0; const o = b.touch.bind(b); b.touch = async () => { window.__touches++; return o(); }; });
  await q.waitForTimeout(5000);      // Quick Access polls the lock state every 2 s
  assert.equal(await q.evaluate(() => window.__touches), 0, 'Quick Access polling called touch()');
  await q.close();
});

