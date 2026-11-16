import { chromium } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

async function run() {
  const outDir = path.resolve('screenshots');
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1200, height: 800 },
    deviceScaleFactor: 1.25 // Test DPI 125%
  });

  console.log('Navigating to http://127.0.0.1:4173...');
  await page.goto('http://127.0.0.1:4173/');

  // 1. Screen 1: Unlock screen
  await page.waitForSelector('text=Personal Vault');
  await page.screenshot({ path: path.join(outDir, '01_unlock_screen.png') });
  console.log('Screenshot 1 captured: 01_unlock_screen.png');

  // 2. Unlock with Demo button
  await page.click('text=Mở nhanh bộ dữ liệu mẫu');
  await page.waitForSelector('text=ETAP Server 15');
  await page.screenshot({ path: path.join(outDir, '02_vault_manager.png') });
  console.log('Screenshot 2 captured: 02_vault_manager.png');

  // 3. Search and Quick Access with Reveal Password
  await page.fill('input[placeholder*="Tìm tài khoản"]', 'fb chính');
  await page.waitForSelector('text=Facebook — Demo Personal');
  await page.click('text=Hiện 15s');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '03_search_reveal.png') });
  console.log('Screenshot 3 captured: 03_search_reveal.png');

  // 4. Import preview modal
  await page.click('text=Import');
  await page.waitForSelector('text=Xem trước dữ liệu Import');
  await page.screenshot({ path: path.join(outDir, '04_import_preview.png') });
  console.log('Screenshot 4 captured: 04_import_preview.png');

  await browser.close();
  console.log('All screenshots completed successfully!');
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});

