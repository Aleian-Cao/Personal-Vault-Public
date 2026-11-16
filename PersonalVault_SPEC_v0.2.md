# Personal Vault — SPEC v0.2 | Local AI Assistant

**Ngày cập nhật:** 2026-11-12  
**Trạng thái:** Desktop Candidate / synthetic-only QA / chưa nghiệm thu dữ liệu thật  
**Owner:** Người dùng cá nhân  
**Phạm vi:** Windows desktop, chatbot-first, offline, bảo mật, test-first  
**Thay thế:** SPEC v0.1 (Python/Tkinter prototype). Đây là phiên bản đặc tả, không phải số phiên bản phát hành EXE.

## 1. Product intent

Personal Vault là trợ lý cá nhân local giúp Owner tìm đúng thông tin đăng nhập trong hàng trăm hoặc hàng nghìn bản ghi bằng cách hỏi tự nhiên, theo tên ứng dụng, tên gợi nhớ, số máy chủ hoặc ngữ cảnh hội thoại. **Chatbot Search là chức năng trung tâm; Vault Manager là nơi quản lý dữ liệu.**

Triết lý sản phẩm:

> AI hiểu câu hỏi. Vault cung cấp sự thật. Backend kiểm soát quyền. Người dùng quyết định khi nào lấy mật khẩu.

- Local-first: không cloud, không tài khoản dịch vụ AI, không API inference bên ngoài, không telemetry.
- Lightweight: search xác định chạy tức thời; Qwen3 local chỉ được gọi khi cần, không bắt buộc GPU hoặc model để dùng chức năng tra cứu cơ bản.
- Shareable app, private data: ứng dụng/source có thể phân phối độc lập với dữ liệu, model và khóa của Owner; hình thức license phân phối vẫn cần chốt.
- Chính xác hơn khả năng hội thoại: không trả nhầm tài khoản để tăng tỷ lệ tìm thấy; không bịa credential.
- Không tự đăng nhập, không chạy script, không tự mở địa chỉ máy chủ hoặc tự thao tác hệ thống.

**Non-goals:** cloud sync, mobile, browser extension, TOTP/attachments, auto-login, autonomous agent, fine-tuning bằng dữ liệu cá nhân, vector DB hoặc MCP server trong phạm vi hiện tại.

## 2. Personas, trải nghiệm và phạm vi

### 2.1 Personas

| Actor | Nhu cầu | Quyền |
|---|---|---|
| Owner | Tra cứu, lưu, sửa, import, backup tài khoản của mình | Quản lý vault sau xác thực; chủ động reveal/copy |
| AI Coding / QA | Phát triển, test, build | Source, synthetic fixtures, test artifacts; không truy cập credential thật |
| Người nhận ứng dụng | Dùng phần mềm độc lập | Tạo vault riêng; không nhận dữ liệu hoặc khóa của Owner |

### 2.2 User journey

1. Mở lần đầu: Welcome → Tạo két sắt mới / Mở két sắt có sẵn / Dùng thử dữ liệu mẫu.
2. Tạo mới: đặt master password, xác nhận, chọn vị trí lưu ngoài repo/build/cloud-sync → tạo vault trống → Chatbot với hướng dẫn thêm hoặc nhập dữ liệu.
3. Mở lại: chọn vault đã biết → nhập master password → Chatbot. Nếu file mất/di chuyển, yêu cầu chọn lại; không tự ghi đè hoặc tạo lại.
4. Hỏi `PSCAD`, `fb chính`, `fb bán hàng`, `ETAP server 15`, hoặc câu hỏi tiếng Việt tự nhiên.
5. Chatbot trả account card hoặc danh sách cần chọn. Password luôn che; chỉ reveal/copy bằng thao tác trực tiếp.
6. Hỏi nối tiếp `PSCAD` → `máy 2`: dùng ngữ cảnh phiên hiện tại để lọc đúng nhóm.
7. Mở Vault Manager khi cần thêm/sửa/xóa, alias, ghi chú, import hoặc backup.
8. Quick Access qua Ctrl+Alt+V: cửa sổ compact, tìm và chọn bằng bàn phím; Esc đóng cửa sổ tìm nhanh. Nếu chưa mở khóa, chuyển Unlock. Không được bypass backend lock.

