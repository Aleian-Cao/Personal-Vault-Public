// Design-iteration screenshots from the mock bridge (SYNTHETIC). Real acceptance is done on the EXE (e2e/exe_e2e.mjs). Usage (from web/): node tests/ui_shots.mjs <outDir>
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const out = path.resolve(process.argv[2] ?? 'ui_shots');
fs.mkdirSync(out, { recursive: true });
const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { host: '127.0.0.1', port: 5197 }, logLevel: 'silent' });
await server.listen();
const base = server.resolvedUrls.local[0];
const browser = await chromium.launch();
const open = async (mock, hash = '') => { const p = await browser.newPage({ viewport: { width: 1040, height: 720 } }); await p.goto(`${base}?mock=${mock}${hash}`); return p; };
const ask = async (p, q) => { await p.getByLabel('Câu hỏi').fill(q); await p.getByLabel('Câu hỏi').press('Enter'); await p.waitForTimeout(500); };
const shot = (p, name) => p.screenshot({ path: path.join(out, name) });
try {
  let p = await open('fresh'); await p.getByRole('button', { name: /Tạo két sắt mới/ }).waitFor(); await shot(p, '01_welcome.png'); await p.close();
  p = await open('open'); await p.getByLabel('Câu hỏi').waitFor(); await p.waitForTimeout(400); await shot(p, '02_chat_empty.png');
  await ask(p, 'fb chính'); await shot(p, '03_exact.png');
  await ask(p, 'etap'); await shot(p, '04_ambiguous.png');
  await p.getByRole('list', { name: 'Chọn tài khoản' }).getByRole('button').nth(1).click(); await p.waitForTimeout(200); await shot(p, '04b_ambiguous_picked.png');
  await ask(p, 'zzzqq'); await shot(p, '05_not_found.png');
  await p.getByRole('article').first().getByRole('button', { name: /Sao chép mật khẩu/ }).click(); await p.waitForTimeout(300); await shot(p, '07_copy_confirmation.png');
  await p.keyboard.press('Escape');
  await p.getByRole('button', { name: 'Quản lý két sắt' }).click(); await p.getByText(/Tổng cộng/).waitFor(); await p.waitForTimeout(300); await shot(p, '06_vault_manager.png');
  await p.close();
  p = await open('open', ''); await p.getByLabel('Câu hỏi').waitFor(); await p.getByRole('button', { name: 'Trợ giúp' }).click(); await p.waitForTimeout(200); await shot(p, '08_help_popup.png'); await p.close();
  p = await open('locked'); await p.getByLabel('Master Password').waitFor(); await shot(p, '09_unlock.png'); await p.close();
} finally { await browser.close(); await server.close(); }
console.log('shots in', out);
