# Personal Vault — runnable synthetic MVP

**KHÔNG nhập dữ liệu thật.** Đây là bản thử nghiệm, không phải password manager đã security audit. Xem SPEC.md.

## Chạy trên Windows (chưa kiểm chứng trên Windows)
Cài Python 3.11+ (bao gồm Tcl/Tk), mở PowerShell trong thư mục giải nén. Cài dependency cần Internet hoặc wheel offline đã được kiểm tra; app khi chạy không gọi Internet.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m personal_vault.app
```

1. Chọn **Tạo demo 500 mẫu**. Chọn đường dẫn file vault synthetic ngoài repo, nhập master password thử nghiệm (>=12 ký tự).
2. Tìm `fb chính`, `fb bán hàng`, `PSCAD`, `etap server 15`, `cho tôi tài khoản fb chính`. Chọn dòng kết quả, xem/copy dữ liệu giả.
3. Thử thêm/sửa/xóa tài khoản giả, khóa và mở lại; import fixture `fixtures/demo_import.txt` (dùng vault mới để tránh trùng). Backup vào file mới và mở backup để verify.
4. Không để vault thật/script thật ở workspace. Không chạy AI Coding dưới user có quyền truy cập dữ liệu thật.

## Linux test
```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
xvfb-run -a python -m unittest discover -s tests -v
python -m personal_vault.app
```

## Supported import formats
- UTF-8 `.txt`: `Account: ...`, `Name: ...`, `Pass: ...`, optional `Aliases: ...; ...`, `Description: ...`, `Tags: ...`, `URL: ...`. Blank line separates records; no blank lines inside one record.
- CSV header: `account,name,pass,aliases,description,tags,url` (optional columns may be omitted). Semicolon-separated aliases/tags.
- JSON array of objects with same keys; aliases/tags may be arrays of strings.
- `.ps1`: each field is a `# Account: ...` comment; `.bat`: `REM Account: ...` or `:: Account: ...`. Any nonempty executable/unrecognized line rejects the batch. No execution, interpolation or arbitrary script analysis.

## Evidence & limitations
RED_BASELINE.txt: original core tests before implementation. TEST_REPORT.txt: measured test output incl. UI smoke on Linux virtual display. SPEC.md: requirements, threat model and outstanding gates. No Windows EXE yet, no production data, no security guarantee. KDBX is not implemented; `.pvault` is a prototype authenticated-encryption container. Do not share any vault file with the application bundle.