### 2.3 Quy tắc UX

- Chatbot là màn hình mặc định sau unlock; lịch sử hội thoại chỉ trong phiên, không lưu file.
- Không yêu cầu người dùng học cú pháp; hỗ trợ alias, tiếng Việt có/không dấu, câu hỏi nối tiếp.
- Một kết quả chính xác: hiển thị card có Account, Name, Pass (masked), alias và mô tả nếu có. Nhiều kết quả: chọn rõ ràng; fuzzy: chỉ gợi ý.
- Không kết quả: nói không tìm thấy và đề nghị điều chỉnh; không tạo tài khoản giả.
- Form thêm/sửa ưu tiên ba trường chính; alias/tag dùng chip, trường phụ dễ mở rộng, ẩn internal UUID.
- Edit password trống = giữ nguyên; không gửi mask làm giá trị. Lưu/xóa cần xác nhận phù hợp.
- Welcome, Unlock, Empty Vault, Loading, Error, Locked và Demo là các trạng thái tách biệt; không hiện lỗi validation trước submit.
- Demo có nhãn cố định, dữ liệu và session riêng; số lượng hiển thị đúng thực tế (fixture nhỏ khác bộ test 500).
- Dùng design tokens thống nhất (slate + blue-600 primary + semantic); không tự phá vỡ bố cục chuẩn. Hỗ trợ keyboard/focus, DPI 100/125/150%, tiếng Việt nhất quán.
- URL web chỉ mở sau thao tác rõ ràng và kiểm tra scheme http/https; host hoặc custom scheme chỉ copy, không execute.

## 3. Data contract và nguồn sự thật

### 3.1 Entry

| Trường | Loại | Quy tắc |
|---|---|---|
| `id` | UUID | Ổn định, unique, do backend sinh |
| `account` | string, bắt buộc | Tài khoản gì / ứng dụng / dịch vụ |
| `name` | string, bắt buộc | Username/email, không phải display name |
| `password` | string, bắt buộc | Giữ nguyên ký tự, không trim/normalize |
| `aliases` | string[], tùy chọn | Tên gợi nhớ như `fb chính`, `etap 15` |
| `description` | string, tùy chọn | Ghi chú riêng, có thể chứa thông tin nhạy cảm |
| `tags` | string[], tùy chọn | Phân loại và hỗ trợ retrieval |
| `url` | string, tùy chọn | Website hoặc host; không tự thực thi |

Tất cả trường, kể cả metadata, đều nhạy cảm và được bảo vệ khi lưu. Không dùng password làm search index. Chặn trùng `(normalized account, name)` khi CRUD/import; alias trùng được phép nhưng phải disambiguate. Mật khẩu không được gửi qua list/search hoặc model.

Giới hạn kế thừa prototype: 10.000 entries, vault/nguồn 32 MiB, UTF-8 (hỗ trợ BOM nếu parser đã kiểm chứng), mỗi string 16.384 ký tự, tối đa 100 aliases/tags. Mọi thay đổi giới hạn cần regression và đo tài nguyên.

### 3.2 Search result contract

Backend trả `status: exact | ambiguous | suggested | none`, `entries[]` gồm metadata đã cho phép, `session_generation`, `request_id`. Không có password thật trong search/list response; dùng `has_password` hoặc mask cố định tại UI. Kết quả cũ không được render sau khi query thay đổi, chuyển vault hoặc lock.

### 3.3 Session và chat

- Backend là nguồn sự thật về lock/unlock, active vault và session generation.
- Chat state chỉ giữ trong RAM: query đã xử lý, nhóm kết quả/ID, ngữ cảnh ngắn, không lưu mật khẩu vào message.
- Account card chỉ giữ metadata cần thiết. Reveal là trường hiển thị tạm riêng, không nằm trong transcript; native copy không trả password về JS.
- Lock/switch vault/exit hủy hoặc vô hiệu hóa request đang chờ, xóa view, search index, chat state, reveal state và reference khóa. Không cam kết zeroization vật lý của Python/JS/LLM runtime.

