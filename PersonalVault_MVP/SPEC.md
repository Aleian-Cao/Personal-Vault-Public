# Personal Vault — SPEC v0.1
**Status:** MVP synthetic-only / chưa cho phép dữ liệu thật. **Owner:** người dùng cá nhân. **Ngày:** 2026-11-12.

## 1. Product intent
Trợ lý quản lý thông tin đăng nhập local, nhẹ, tra cứu như hỏi người quen. Người dùng có thể chia sẻ app/source nhưng dữ liệu cá nhân không đi cùng. Không yêu cầu LLM, GPU, tài khoản cloud hoặc Internet lúc chạy. Không tự đăng nhập vào dịch vụ hay chạy script.

## 2. Personas & use cases
- Owner: tạo/mở vault bằng master password; hỏi `PSCAD`, `fb chính`, `fb bán hàng`, `ETAP server 15`; thêm/sửa/xóa dữ liệu và alias, ghi chú; sao lưu và mở bản backup.
- AI Coding: chỉ source, mock, test, build. Không quyền đọc vault, file script thật, master password hay backup thật. Không yêu cầu Owner paste dữ liệu thật vào chat.
- Người nhận ứng dụng: nhận bản phân phối sạch, tạo vault riêng; không nhận vault của Owner.

## 3. Data contract
Mỗi Entry có `id` (UUID), `account`, `name`, `password` (3 trường bắt buộc); `aliases[]`, `description`, `tags[]`, `url` (tùy chọn). `name` = username/email, không phải tên hiển thị. Không dùng password làm chỉ mục. Tất cả fields, kể cả alias, username, URL và note đều là sensitive. Chặn trùng `(normalized account, name)` khi import/CRUD; alias có thể trùng nhưng phải yêu cầu chọn. Mật khẩu giữ nguyên ký tự, không normalize. Giới hạn prototype: 10.000 entries, vault/nguồn 32 MiB, UTF-8, mỗi string 16.384 ký tự, tối đa 100 aliases/tags. Không hỗ trợ file attachment/TOTP ở v0.1.

## 4. Functional acceptance
| ID | Requirement | Acceptance |
|---|---|---|
| FR-01 | Create/unlock/lock | Sai password, dữ liệu hỏng: fail closed; không overwrite; lock xóa view và reference session |
| FR-02 | CRUD | Bắt buộc 3 trường; edit/delete có xác nhận lưu/xóa; password masked |
| FR-03 | Search | Unicode Việt có/không dấu, exact title/alias > token > fuzzy suggestion; multiple results luôn chọn thủ công |
| FR-04 | Numeric identity | `ETAP server 15` và `server15` không khớp 1/5/51; số phải nằm trong title/alias, không fuzzy số |
| FR-05 | Natural query | Nhận một số mẫu câu lệnh tiếng Việt: `cho tôi tài khoản ...`, `tìm ...`; không phải NLP tổng quát |
| FR-06 | Import | UTF-8 txt/CSV/JSON; bat/ps1 dạng comment data; parse tĩnh, reject file sai format/duplicate; preview, owner confirm, atomic save |
| FR-07 | Reveal/copy | Password che mặc định, reveal 15s; copy password explicit warning/confirm, best-effort clear sau 20s; lock clear nếu clipboard chưa thay đổi |
| FR-08 | Backup/restore | Tạo encrypted backup không ghi đè; mở backup riêng để xác minh/khôi phục; không tự thay dữ liệu gốc |
| FR-09 | Local | Không network, telemetry, API, history; dữ liệu mẫu tạo runtime; không bundle vault thật |
| FR-10 | Idle | 5 phút không thao tác trong app thì lock; Windows session lock/suspend handling là production gate chưa triển khai |

## 5. Architecture & decisions
Prototype: Python 3.11+ / Tkinter, core độc lập UI, argon2-cffi + cryptography. File `*.pvault` có magic/version, salt 16 bytes, nonce 12 bytes, AES-256-GCM ciphertext + tag; header được xác thực AAD. Argon2id: m=65536 KiB, t=3, p=1, output 32 bytes; random salt per vault, nonce per write. Không tự cài thuật toán mật mã. Ghi ciphertext vào temp cùng thư mục, fsync, atomic replace; create/backup dùng hard link exclusive (filesystem phải hỗ trợ, ví dụ NTFS; chưa test Windows). Không tạo plaintext file trung gian. Master password tối thiểu 12 ký tự chỉ là policy prototype, dùng passphrase dài ngẫu nhiên cho production. Không recovery master password. Backup mang cùng salt/key context và cần master password gốc.

