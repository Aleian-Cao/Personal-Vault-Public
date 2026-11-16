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
    deviceScaleFactor: 1.25 // DPI 125%
  });

  console.log('Navigating to http://127.0.0.1:4173...');
  await page.goto('http://127.0.0.1:4173/');

  // 1. Màn hình Unlock (Tab Mở Vault)
  await page.waitForSelector('text=Personal Vault');
  await page.screenshot({ path: path.join(outDir, '01_unlock_open_vault.png') });
  console.log('Saved: 01_unlock_open_vault.png');

  // 2. Màn hình Unlock (Tab Khởi tạo mới)
  await page.click('text=Khởi tạo mới');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '02_unlock_create_vault.png') });
  console.log('Saved: 02_unlock_create_vault.png');

  // Trở lại tab Mở Vault và unlock với demo
  await page.click('text=Mở Vault');
  await page.waitForTimeout(200);
  await page.click('text=Mở nhanh bộ dữ liệu mẫu');
  await page.waitForSelector('text=ETAP Server 15');
  await page.waitForTimeout(300);

  // 3. Vault Manager (Trang chính - Danh sách đầy đủ)
  await page.screenshot({ path: path.join(outDir, '03_vault_manager_overview.png') });
  console.log('Saved: 03_vault_manager_overview.png');

  // 4. Tìm kiếm tức thì theo alias & query
  await page.fill('input[placeholder*="Tìm tài khoản"]', 'etap 15');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '04_search_results.png') });
  console.log('Saved: 04_search_results.png');

  // 5. Trạng thái Reveal Password (Hiện 15s)
  await page.click('text=Hiện 15s');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '05_password_revealed.png') });
  console.log('Saved: 05_password_revealed.png');

  // 6. Trạng thái Copy Password thành công (Toast notification)
  await page.click('text=Copy Pass');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '06_password_copied_toast.png') });
  console.log('Saved: 06_password_copied_toast.png');

  // Xóa ô tìm kiếm để danh sách hiện đầy đủ
  await page.fill('input[placeholder*="Tìm tài khoản"]', '');
  await page.waitForTimeout(200);

  // 7. Modal Chỉnh sửa tài khoản (Edit Entry)
  await page.click('button[title="Chỉnh sửa tài khoản"]');
  await page.waitForSelector('text=Chỉnh sửa tài khoản');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '07_modal_edit_entry.png') });
  console.log('Saved: 07_modal_edit_entry.png');
  await page.click('text=Hủy');
  await page.waitForTimeout(200);

  // 8. Modal Thêm tài khoản mới (Add Entry)
  await page.click('text=Thêm mới');
  await page.waitForSelector('text=Thêm tài khoản mới');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '08_modal_add_entry.png') });
  console.log('Saved: 08_modal_add_entry.png');
  await page.click('text=Hủy');
  await page.waitForTimeout(200);

  // 9. Modal Xem trước Import dữ liệu (Import Preview)
  await page.click('text=Import');
  await page.waitForSelector('text=Xem trước dữ liệu Import');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '09_modal_import_preview.png') });
  console.log('Saved: 09_modal_import_preview.png');
  await page.click('text=Hủy bỏ');
  await page.waitForTimeout(200);

  // 10. Trạng thái Khóa Vault (Lock Vault action)
  await page.click('text=Khóa Vault');
  await page.waitForSelector('text=Personal Vault');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, '10_vault_locked_state.png') });
  console.log('Saved: 10_vault_locked_state.png');

  await browser.close();
  console.log('ALL UI SCREENS CAPTURED SUCCESSFULLY!');
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});