## 4. Architecture & decisions

### 4.1 Desktop

```
React 18 + TypeScript + Tailwind 3 (Chatbot / Manager / Quick Access)
        |
        v
Tauri v2 + WebView2 (host.ts / restricted native commands)
        |
        v
Python sidecar — framed JSON-RPC over stdin/stdout
        |
        +-- Vault Security Core (auth, CRUD, import, backup)
        +-- Deterministic Search / Session Router
        +-- LocalIntentEngine --> isolated local inference worker
        |
        v
Encrypted .pvault (prototype storage)
```

- Giữ Python core đã có 48 baseline tests theo báo cáo Master; không viết lại crypto cho task Chatbot.
- React không gọi API hệ điều hành trực tiếp; `host.ts` là lớp giao tiếp. Mock host chỉ dùng dev/test, không fallback production.
- Tauri quản lý cửa sổ, global hotkey, single instance, native clipboard, lifecycle sidecar. Không arbitrary shell/file commands, không mở HTTP listener.
- JSON-RPC có allowlist, schema/size limits, request ID, timeout, response correlation, session generation; không log payload. Reject malformed/unauthorized commands; sidecar crash → khóa UI/fail closed, không dùng cache cũ.
- Qwen chạy qua adapter/worker offline; ưu tiên tách khỏi process nắm vault, không nhận đường dẫn vault, key hay quyền gọi Vault Tools. Không dùng HTTP inference server. Không mặc định worker có OS sandbox; phải ghi rõ quyền thực tế.
- Tkinter `personal_vault.app` giữ làm fallback và nơi thử inference với synthetic trước khi tích hợp Tauri.
- Deviation so với APP_ARCHITECTURE: dùng stdio thay FastAPI loopback vì dữ liệu đăng nhập. Giữ boundary UI/host/service; kiểm tra đóng gói sidecar onedir theo chuẩn hoặc ghi rõ lý do ngoại lệ onefile và evidence temp cleanup.
- Không ghi dữ liệu cạnh EXE hoặc trong repo. Mặc định thư mục dữ liệu riêng trong `%LOCALAPPDATA%\PersonalVault\` (hoặc namespace công ty/sản phẩm đã được thống nhất), chỉ lưu config không chứa secret và tham chiếu vault cần thiết; đường dẫn cũng được coi là nhạy cảm, không log.
- Global-docs là SSOT về UI/architecture/versioning. Bản build nội bộ dùng build ID; không tự đúc số phát hành.

### 4.2 Storage — giữ nguyên baseline, chưa production-approved

Container `.pvault`: magic/version, salt 16 bytes, nonce 12 bytes, AES-256-GCM ciphertext + tag; header authenticated AAD. Argon2id m=65536 KiB, t=3, p=1, output 32 bytes. Salt ngẫu nhiên per vault, nonce ngẫu nhiên mới per write. Đây là contract v0.1 kế thừa; cần xác minh implementation thực tế trước nghiệm thu, không tự viết cryptographic primitives.

Atomic encrypted temp cùng thư mục, fsync, replace; create/backup không overwrite (kiểm tra phương thức exclusive trên NTFS và lỗi filesystem). OS sidecar lock + in-process guard, hash check trước ghi/backup theo báo cáo hardening. Không ghi plaintext trung gian. Bảo toàn file gốc nếu save lỗi. Không chống rollback ciphertext hợp lệ; concurrent/path alias/reparse point và crash recovery vẫn cần review.

Master password tối thiểu 12 ký tự (policy prototype, khuyến nghị passphrase dài mạnh); không lưu master password, không recovery mật khẩu chính. Backup dùng cùng key context và master password gốc; không tự restore đè file gốc.

KDBX 4.x vẫn là phương án ưu tiên về tương thích/phục hồi; chưa quyết định. `pykeepass` GPL-3.0 được Master nêu là vướng license phân phối; cần Owner chốt source/EXE policy, review license và dependency chain. Không tự migrate dữ liệu thật hoặc đổi format. Nếu đổi, có compatibility, migration/rollback và backup tests trước.

## 5. AI 8-Layer Production Engineering

Tám tầng là trách nhiệm logic trong ứng dụng, **không phải tám microservice**.

| Layer | Contract | Acceptance |
|---|---|---|
| 1 Model & Serving | Qwen3-0.6B-Q8_0 GGUF local CPU, lazy load, non-thinking; model tùy chọn | Inference thật trên Windows, đo load/warm/RAM; fallback khi thiếu hoặc lỗi |
| 2 Prompt Management | Prompt versioned, intent schema, context tối thiểu, không sinh credential | JSON/schema fail → reject/fallback; không đổi định danh người dùng |
| 3 Retrieval / RAG | Exact, alias, token, fuzzy suggestion; index RAM; vault là nguồn sự thật | Tìm đúng và không nhầm số; không cần embedding/vector DB |
| 4 Tools | Search/read metadata qua core; reveal/copy/CRUD/import là backend operations | Model không gọi tool secret; không arbitrary command/filesystem |
| 5 Authorization | Backend lock state, active session, entry ID, generation | Locked/stale/wrong-session requests bị chặn, kể cả IPC trực tiếp |
| 6 Guardrails | Secret isolation, untrusted input, validate query/identity, ambiguity handling | Không hallucinate credential, không auto-reveal/copy, không prompt-injection execution |
| 7 Router & Cache | Deterministic-first, AI chỉ khi cần; timeout/cancel, RAM-only | Exact nhanh không load Qwen; stale result không xuất hiện sau lock |
| 8 Observability & Evals | Test-first, synthetic ground truth, metrics không chứa secret | So sánh search thường vs AI, latency/RAM/accuracy và security regressions |

### 5.1 Model & runtime contract

Model tham chiếu (cấu hình tùy chọn qua env `PVAULT_MODEL_PATH` / `PVAULT_LLAMA_DIR`):
`<LOCAL_MODELS_DIR>\Qwen3-0.6B-Q8_0.gguf`

Đường dẫn do người dùng/máy dev cấu hình qua biến môi trường hoặc tham số, không hardcode trong bản phân phối; chỉ dùng file model read-only. Runtime đề xuất llama.cpp/llama-cpp-python CPU, context 2048, output tối đa 128 tokens, non-thinking (xác minh chat template/cấu hình tương thích; không chỉ giả định flag hoạt động), timeout hữu hạn và cancel. Thông số là starting configuration, chưa benchmark. Không bundle GGUF trong EXE, không tự tải model.

### 5.2 Prompt và structured output

Input được phép: câu hỏi đã kiểm soát, từ khóa dịch vụ và định danh cần thiết, ngữ cảnh tối thiểu của lượt trước (ví dụ nhóm `PSCAD` và số máy). Không đưa database, mật khẩu, master password, raw notes, username, URL hay transcript chứa secrets vào model. Metadata nhạy cảm chỉ được dùng ở backend; nếu cần đưa alias hoặc tên dịch vụ vào model, tối thiểu hóa và ghi rõ policy.

Không thể đảm bảo redaction nhận ra mọi mật khẩu tùy ý. Với input có dấu hiệu chứa secret, multiline credential/script, hoặc không thể xác định an toàn, không chuyển sang Qwen; giữ tra cứu xác định hoặc yêu cầu viết lại. Không ghi input thô vào logs. Dữ liệu do người dùng/import cung cấp là untrusted data, không phải chỉ thị model.

Ví dụ output hợp lệ:

```json
{
  "intent": "find_account",
  "query": "etap server 15",
  "service": "ETAP",
  "server_id": 15
}
```

Schema allowlist `find_account | refine_search | clarify | unsupported`; query giới hạn độ dài, service/server_id tùy chọn, không cho tool name, path, code, password hay entry ID do model sinh. Reject extra fields và sai kiểu. Không chấp nhận model thay đổi số định danh rõ ràng trong input; kiểm tra số từ ngữ cảnh đã xác nhận và hỏi lại khi mâu thuẫn. Output là đề xuất tìm kiếm, không phải authorization hoặc bằng chứng.

### 5.3 Search routing

1. Xác minh session; chuẩn hóa câu hỏi tiếng Việt và context an toàn.
2. Deterministic exact title/alias và numeric constraints; nếu rõ ràng, trả ngay không load model.
3. Token/keyword search trên account, alias, tags, description; description không đưa vào prompt. Multiple results → chọn thủ công.
4. Nếu query tự nhiên phức tạp hoặc cần hiểu follow-up, gọi Qwen khi input đủ điều kiện. Validate output và giữ nguyên identity constraints; chạy search backend lại.
5. Fuzzy hoặc Qwen-derived result không đủ chắc chắn → suggested/ambiguous, yêu cầu chọn hoặc xác nhận; không tự chọn mật khẩu.
6. Không kết quả → none; timeout/missing model/invalid JSON → deterministic fallback hoặc hỏi lại, không block UI.

`ETAP server 15`, `server15` không match 1/5/11/51. Số định danh phải là token chính xác trong title/alias, không fuzzy số. `PSCAD → máy 2` chỉ lọc trong nhóm đã xác nhận; đổi chủ đề rõ ràng phải reset context. Không lấy entry ID tùy ý do AI sinh.

### 5.4 Tools & secret boundary

| Operation | Bên thực thi | Điều kiện |
|---|---|---|
| `search_accounts(query)` | Python core | Unlocked; query validated |
| `get_account_metadata(id)` | Python core | Unlocked, valid ID thuộc vault hiện tại |
| `reveal_password(id)` | Python core → UI tạm | Explicit click, current session/ID; 15s |
| `copy_username/password(id)` | Native host + core | Explicit action; password không trả vào JS |
| CRUD/import/backup/restore | Core | Unlocked, user action, confirmation khi cần |
| `lock()` | Backend | Hủy quyền session, pending results và view |

Model chỉ đề xuất query; không được gọi reveal, copy, CRUD, filesystem, shell hoặc mở URL. Native copy và explicit click không thay thế authorization backend; compromised client không được xem là trusted.

## 6. Functional acceptance

| ID | Requirement | Acceptance |
|---|---|---|
| FR-01 | Vault lifecycle | First-run Welcome; tạo vault trống với master password + xác nhận; reopen/unlock; missing file recovery; sai password/corruption fail closed; không overwrite |
| FR-02 | CRUD | 3 trường bắt buộc; edit password trống giữ secret, không lưu mask; delete confirm; duplicate policy |
| FR-03 | Search | Unicode Việt có/không dấu; exact/alias > token > fuzzy suggestion; multiple manual selection |
| FR-04 | Numeric identity | `server15` và `ETAP server 15` không nhầm 1/5/11/51; không fuzzy số |
| FR-05 | Chatbot-first | Natural query, multi-turn, account cards, ambiguity/none; Qwen thật khi cần; fallback khi thiếu model |
| FR-06 | Import | Chọn file/thư mục do Owner chỉ định; UTF-8 txt/CSV/JSON và bat/ps1 comment data; parser tĩnh, không execute; preview đầy đủ, new/duplicate/invalid counts; xác nhận và atomic save |
| FR-07 | Reveal/copy | Mask default; reveal 15s, ẩn khi chuyển entry/lock; copy explicit warning/confirm, native password copy, best-effort clear sau 20s nếu clipboard còn thuộc app; cảnh báo history/cloud |
| FR-08 | Backup/restore | Encrypted backup exclusive, mở xác minh/recover riêng, không tự ghi đè vault gốc |
| FR-09 | Local | Không outbound network/HTTP listener/telemetry/cloud, không persist history, không bundle dữ liệu thật |
| FR-10 | Auto-lock | 5 phút idle; Windows session lock/suspend; lock backend độc lập UI, invalidate pending IPC/inference, clear state |
| FR-11 | Quick Access | Global Ctrl+Alt+V, compact window, keyboard navigation, Esc đóng; locked access yêu cầu unlock |
| FR-12 | Demo separation | Demo riêng vault/session/storage, nhãn cố định, đúng số mẫu; không trộn/ghi đè vault cá nhân |
| FR-13 | Error & recovery | Sidecar crash, missing model, timeout, wrong session, save fail, malformed request → fail closed hoặc fallback an toàn; không stale secrets |
| FR-14 | Distribution | Clean EXE + sidecar, không model/data thật, no orphan processes; standard-user/clean-machine QA, reproducible manifest |

Import parser chỉ hỗ trợ format được định nghĩa và kiểm thử; không tuyên bố hiểu mọi script. Hỗ trợ batch folder là mục tiêu cần triển khai/đo, không được tự quét filesystem. Không đọc file thật để thiết kế parser; dùng fixture đã redacted hoàn toàn hoặc synthetic tương đương. Nguồn plaintext không tự xóa; Owner xử lý sau xác minh dữ liệu và backup.

## 7. Threat model / security boundaries

### 7.1 Mục tiêu bảo vệ

- Vault bị copy, đọc bằng editor, sai master password, ciphertext bị sửa.
- Accidental disclosure qua logs, repo, build, IPC payload, browser storage, model prompt, clipboard, import temp, backup.
- Unauthorized access khi locked, wrong session/ID, stale responses, invalid requests, sidecar crash.
- Script/import/notes/model output không đáng tin cậy; không execute, không mở custom protocol tùy ý.
- Cô lập demo khỏi private vault; tách ứng dụng phân phối khỏi dữ liệu.

### 7.2 Giới hạn

Không cam kết chống malware/keylogger, admin/debugger, memory dump, screen capture, pagefile/crash dump, clipboard history/cloud sync, file nguồn plaintext hoặc rollback ciphertext hợp lệ. Python/Rust/JS/WebView/LLM runtime không được tuyên bố secure zeroization nếu chưa chứng minh. Lock là revoke access + xóa reference/view best effort; cần xem cả worker inference/KV cache và request đang chạy.

Không mở HTTP listener không đồng nghĩa không có mọi rủi ro IPC hay không có outbound network. Chưa có bằng chứng OS-enforced network deny, sandbox/DLP hoàn chỉnh. Kiểm tra network cả process tree, WebView2, sidecar và worker; CSP/capability/navigation restrictions, devtools production policy và dependency review. Không ghi secret vào stdout/stderr diagnostics, URL, browser storage hoặc crash reports. Canary scan chỉ là test leakage có phạm vi, không thay security audit.

### 7.3 Development / private data separation — mandatory

- Repo, CI, test/build, screenshots, logs, prompts của AI Coding: synthetic only.
- Private vault, scripts, backups, master password ngoài workspace, ngoài cloud-sync; AI Coding chạy tài khoản/VM không được cấp quyền đọc chúng, không mount private folders, không dùng cùng user token khi vault thật đang mở.
- `.gitignore` và thư mục riêng không phải access control. File source plaintext cần bảo vệ từ trước import.
- Owner tự tạo/import dữ liệu thật sau security acceptance, không có AI Coding tham gia. Không yêu cầu paste real credentials hoặc script thật vào chat.
- **Synthetic-only là rào của development/QA, không phải giới hạn sản phẩm vĩnh viễn.** App phải có luồng tạo vault trống/import thực tế, được kiểm thử trước bằng dữ liệu giả.

## 8. Test-first, evaluation và evidence

### 8.1 Baseline

Theo các Wave Digest do Master cung cấp (chưa audit độc lập source/log):

- v0.1 prototype: 33/33 tests PASS trên Windows; hardening: 48/48 PASS.
- Tkinter fallback: 15.11 MiB, startup ~1.48s, working set báo cáo 38.74 MiB.
- Desktop candidate: Tauri + Python stdio sidecar, ~24.28 MiB hai binary, startup ~2.04s, 76.73 MiB chỉ shell+sidecar; **chưa xác minh toàn bộ WebView2 process tree**.
- React preview đã có các màn hình quản lý và demo; screenshot cho thấy create tab chỉ tạo demo, startup mặc định Unlock. Cần sửa product lifecycle; preview không phải E2E trên EXE.
- Chưa có evidence Qwen thật, chatbot integrated, IPC/security regression đầy đủ, canary scan toàn phạm vi hoặc interactive E2E trực tiếp trên binary. Không đánh dấu DONE.

### 8.2 Quy trình thực thi

Viết synthetic tests và ground truth trước khi triển khai; ghi RED có ý nghĩa (không nhầm import error với assertion failures), sửa rồi chạy GREEN. Giữ 48 baseline tests; bổ sung tests cho các đường đi mới. Không dùng credential thật để cải thiện chất lượng.

Lệnh baseline từ `PersonalVault_MVP`:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### 8.3 Bộ eval bắt buộc

| ID | Test | Expected |
|---|---|---|
| E01 | 500 synthetic entries, exact/alias tiếng Việt có/không dấu | Đúng entry ID, không gọi Qwen nếu exact |
| E02 | `ETAP 15` vs 1/5/11/51, viết liền, lỗi chính tả | Không nhầm số, suggestion không auto-select |
| E03 | `PSCAD`, alias collision | Ambiguous, người dùng chọn |
| E04 | `cho tôi tài khoản fb chính`, câu hỏi tự nhiên dài | Query đúng hoặc safe fallback |
| E05 | `PSCAD` → `máy thứ hai`; đổi chủ đề | Context đúng, không dùng context sai nhóm |
| E06 | Unknown query, Qwen hallucination, invalid JSON | None/clarify/fallback; không sinh credential |
| E07 | Missing model, cold load, timeout/cancel, worker crash | UI responsive, deterministic search vẫn dùng được |
| E08 | Prompt injection, raw note/script, canary input | Không execute, không secret vào model/log ngoài policy |
| E09 | Locked/stale/unauthorized IPC, switch vault, late reveal | Reject và không render dữ liệu cũ |
| E10 | Fresh launch/create/reopen/missing/demo isolation | Đúng state; không overwrite |
| E11 | CRUD unchanged password, alias collision, import duplicate/invalid | Giữ secret chính xác, preview/atomic save |
| E12 | Wrong password/tamper/nonce/duplicate ID/atomic failure/concurrency | Fail closed, file gốc nguyên vẹn |
| E13 | Clipboard expiry, history/cloud, idle/session lock/suspend | Native copy, clear phù hợp, backend lock |
| E14 | EXE E2E, global hotkey, single-instance, sidecar crash/exit | Không mock fallback hoặc orphan process |
| E15 | Canary scan repo/build/temp/_MEI/WebView2/log/cache/crash behavior | Không rò rỉ ngoài nguồn/hiển thị synthetic được chỉ định |
| E16 | Backup/recovery, clean distribution, standard user | Mở backup chính xác; không kèm dữ liệu riêng |

Tạo tối thiểu 100 truy vấn synthetic có ground truth, gồm các nhóm E01–E08; tách corpus dùng phát triển prompt và held-out eval. Báo accuracy/recall và số wrong-account, false exact, ambiguity, none, fallback, AI calls. So sánh cùng corpus deterministic-only vs Qwen-assisted; không tối ưu chỉ theo tỷ lệ trả kết quả. Mục tiêu nghiệm thu: 100% critical numeric/session/secret tests PASS và không wrong-account ở tập eval; các lỗi retrieval khác báo rõ. Nếu AI không tăng chất lượng đáng kể hoặc quá chậm, giữ deterministic fallback và chưa duyệt AI integration.

### 8.4 Performance targets (đề xuất cần đo)

- 500/5.000 entries: exact/alias p95 <100 ms trên Windows mục tiêu; đo nhiều lượt, cold/warm riêng.
- Desktop startup <3s đến trạng thái dùng được; báo RAM cả process tree ở locked/unlocked, 500/5.000 entries và import. Mục tiêu baseline idle <150 MiB không bao gồm model hoặc peak unlock; nếu vượt phải báo, không tự nới ngưỡng.
- Qwen: đo cold load, warm inference p50/p95, tokens/s, CPU, RAM tăng thêm, timeout/cancel. Mục tiêu thử nghiệm warm p95 ≤3s, timeout 10s với fallback; chưa phải số đã đạt và điều chỉnh phải có evidence. Model không được làm chậm exact search.
- Ghi model identity/hash, runtime version, config, máy test và số mẫu; không thu query/credential thật.

## 9. Release acceptance / outstanding

Không mở thêm tính năng ngoài Chatbot Search + product lifecycle + security closure. Thực thi tuần tự, không chờ quyết định storage để thử inference synthetic.

| Hạng mục | Trạng thái / điều kiện đóng |
|---|---|
| Functional baseline | PASS theo báo cáo 48 tests; giữ regression |
| Chatbot Qwen local | OPEN: inference thật + eval + integration trên desktop |
| Product lifecycle | OPEN: Welcome/create trống/reopen/demo isolation, screenshots EXE |
| IPC and security | OPEN: regression, CSP/capabilities, native copy, stale/lock/crash, canary, independent review |
| Storage | OPEN: Owner quyết định KDBX/license hoặc duyệt container hiện tại sau review |
| Import real formats | OPEN: synthetic/redacted fixture cho từng format, batch/preview/validation |
| Windows packaging | Candidate đã build; clean-machine + true standard-user E2E, full process metrics, provenance/hash, dependency/license manifest |
| Distribution | Chưa ký số; signing/installer/license/release policy cần chốt; không publish/push tự động |
| Private data | NOT AUTHORIZED: chỉ Owner nhập sau security acceptance và isolation thực tế |

Nghiệm thu yêu cầu artifact path/hash, test command + raw summary, screenshots từ EXE (Welcome, Create, Unlock, Chatbot, Quick Access, Manager, Import), PASS/FAIL/NOT_TESTED theo từng yêu cầu, benchmark, limitations và outstanding decisions. Không dùng screenshot browser preview thay thế desktop E2E; không dùng 48 core tests làm bằng chứng IPC/AI; không tuyên bố an toàn tuyệt đối.

## 10. Next execution — AI Coding

1. Chạy `personal_vault.app` với synthetic; kiểm tra model path và llama.cpp compatibility trong môi trường dự án riêng.
2. Viết intent/router/chat/session/security evals trước; chạy Qwen thật, đo và so sánh với deterministic search.
3. Tích hợp Chatbot-first vào React/Tauri/stdio sidecar, hoàn thiện create/reopen/demo separation; giữ Manager và Quick Access.
4. Test binary Windows, khắc phục regression trong scope, build candidate nếu có thay đổi; bảo toàn fallback và báo hash thực tế.
5. Giao Wave Digest có evidence và phần OPEN; Owner review UX và quyết định storage trước production acceptance.

**Rào:** SYNTHETIC ONLY. Không đọc hoặc yêu cầu credential thật. Không đổi crypto/storage, không network, không nhúng GGUF, không publish/push. Tự quyết HOW trong phạm vi; không mở Wave mới. Không nhập dữ liệu thật chỉ vì test PASS.

---

**Nguồn cập nhật:** SPEC v0.1 do Owner cung cấp; các quyết định chatbot-first/Qwen local/8-layer và Wave Digest Desktop Integration trong cuộc hội thoại. Các chỉ số baseline là báo cáo, không phải phép đo độc lập của người viết đặc tả. Các mục tiêu hiệu năng AI, cấu hình worker và schema là đề xuất kỹ thuật cần kiểm chứng.
