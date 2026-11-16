"""Tkinter local UI styled with slate/blue design tokens. Synthetic data only."""
from __future__ import annotations
import ctypes, os, time, tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog
from .core import (
    Entry,
    ImportPreview,
    MAX_BYTES,
    Vault,
    VaultError,
    default_vault_dir,
    inspect_import,
    is_inside_app_dir,
    norm,
    search,
    synthetic_entries,
)

IDLE_TIMEOUT_S = 300
SUSPEND_GAP_S = 15
REVEAL_TIMEOUT_MS = 15000
CLIP_TIMEOUT_MS = 20000

# UI Design Tokens (slate + blue-600 primary + semantic)
C_APP_BG = '#F9FAFB'
C_SURFACE = '#FFFFFF'
C_SUBTLE = '#F8FAFC'
C_DIVIDER = '#F1F5F9'
C_BORDER = '#E2E8F0'
C_TEXT_MAIN = '#0F172A'
C_TEXT_BODY = '#334155'
C_TEXT_MUTED = '#64748B'
C_TEXT_HINT = '#94A3B8'
C_PRIMARY = '#2563EB'
C_PRIMARY_HOVER = '#1D4ED8'
C_PRIMARY_SOFT = '#EFF6FF'
C_SUCCESS_FG = '#047857'
C_SUCCESS_BG = '#ECFDF5'
C_SUCCESS_BD = '#A7F3D0'
C_WARN_FG = '#B45309'
C_WARN_BG = '#FFFBEB'
C_ERROR_FG = '#DC2626'
C_ERROR_BG = '#FEF2F2'
C_IDLE_BG = '#F1F5F9'

F_TITLE = ('Segoe UI', 18, 'bold')
F_SUB = ('Segoe UI', 9)
F_CARD_TITLE = ('Segoe UI', 12, 'bold')
F_LABEL = ('Segoe UI', 8, 'bold')
F_BODY = ('Segoe UI', 10)
F_BTN = ('Segoe UI', 9, 'bold')
F_MONO = ('Consolas', 10)


def is_windows_session_locked() -> bool:
    if os.name != 'nt':
        return False
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0001)
        if not hdesk:
            return True
        user32.CloseDesktop(hdesk)
        return False
    except Exception:
        return False


def is_clipboard_history_enabled() -> bool:
    if os.name != 'nt':
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Clipboard') as k:
            val, _ = winreg.QueryValueEx(k, 'EnableClipboardHistory')
            return bool(val)
    except OSError:
        return False