**Deviation:** thiết kế ban đầu C# WPF + KDBX 4.x; runtime hiện có không hỗ trợ .NET/KDBX library. Prototype format không tương thích KeePass, chưa có security review. Production ưu tiên KDBX chuẩn hoặc review và duyệt rõ container hiện tại; không mặc định migrate dữ liệu thật vào prototype. Thay đổi storage phải có test compatibility/migration và quyết định Owner.

## 6. Threat model / boundaries
Bảo vệ mục tiêu: file vault bị copy hoặc mở bằng editor; sửa ciphertext; password sai; accidental disclosure qua logs/build/import. Không bảo vệ máy đã bị malware, keylogger, admin/debugger, memory dump, clipboard history, screen capture, file nguồn plaintext hoặc backup nguồn. Python/Tkinter không đảm bảo secure memory zeroization; secrets tồn tại trong RAM khi unlock; lock chỉ loại reference và UI best effort. Không lưu log nội dung. Không có cơ chế OS-enforced network deny, sandbox hoặc DLP; code không chủ động gọi network nhưng cần kiểm tra runtime khi production. Không chống rollback ciphertext hợp lệ hay concurrent writer; chỉ chạy một instance/one writer trên ổ local. Không lưu trên cloud-sync/network shares. Không có Windows session-lock, suspend, crash-dump/pagefile mitigation ở prototype. Không coi việc quét ciphertext bằng canary là security audit.

### Dev/data separation — mandatory
Development repo chỉ synthetic; private vault ở thư mục riêng, ngoài repo, ngoài cloud sync. Chạy AI Coding bằng tài khoản/VM riêng không có quyền truy cập private files; không cấp host mount chứa vault/script thật; không dùng cùng user token khi vault mở. .gitignore chỉ chống commit tình cờ, không phải access control. Không lưu dữ liệu thật vào fixtures, screenshots, clipboard của AI tool, test logs, CI hoặc artifacts. Owner thực hiện import sau nghiệm thu độc lập, không chạy AI Coding trong môi trường có credential thật. File script nguồn có thể chứa plaintext: không tự xóa nguồn, Owner tự xử lý bảo mật và backup sau khi xác minh import.

## 7. Test-first / gates
RED: tạo test trước core; baseline import fail do module chưa tồn tại (không phải 30 assertion failure). GREEN: `python -m unittest discover -s tests -v`, UI smoke cần display hoặc Windows. 500 synthetic accounts; test search 1/5/11/15/51, alias collision, unknown query, passwords excluded, parser reject commands/invalid/duplicate, encryption roundtrip, wrong key, tamper, locked, backup, nonce, duplicate ID, GUI unlock/search/reveal/lock. Report và synthetic fixtures không chứa secret thật. Performance: đo 500/5000 entries; mục tiêu exact/alias p95 <100ms trên máy mục tiêu, RAM idle <150MB excluding unlock peak; chưa benchmark Windows. Không claim production PASS.

## 8. Release acceptance / outstanding
1. Owner chốt target Windows phiên bản và storage KDBX/format; chọn thư viện maintained, review license/dependency chain, pin dependencies, verify build provenance.
2. Independent security review, fuzz parser/format, failure injection atomic saves, concurrent writer policy, stale backup/rollback; Windows standard user QA, clipboard history/cloud and session lock/suspend, no outbound connections, inspect temp/logs/build/crash behavior; test backup recovery and clean distribution.
3. Cần mẫu đã redacted của từng định dạng script thật để mở rộng parser. Không đọc script thật để phát triển. Hiện script import chỉ hỗ trợ comment format, không tự hiểu biến/lệnh, không quét thư mục hàng loạt. Import preview chỉ 10 dòng đầu, xác nhận toàn batch; production cần preview đầy đủ/trùng lặp theo từng record.
4. Build EXE Windows và test trên máy sạch; hiện chỉ source chạy Python, chưa có EXE. Không ký code hay phát hành production. Không nhập dữ liệu thật trước khi các hạng mục bảo mật được nghiệm thu.
5. Sau khi đạt gate, Owner tạo vault thật và import local; AI Coding không tham gia. Không mở rộng mobile/cloud/LLM/auto-login ở MVP.