class App:
    def __init__(self, root, session_locked_fn=None):
        self.root = root
        self.vault: Vault | None = None
        self.selected: Entry | None = None
        self.dialog = None
        self.last = time.monotonic()
        self._last_tick = self.last
        self._session_locked_fn = session_locked_fn or is_windows_session_locked
        self.clip: str | None = None
        self.clip_generation = 0
        self.clip_timer = None
        self.reveal_timer = None
        self._tick_timer = None
        self.results: dict[str, Entry] = {}

        root.title('Personal Vault — Synthetic MVP')
        root.geometry('1020x680')
        root.minsize(780, 520)
        root.configure(bg=C_APP_BG)
        self._configure_styles()

        # Top Chrome Header
        header = tk.Frame(root, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1)
        header.pack(fill='x')
        h_inner = tk.Frame(header, bg=C_SURFACE, padx=20, pady=12)
        h_inner.pack(fill='x')

        h_left = tk.Frame(h_inner, bg=C_SURFACE)
        h_left.pack(side='left', fill='x', expand=True)
        tk.Label(h_left, text='Personal Vault', font=F_TITLE, bg=C_SURFACE, fg=C_TEXT_MAIN).pack(anchor='w')
        tk.Label(
            h_left,
            text='LOCAL  •  OFFLINE  •  SYNTHETIC DATA ONLY — chưa dùng mật khẩu thật',
            font=F_SUB,
            bg=C_SURFACE,
            fg=C_TEXT_MUTED,
        ).pack(anchor='w', pady=(2, 0))

        h_right = tk.Frame(h_inner, bg=C_SURFACE)
        h_right.pack(side='right', anchor='center')
        ttk.Button(h_right, text='Mở vault / backup', style='Primary.TButton', command=self.open).pack(side='left', padx=(0, 6))
        ttk.Button(h_right, text='Tạo vault', style='Secondary.TButton', command=self.create).pack(side='left', padx=(0, 6))
        ttk.Button(h_right, text='Demo 500 mẫu', style='Secondary.TButton', command=lambda: self.create(True)).pack(side='left', padx=(0, 6))
        self.lockbtn = ttk.Button(h_right, text='Khóa', style='Secondary.TButton', command=self.lock)
        self.lockbtn.pack(side='left')

        # Main Content Container
        body = tk.Frame(root, bg=C_APP_BG, padx=20, pady=14)
        body.pack(fill='both', expand=True)

        # Status Badge Bar
        self.status = tk.StringVar(value='Đã khóa. Tạo hoặc mở vault thử nghiệm.')
        self.status_bar = tk.Frame(body, bg=C_IDLE_BG, highlightbackground=C_BORDER, highlightthickness=1, padx=12, pady=7)
        self.status_bar.pack(fill='x', pady=(0, 12))
        self.status_lbl = tk.Label(
            self.status_bar,
            textvariable=self.status,
            font=('Segoe UI', 9, 'bold'),
            bg=C_IDLE_BG,
            fg=C_TEXT_MUTED,
            anchor='w',
            wraplength=920,
        )
        self.status_lbl.pack(fill='x')

        # Search & Toolbar Card
        toolbar = tk.Frame(body, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1, padx=14, pady=10)
        toolbar.pack(fill='x', pady=(0, 12))

        qbar = tk.Frame(toolbar, bg=C_SURFACE)
        qbar.pack(fill='x')
        self.query = tk.StringVar()
        self.qentry = ttk.Entry(qbar, textvariable=self.query, font=F_BODY)
        self.qentry.pack(side='left', fill='x', expand=True, ipady=4)
        self.qentry.bind('<Return>', lambda _: self.run_search())
        self.searchbtn = ttk.Button(qbar, text='Tìm tài khoản', style='Primary.TButton', command=self.run_search)
        self.searchbtn.pack(side='left', padx=(8, 0))

        self.actions = tk.Frame(toolbar, bg=C_SURFACE)
        self.actions.pack(fill='x', pady=(10, 0))
        self.buttons = []
        action_specs = [
            ('Tất cả', 'Secondary.TButton', self.refresh),
            ('Thêm', 'Secondary.TButton', self.add),
            ('Sửa', 'Secondary.TButton', self.edit),
            ('Xóa', 'Danger.TButton', self.delete),
            ('Import mẫu', 'Secondary.TButton', self.import_file),
            ('Backup', 'Secondary.TButton', self.backup),
        ]
        for label, style_name, cmd in action_specs:
            b = ttk.Button(self.actions, text=label, style=style_name, command=cmd)
            b.pack(side='left', padx=(0, 6))
            self.buttons.append(b)

        # Workspace: Split Left Table Card + Right Inspector Card
        workspace = tk.Frame(body, bg=C_APP_BG)
        workspace.pack(fill='both', expand=True)
        workspace.grid_columnconfigure(0, weight=3, uniform='ws')
        workspace.grid_columnconfigure(1, weight=2, uniform='ws')
        workspace.grid_rowconfigure(0, weight=1)

        left_card = tk.Frame(workspace, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1)
        left_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        self.tree = ttk.Treeview(left_card, columns=('name',), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='TÀI KHOẢN', anchor='w')
        self.tree.heading('name', text='TÊN ĐĂNG NHẬP', anchor='w')
        self.tree.column('#0', width=260, minwidth=150)
        self.tree.column('name', width=200, minwidth=120)
        self.tree.tag_configure('odd', background=C_SUBTLE)
        self.tree.tag_configure('even', background=C_SURFACE)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(left_card, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)

        right_card = tk.Frame(workspace, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1, padx=18, pady=16)
        right_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

        self.account = tk.StringVar()
        self.name = tk.StringVar()
        self.password = tk.StringVar(value='••••••••')
        self.meta = tk.StringVar()

        self.detail_title = tk.Label(
            right_card,
            textvariable=self.account,
            font=('Segoe UI', 14, 'bold'),
            bg=C_SURFACE,
            fg=C_TEXT_MAIN,
            wraplength=340,
            justify='left',
            anchor='w',
        )
        self.detail_title.pack(fill='x')
        tk.Frame(right_card, bg=C_DIVIDER, height=1).pack(fill='x', pady=(10, 14))

        tk.Label(right_card, text='TÊN ĐĂNG NHẬP', font=F_LABEL, bg=C_SURFACE, fg=C_TEXT_MUTED).pack(anchor='w')
        name_box = tk.Frame(right_card, bg=C_SUBTLE, highlightbackground=C_BORDER, highlightthickness=1, padx=10, pady=7)
        name_box.pack(fill='x', pady=(4, 6))
        tk.Label(name_box, textvariable=self.name, font=F_MONO, bg=C_SUBTLE, fg=C_TEXT_MAIN, anchor='w', wraplength=310).pack(fill='x')
        ttk.Button(right_card, text='Copy username', style='Secondary.TButton', command=lambda: self.copy('name')).pack(anchor='w', pady=(0, 14))

        tk.Label(right_card, text='MẬT KHẨU', font=F_LABEL, bg=C_SURFACE, fg=C_TEXT_MUTED).pack(anchor='w')
        pw_box = tk.Frame(right_card, bg=C_SUBTLE, highlightbackground=C_BORDER, highlightthickness=1, padx=10, pady=7)
        pw_box.pack(fill='x', pady=(4, 6))
        tk.Label(pw_box, textvariable=self.password, font=F_MONO, bg=C_SUBTLE, fg=C_TEXT_MAIN, anchor='w', wraplength=310).pack(fill='x')
        pbar = tk.Frame(right_card, bg=C_SURFACE)
        pbar.pack(anchor='w', pady=(0, 14))
        self.showbtn = ttk.Button(pbar, text='Hiện 15 giây', style='Secondary.TButton', command=self.reveal)
        self.showbtn.pack(side='left')
        ttk.Button(pbar, text='Copy password', style='Secondary.TButton', command=lambda: self.copy('password')).pack(side='left', padx=(6, 0))

        tk.Label(right_card, text='ALIAS / MÔ TẢ / TAGS / URL', font=F_LABEL, bg=C_SURFACE, fg=C_TEXT_MUTED).pack(anchor='w')
        meta_box = tk.Frame(right_card, bg=C_SUBTLE, highlightbackground=C_BORDER, highlightthickness=1, padx=10, pady=8)
        meta_box.pack(fill='both', expand=True, pady=(4, 0))
        tk.Label(
            meta_box,
            textvariable=self.meta,
            font=F_BODY,
            bg=C_SUBTLE,
            fg=C_TEXT_BODY,
            anchor='nw',
            justify='left',
            wraplength=310,
        ).pack(fill='both', expand=True)

        root.bind_all('<KeyPress>', self.activity, add='+')
        root.bind_all('<ButtonPress>', self.activity, add='+')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.enable(False)
        self._tick_timer = root.after(1000, self.tick)

    def _configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=F_BODY, background=C_APP_BG, foreground=C_TEXT_BODY)
        style.configure('TFrame', background=C_SURFACE)
        style.configure('TLabel', background=C_SURFACE, foreground=C_TEXT_BODY)
        style.configure('TEntry', fieldbackground=C_SURFACE, foreground=C_TEXT_MAIN, bordercolor=C_BORDER, lightcolor=C_PRIMARY, darkcolor=C_BORDER, padding=6)

        style.configure('Primary.TButton', font=F_BTN, background=C_PRIMARY, foreground='#FFFFFF', borderwidth=0, padding=(12, 7))
        style.map('Primary.TButton', background=[('active', C_PRIMARY_HOVER), ('disabled', '#93C5FD')], foreground=[('disabled', '#FFFFFF')])

        style.configure('Secondary.TButton', font=F_BTN, background=C_SURFACE, foreground=C_TEXT_BODY, bordercolor=C_BORDER, lightcolor=C_BORDER, darkcolor=C_BORDER, borderwidth=1, padding=(11, 6))
        style.map('Secondary.TButton', background=[('active', C_SUBTLE), ('disabled', C_SUBTLE)], foreground=[('disabled', C_TEXT_HINT)])

        style.configure('Danger.TButton', font=F_BTN, background=C_SURFACE, foreground=C_ERROR_FG, bordercolor=C_BORDER, lightcolor=C_BORDER, darkcolor=C_BORDER, borderwidth=1, padding=(11, 6))
        style.map('Danger.TButton', background=[('active', C_ERROR_BG), ('disabled', C_SUBTLE)], foreground=[('disabled', C_TEXT_HINT)])

        style.configure('Treeview', background=C_SURFACE, fieldbackground=C_SURFACE, foreground=C_TEXT_MAIN, rowheight=32, borderwidth=0, font=F_BODY)
        style.map('Treeview', background=[('selected', C_PRIMARY_SOFT)], foreground=[('selected', C_TEXT_MAIN)])
        style.configure('Treeview.Heading', font=F_LABEL, background=C_SUBTLE, foreground=C_TEXT_MUTED, relief='flat', padding=(8, 8))
        style.map('Treeview.Heading', background=[('active', C_IDLE_BG)])

    def _set_status(self, text: str, tone: str = 'idle'):
        palette = {
            'idle': (C_IDLE_BG, C_TEXT_MUTED, C_BORDER),
            'success': (C_SUCCESS_BG, C_SUCCESS_FG, C_SUCCESS_BD),
            'warn': (C_WARN_BG, C_WARN_FG, '#FDE68A'),
            'info': (C_PRIMARY_SOFT, C_PRIMARY_HOVER, '#BFDBFE'),
        }
        bg, fg, bd = palette.get(tone, palette['idle'])
        self.status_bar.configure(bg=bg, highlightbackground=bd)
        self.status_lbl.configure(bg=bg, fg=fg)
        self.status.set(text)

    def activity(self, event=None):
        self.last = time.monotonic()

    def tick(self):
        now = time.monotonic()
        if self.vault and (
            now - self.last >= IDLE_TIMEOUT_S
            or now - self._last_tick >= SUSPEND_GAP_S
            or self._session_locked_fn()
        ):
            self.lock(reason='Đã tự động khóa (hết thời gian chờ hoặc khóa phiên Windows).')
        self._last_tick = now
        self._tick_timer = self.root.after(1000, self.tick)

    def _safe_initial_dir(self) -> str:
        d = default_vault_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
            return str(d)
        except OSError:
            return str(Path.home())

    def enable(self, on: bool):
        state = 'normal' if on else 'disabled'
        for w in [self.qentry, self.searchbtn, *self.buttons]:
            w.configure(state=state)
        self.lockbtn.configure(state=state)

    def fail(self, e):
        messagebox.showerror(
            'Personal Vault',
            str(e) if isinstance(e, VaultError) else 'Thao tác thất bại. Không ghi log dữ liệu.',
            parent=self.root,
        )

    def choose_password(self, confirm=False):
        p = simpledialog.askstring(
            'Master password',
            'Mật khẩu thử nghiệm (≥12 ký tự):' if confirm else 'Master password:',
            show='•',
            parent=self.root,
        )
        if p is None:
            return None
        if confirm and simpledialog.askstring('Xác nhận', 'Nhập lại mật khẩu thử nghiệm:', show='•', parent=self.root) != p:
            messagebox.showwarning('Không khớp', 'Mật khẩu xác nhận không khớp.', parent=self.root)
            return None
        return p

    def create(self, demo=False):
        if self.vault:
            self.lock()
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=self._safe_initial_dir(),
            defaultextension='.pvault',
            filetypes=[('Vault', '*.pvault')],
            initialfile='synthetic-demo.pvault',
        )
        if not path:
            return
        if is_inside_app_dir(path):
            self.fail(VaultError('Không lưu vault bên trong thư mục ứng dụng hoặc repo.'))
            return
        p = self.choose_password(True)
        if p is None:
            return
        try:
            v = Vault.create(path, p)
            if demo:
                v.replace(synthetic_entries())
            self.attach(v)
        except Exception as e:
            self.fail(e)

    def open(self):
        if self.vault:
            self.lock()
        path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=self._safe_initial_dir(),
            filetypes=[('Vault', '*.pvault')],
        )
        if not path:
            return
        if is_inside_app_dir(path):
            messagebox.showwarning(
                'Cảnh báo vị trí file',
                'File vault đang nằm trong thư mục ứng dụng/repo. Hãy di chuyển ra thư mục dữ liệu riêng.',
                parent=self.root,
            )
        p = self.choose_password()
        if p is None:
            return
        try:
            self.attach(Vault.open(path, p))
        except Exception as e:
            self.fail(e)

    def attach(self, v: Vault):
        self.vault = v
        self.activity()
        self.enable(True)
        self.refresh()
        self.qentry.focus_set()

    def clear_details(self):
        if self.reveal_timer is not None:
            self.root.after_cancel(self.reveal_timer)
            self.reveal_timer = None
        self.selected = None
        self.account.set('Chưa chọn tài khoản')
        self.name.set('—')
        self.password.set('••••••••')
        self.meta.set('Chọn một dòng ở danh sách bên trái để xem chi tiết.')

    def show_items(self, items):
        self.clear_details()
        self.tree.delete(*self.tree.get_children())
        self.results = {e.id: e for e in items}
        for idx, e in enumerate(items):
            tag = 'odd' if idx % 2 else 'even'
            self.tree.insert('', 'end', iid=e.id, text=f'  {e.account}', values=(e.name,), tags=(tag,))

    def refresh(self):
        if not self.vault:
            return
        self.query.set('')
        items = self.vault.entries
        self.show_items(items)
        self._set_status(f'Đã mở khóa — {len(items)} tài khoản. Chọn một dòng để xem.', 'success')

    def run_search(self):
        if not self.vault:
            return
        result = search(self.vault.entries, self.query.get())
        self.show_items(result.items)
        msg = {
            'none': ('Không tìm thấy.', 'warn'),
            'ambiguous': ('Nhiều kết quả — hãy chọn chính xác.', 'info'),
            'suggestion': ('Gợi ý gần đúng — kiểm tra và chọn thủ công.', 'warn'),
            'match': ('Tìm thấy — chọn để xem.', 'success'),
            'exact': ('Khớp chính xác — chọn để xem.', 'success'),
        }
        text, tone = msg[result.kind]
        self._set_status(text + f' ({len(result.items)})', tone)

    def select(self, event=None):
        if not self.vault:
            return
        sel = self.tree.selection()
        self.clear_details()
        if not sel:
            return
        e = self.results.get(sel[0])
        self.selected = e
        if e:
            self.account.set(e.account)
            self.name.set(e.name)
            lines = []
            if e.aliases:
                lines.append('Alias: ' + '; '.join(e.aliases))
            if e.description:
                lines.append('Mô tả: ' + e.description)
            if e.tags:
                lines.append('Tags: ' + '; '.join(e.tags))
            if e.url:
                lines.append('URL: ' + e.url)
            self.meta.set('\n'.join(lines) if lines else 'Không có thông tin bổ sung.')

    def reveal(self):
        if not self.vault or not self.selected:
            return
        self.password.set(self.selected.password)
        if self.reveal_timer is not None:
            self.root.after_cancel(self.reveal_timer)
        self.reveal_timer = self.root.after(REVEAL_TIMEOUT_MS, self.hide)

    def hide(self):
        self.password.set('••••••••')
        self.reveal_timer = None

    def copy(self, field: str):
        if not self.vault or not self.selected:
            return
        if field == 'password':
            if is_clipboard_history_enabled():
                warn = (
                    'Cảnh báo: Windows Clipboard History đang BẬT — mật khẩu có thể bị lưu lại trong '
                    'lịch sử clipboard (Win+V) hoặc đồng bộ! Tiếp tục copy mật khẩu?'
                )
            else:
                warn = 'Clipboard có thể lưu lịch sử hoặc đồng bộ. Tiếp tục copy mật khẩu?'
            if not messagebox.askyesno('Clipboard', warn, parent=self.root):
                return
        if not self.vault or not self.selected:
            return
        val = getattr(self.selected, field)
        self.clear_clip()
        self.root.clipboard_clear()
        self.root.clipboard_append(val)
        self.clip = val
        self.clip_generation += 1
        generation = self.clip_generation
        self.clip_timer = self.root.after(CLIP_TIMEOUT_MS, lambda: self.clear_clip(generation))
        self._set_status('Đã copy; sẽ cố xóa clipboard sau 20 giây nếu chưa thay đổi.', 'info')

    def clear_clip(self, expected=None):
        if self.clip is None or (expected is not None and expected != self.clip_generation):
            return
        if self.clip_timer is not None:
            try:
                self.root.after_cancel(self.clip_timer)
            except tk.TclError:
                pass
            self.clip_timer = None
        try:
            if self.root.clipboard_get() == self.clip:
                self.root.clipboard_clear()
        except tk.TclError:
            pass
        self.clip = None
        self.clip_generation += 1

    def lock(self, reason='Đã khóa. Mở vault để tra cứu.'):
        if self.dialog:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
            self.dialog = None
        self.clear_clip()
        self.clear_details()
        self.query.set('')
        self.tree.delete(*self.tree.get_children())
        self.results = {}
        if self.vault:
            self.vault.lock()
            self.vault = None
        self.enable(False)
        self._set_status(reason, 'idle')
        self.root.focus_set()

    def close(self):
        if self._tick_timer is not None:
            try:
                self.root.after_cancel(self._tick_timer)
            except tk.TclError:
                pass
            self._tick_timer = None
        self.lock()
        self.root.destroy()

    def add(self):
        self.editor(None)

    def edit(self):
        if self.selected:
            self.editor(self.selected)

    def editor(self, e: Entry | None):
        if not self.vault or self.dialog:
            return
        d = tk.Toplevel(self.root)
        self.dialog = d
        d.title('Sửa tài khoản' if e else 'Thêm tài khoản')
        d.configure(bg=C_APP_BG, padx=16, pady=16)
        d.transient(self.root)
        d.grab_set()
        vals = {}

        def done():
            self.dialog = None
            d.destroy()

        d.protocol('WM_DELETE_WINDOW', done)
        card = tk.Frame(d, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1, padx=16, pady=16)
        card.pack(fill='both', expand=True)

        fields = [
            ('account', 'Tài khoản *'),
            ('name', 'Username *'),
            ('password', 'Password *'),
            ('aliases', 'Alias (;)'),
            ('description', 'Mô tả'),
            ('tags', 'Tags (;)'),
            ('url', 'URL / Host'),
        ]
        for i, (k, label) in enumerate(fields):
            tk.Label(card, text=label.upper(), font=F_LABEL, bg=C_SURFACE, fg=C_TEXT_MUTED).grid(row=i, column=0, padx=(0, 12), pady=6, sticky='w')
            v = getattr(e, k, '') if e else ''
            v = '; '.join(v) if isinstance(v, tuple) else v
            vals[k] = tk.StringVar(value=v)
            ttk.Entry(card, textvariable=vals[k], width=46, show='•' if k == 'password' else '').grid(row=i, column=1, pady=6)

        def save():
            if not self.vault:
                return
            data = {k: v.get() for k, v in vals.items()}
            data['aliases'] = tuple(x.strip() for x in data['aliases'].split(';') if x.strip())
            data['tags'] = tuple(x.strip() for x in data['tags'].split(';') if x.strip())
            new = replace(e, **data) if e else Entry.new(**data)
            try:
                items = self.vault.entries
                if any(x.id != new.id and norm(x.account) == norm(new.account) and x.name == new.name for x in items):
                    raise VaultError('Duplicate account + username.')
                self.vault.replace([new if x.id == new.id else x for x in items] if e else [*items, new])
                done()
                self.refresh()
            except Exception as ex:
                self.fail(ex)

        btns = tk.Frame(card, bg=C_SURFACE)
        btns.grid(row=7, column=1, pady=(14, 0), sticky='e')
        ttk.Button(btns, text='Hủy', style='Secondary.TButton', command=done).pack(side='left', padx=(0, 6))
        ttk.Button(btns, text='Lưu vào vault', style='Primary.TButton', command=save).pack(side='left')

    def delete(self):
        if not self.vault or not self.selected:
            return
        eid = self.selected.id
        if messagebox.askyesno('Xóa', 'Xóa mục đã chọn khỏi vault?', parent=self.root) and self.vault:
            try:
                self.vault.replace([x for x in self.vault.entries if x.id != eid])
                self.refresh()
            except Exception as e:
                self.fail(e)

    def _show_import_preview(self, preview: ImportPreview) -> bool:
        d = tk.Toplevel(self.root)
        self.dialog = d
        d.title('Preview Import (Synthetic Only)')
        d.configure(bg=C_APP_BG, padx=16, pady=16)
        d.transient(self.root)
        d.grab_set()
        d.geometry('680x440')
        accepted = {'ok': False}

        def close_dlg(ok=False):
            accepted['ok'] = ok
            self.dialog = None
            d.destroy()

        d.protocol('WM_DELETE_WINDOW', lambda: close_dlg(False))
        summary = (
            f'Tổng đọc được: {len(preview.records)}  •  '
            f'Mới: {len(preview.new_entries)}  •  '
            f'Trùng với vault (sẽ bỏ qua): {len(preview.duplicate_in_vault)}'
        )
        tk.Label(d, text=summary, font=F_BTN, bg=C_APP_BG, fg=C_TEXT_MAIN).pack(anchor='w', pady=(0, 10))

        table_card = tk.Frame(d, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1)
        table_card.pack(fill='both', expand=True)
        tree = ttk.Treeview(table_card, columns=('name', 'status'), show='tree headings', selectmode='none')
        tree.heading('#0', text='TÀI KHOẢN', anchor='w')
        tree.heading('name', text='USERNAME', anchor='w')
        tree.heading('status', text='TRẠNG THÁI', anchor='w')
        tree.column('#0', width=240)
        tree.column('name', width=220)
        tree.column('status', width=160)
        tree.pack(fill='both', expand=True)

        dup_ids = {e.id for e in preview.duplicate_in_vault}
        for e in preview.records:
            st = 'Trùng (bỏ qua)' if e.id in dup_ids else 'Mới'
            tree.insert('', 'end', text=f'  {e.account}', values=(e.name, st))

        btns = tk.Frame(d, bg=C_APP_BG, pady=12)
        btns.pack(fill='x')
        if preview.new_entries:
            ttk.Button(
                btns,
                text=f'Import {len(preview.new_entries)} mục mới',
                style='Primary.TButton',
                command=lambda: close_dlg(True),
            ).pack(side='right', padx=(6, 0))
        ttk.Button(btns, text='Hủy', style='Secondary.TButton', command=lambda: close_dlg(False)).pack(side='right')
        self.root.wait_window(d)
        return accepted['ok']

    def import_file(self):
        if not self.vault:
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=str(Path.home()),
            filetypes=[('Synthetic data', '*.txt *.csv *.json *.bat *.ps1')],
        )
        if not path or not self.vault:
            return
        try:
            with open(path, 'rb') as f:
                raw = f.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise VaultError('Import too large.')
            old = self.vault.entries
            preview = inspect_import(raw.decode('utf-8-sig'), Path(path).suffix, existing_entries=old)
            if not preview.new_entries:
                raise VaultError('Tất cả bản ghi đều trùng với vault hiện tại; không có gì để import.')
            if self._show_import_preview(preview) and self.vault:
                self.vault.replace([*old, *preview.new_entries])
                self.refresh()
        except Exception as e:
            self.fail(e)

    def backup(self):
        if not self.vault:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=self._safe_initial_dir(),
            defaultextension='.pvault',
            initialfile='synthetic-backup.pvault',
        )
        if not path or not self.vault:
            return
        if is_inside_app_dir(path):
            self.fail(VaultError('Không lưu backup bên trong thư mục ứng dụng hoặc repo.'))
            return
        try:
            self.vault.backup(path)
            self._set_status('Đã tạo backup mã hóa. Mở backup như một vault riêng.', 'success')
        except Exception as e:
            self.fail(e)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
