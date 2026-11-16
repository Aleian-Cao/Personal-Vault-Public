"""Personal Vault - Headless JSON-RPC Sidecar over standard input/output (stdio).
Zero network, zero HTTP listeners, zero persistent secrets in frontend.
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

# Ensure personal_vault module is accessible
MVP_DIR = Path(__file__).resolve().parent.parent / 'PersonalVault_MVP'
if str(MVP_DIR) not in sys.path:
    sys.path.insert(0, str(MVP_DIR))

from personal_vault.core import (
    Vault,
    VaultError,
    Entry,
    search,
    inspect_import,
    default_vault_dir,
    is_inside_app_dir,
    synthetic_entries,
    norm,
)

from chat_pipeline import ChatPipeline  # noqa: E402  (sibling module; also bundled by PyInstaller)

# Release build: Qwen can never be enabled. The experimental build's entry point
# (sidecar_experimental.py) flips this flag; an environment variable alone is not enough.
QWEN_ALLOWED = False
# QA-only hooks (experimental build entry flips this): scaled idle time, simulated session lock / suspend via files, activity log.
# Never enabled in the release sidecar.
TEST_HOOKS = False
SUSPEND_GAP_S = 15  # same as the Tkinter fallback: a wall-clock jump this big between ticks = suspend/resume

STATE_FILE = 'last_vault.json'  # pointer only (vault path); never a secret
IDLE_LOCK_SECONDS = 300
# Synthetic demo vault only; personal vaults never use this password.
DEMO_PASSWORD = 'Synthetic-Master-Only-123!'

# IPC allowlist: anything else (incl. private helpers) is rejected.
ALLOWED_METHODS = frozenset({
    'startup_state', 'is_unlocked', 'touch', 'unlock', 'lock', 'create', 'open_demo', 'get_entries',
    'search', 'chat_search', 'reveal', 'save_entry', 'delete_entry', 'inspect_import', 'confirm_import', 'backup',
    'default_dir',
})
TEST_ONLY_METHODS = frozenset({'debug_activity'})


def session_locked() -> bool:
    """True while the Windows session is locked (secure desktop active). Two independent signals, either one locks."""
    if TEST_HOOKS and os.environ.get('PVAULT_TEST_LOCK_FILE') and os.path.exists(os.environ['PVAULT_TEST_LOCK_FILE']):
        return True  # QA simulation of the locked secure desktop
    if os.name != 'nt':
        return False
    try:
        import ctypes
        import struct
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0001)
        if not hdesk:
            return True  # cannot open the input desktop = secure desktop is in front
        user32.CloseDesktop(hdesk)
        wts, buf, n = ctypes.windll.wtsapi32, ctypes.c_void_p(), ctypes.c_ulong()
        if wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, ctypes.byref(buf), ctypes.byref(n)):  # WTSSessionInfoEx
            try:
                if n.value >= 20:
                    return struct.unpack_from('<i', ctypes.string_at(buf, n.value), 16)[0] == 0  # WTS_SESSIONSTATE_LOCK
            finally:
                wts.WTSFreeMemory(buf)
        return False
    except Exception:
        return False


def _make_runner():
    """Qwen only in the experimental build (QWEN_ALLOWED) AND PVAULT_QWEN=1. Off in release: the eval showed
    no clear gain and the frozen sidecar's only usable backend (llama-cli) opens loopback sockets."""
    if not QWEN_ALLOWED or os.environ.get('PVAULT_QWEN') != '1':
        return None
    from qwen_runner import QwenRunner
    return QwenRunner(timeout_s=10)


def _meta(e: Entry) -> dict:
    """Entry metadata for the UI. Never includes the password."""
    return {
        "id": e.id,
        "account": e.account,
        "name": e.name,
        "aliases": list(e.aliases),
        "description": e.description,
        "tags": list(e.tags),
        "url": e.url,
    }


class SidecarController:
    def __init__(self, state_dir: Path | None = None, idle_seconds: float = IDLE_LOCK_SECONDS, clock=time.monotonic):
        self.vault: Vault | None = None
        self.active_path: Path | None = None
        self.demo = False
        self.generation = 0  # bumps on every lock/unlock so late responses can be recognised as stale
        self._pending_import: list[Entry] | None = None
        self._chat = ChatPipeline(runner=_make_runner())  # RAM-only session context
        self._idle = idle_seconds
        self._clock = clock
        self._last = clock()
        self._wall_prev = time.time()
        self._t0 = clock()
        self.activity: list = []  # (seconds since start, kind): which call last refreshed the idle window (for attribution)
        self.state_dir = Path(state_dir) if state_dir else default_vault_dir()

    # -- session ------------------------------------------------------
    def _expire(self) -> None:
        if self.vault is not None and self._clock() - self._last > self._idle:
            self.lock()

    def _note(self, kind: str) -> None:
        self.activity.append((round(self._clock() - self._t0, 1), kind))
        del self.activity[:-200]

    def _require_unlocked(self) -> Vault:
        self._expire()
        if self.vault is None:
            raise VaultError("Vault is locked.")
        self._last = self._clock()
        self._note('data-call')
        return self.vault

    def debug_activity(self) -> dict:
        """QA only (TEST_HOOKS): the idle-window refreshes seen so far, newest last."""
        return {"events": list(self.activity), "idle_seconds": self._idle, "now": round(self._clock() - self._t0, 1)}

    def poll_session(self, locked: bool, wall_now: float) -> str | None:
        """~1/s from the watcher thread (inputs injectable for tests). Expires idle, and locks on Windows session
        lock or a suspend/resume wall-clock jump, independent of the UI. Returns the reason if it locked."""
        gap, self._wall_prev = wall_now - self._wall_prev, wall_now
        was_open = self.vault is not None
        self._expire()
        if self.vault is None:
            return 'idle' if was_open else None
        reason = 'session' if locked else 'suspend' if gap > SUSPEND_GAP_S else None
        if reason:
            self.lock()
        return reason

    def touch(self) -> dict:
        self._expire()
        if self.vault is not None:
            self._last = self._clock()
            self._note('touch')
        return {"unlocked": self.vault is not None}

    def _open(self, v: Vault, target: Path, demo: bool) -> dict:
        self.vault, self.active_path, self.demo = v, target, demo
        self._pending_import = None
        self._chat.clear()
        self._last = self._clock()
        self._note('open')
        self.generation += 1
        return {"success": True, "path": str(target), "count": len(v.entries), "generation": self.generation}

    # -- remembered vault pointer (best effort, no secrets) -------------
    def _remembered(self) -> Path | None:
        try:
            p = json.loads((self.state_dir / STATE_FILE).read_text(encoding='utf-8'))['path']
            return Path(p) if isinstance(p, str) and p else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _remember(self, target: Path) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / STATE_FILE).write_text(json.dumps({"path": str(target)}), encoding='utf-8')
        except OSError:
            pass  # pointer is a convenience; the vault itself is already safe on disk

    def startup_state(self) -> dict:
        """fresh | locked | missing | unlocked. Read-only: never creates files."""
        self._expire()
        if self.vault is not None:
            return {"state": "unlocked", "path": str(self.active_path), "demo": self.demo, "generation": self.generation,
                    "qwen": self._chat.runner is not None}
        p = self._remembered()
        if p is None:
            return {"state": "fresh", "path": None, "demo": False, "generation": self.generation}
        return {"state": "locked" if p.is_file() else "missing", "path": str(p), "demo": False,
                "generation": self.generation}

    def is_unlocked(self) -> dict:
        self._expire()
        return {
            "unlocked": self.vault is not None,
            "path": str(self.active_path) if self.active_path else None,
            "count": len(self.vault.entries) if self.vault else 0
        }

    def unlock(self, path: str, password: str) -> dict:
        target = Path(path)
        if not target.is_file():  # first: opening must never create dirs/lock files for a missing vault
            raise VaultError("Vault file not found.")
        if self.vault:
            self.lock()
        res = self._open(Vault.open(target, password), target, False)
        self._remember(target)
        return res

    def lock(self) -> dict:
        if self.vault:
            self.vault.lock()
            self.vault = None
        self.active_path = None
        self.demo = False
        self._pending_import = None
        self._chat.clear()
        self.generation += 1
        return {"success": True}

    def create(self, path: str, password: str, demo: bool = False) -> dict:
        if self.vault:
            self.lock()
        target = Path(path)
        if is_inside_app_dir(target):
            raise VaultError("Cannot create vault inside application or repository directory.")
        v = Vault.create(target, password)
        if demo:
            v.replace(synthetic_entries())
        res = self._open(v, target, demo)
        if not demo:
            self._remember(target)
        return res

    def open_demo(self) -> dict:
        """Fresh synthetic vault in its own folder; never remembered, never the personal vault."""
        if self.vault:
            self.lock()
        d = self.state_dir / 'demo'
        for old in d.glob('synthetic-demo-*'):  # stale demo files only (own glob, own folder)
            try:
                old.unlink()
            except OSError:
                pass
        return self.create(str(d / f'synthetic-demo-{uuid.uuid4().hex[:8]}.pvault'), DEMO_PASSWORD, demo=True)

    # -- data ---------------------------------------------------------
    def get_entries(self) -> list[dict]:
        v = self._require_unlocked()
        # Strictly return sanitized metadata; NEVER return plaintext passwords in list
        return [_meta(e) for e in v.entries]

    def search(self, query: str) -> dict:
        v = self._require_unlocked()
        res = search(v.entries, query)
        return {"kind": res.kind, "session_generation": self.generation, "items": [_meta(e) for e in res.items]}

    def chat_search(self, query: str) -> dict:
        """Chatbot search: metadata only (no passwords), session context kept in RAM, cleared on lock."""
        v = self._require_unlocked()
        res = self._chat.answer(query, v.entries)
        res["session_generation"] = self.generation
        return res

    def reveal(self, entry_id: str) -> dict:
        v = self._require_unlocked()
        for e in v.entries:
            if e.id == entry_id:
                return {"id": e.id, "password": e.password}
        raise VaultError("Entry not found.")

    def save_entry(self, entry_data: dict) -> dict:
        v = self._require_unlocked()
        eid = entry_data.get("id")
        account = entry_data["account"].strip()
        name = entry_data["name"].strip()
        password = entry_data.get("password")
        aliases = tuple(x.strip() for x in entry_data.get("aliases", []) if x.strip())
        description = entry_data.get("description", "").strip()
        tags = tuple(x.strip() for x in entry_data.get("tags", []) if x.strip())
        url = entry_data.get("url", "").strip()

        cur = v.entries
        if eid:
            found = False
            updated = []
            for e in cur:
                if e.id == eid:
                    pw = password if password else e.password  # blank/missing = keep the stored secret
                    new_e = Entry(eid, account, name, pw, aliases, description, tags, url)
                    updated.append(new_e)
                    found = True
                else:
                    if norm(e.account) == norm(account) and e.name == name:
                        raise VaultError("Duplicate account + username.")
                    updated.append(e)
            if not found:
                raise VaultError("Entry not found to update.")
            v.replace(updated)
            return {"success": True, "id": eid}
        else:
            if not password:
                raise VaultError("Password is required for new entry.")
            if any(norm(e.account) == norm(account) and e.name == name for e in cur):
                raise VaultError("Duplicate account + username.")
            new_e = Entry.new(account, name, password, aliases, description, tags, url)
            v.replace([*cur, new_e])
            return {"success": True, "id": new_e.id}

    def delete_entry(self, entry_id: str) -> dict:
        v = self._require_unlocked()
        cur = v.entries
        updated = [e for e in cur if e.id != entry_id]
        if len(updated) == len(cur):
            raise VaultError("Entry not found.")
        v.replace(updated)
        return {"success": True}

    def inspect_import(self, content: str, extension: str) -> dict:
        v = self._require_unlocked()
        self._pending_import = None  # a failed preview must not leave an older one confirmable
        preview = inspect_import(content, extension, existing_entries=v.entries)
        dup_ids = {e.id for e in preview.duplicate_in_vault}
        # Secrets stay here: the UI gets metadata only and confirms by reference to this pending batch.
        self._pending_import = list(preview.new_entries)
        return {
            "total": len(preview.records),
            "newCount": len(preview.new_entries),
            "duplicateCount": len(preview.duplicate_in_vault),
            "invalidCount": 0,  # core parser is all-or-nothing: any invalid record rejects the whole file
            "records": [
                {"entry": _meta(e), "status": "duplicate" if e.id in dup_ids else "new"}
                for e in preview.records
            ],
        }

    def confirm_import(self) -> dict:
        v = self._require_unlocked()
        if self._pending_import is None:
            raise VaultError("No import preview pending.")
        cur = v.entries
        cur_keys = {(norm(e.account), e.name) for e in cur}
        to_add = [e for e in self._pending_import if (norm(e.account), e.name) not in cur_keys]
        skipped = len(self._pending_import) - len(to_add)
        v.replace([*cur, *to_add])
        self._pending_import = None
        return {"success": True, "importedCount": len(to_add), "skippedCount": skipped}

    def backup(self, path: str) -> dict:
        v = self._require_unlocked()
        target = Path(path)
        if is_inside_app_dir(target):
            raise VaultError("Cannot create backup inside application directory.")
        v.backup(target)
        return {"success": True, "path": str(target)}

    def default_dir(self) -> dict:
        d = default_vault_dir()
        d.mkdir(parents=True, exist_ok=True)
        return {"dir": str(d)}


def _watch(controller: SidecarController, mutex: threading.Lock, stop: threading.Event) -> None:
    skew = 0.0
    while not stop.wait(1.0):
        f = os.environ.get('PVAULT_TEST_SUSPEND_FILE') if TEST_HOOKS else None
        if f and os.path.exists(f):  # QA simulation of a suspend/resume wall-clock jump
            try:
                skew += float(open(f).read().strip() or 60)
                os.remove(f)
            except (OSError, ValueError):
                pass
        with mutex:
            controller.poll_session(session_locked(), time.time() + skew)


def main():
    idle = float(os.environ.get('PVAULT_TEST_IDLE_SECONDS', IDLE_LOCK_SECONDS)) if TEST_HOOKS else IDLE_LOCK_SECONDS
    controller = SidecarController(idle_seconds=idle)
    mutex = threading.Lock()  # the stdin loop and the watcher thread never touch the controller at the same time
    threading.Thread(target=_watch, args=(controller, mutex, threading.Event()), daemon=True).start()
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')

    # Emit ready banner
    sys.stdout.write(json.dumps({"event": "ready", "version": "0.1.0-sidecar"}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            allowed = method in ALLOWED_METHODS or (TEST_HOOKS and method in TEST_ONLY_METHODS)
            handler = getattr(controller, method, None) if allowed else None
            if not handler or not isinstance(params, dict):
                resp = {"id": req_id, "error": "Unknown or malformed request."}
            else:
                with mutex:
                    res = handler(**params)
                resp = {"id": req_id, "result": res}
        except VaultError as e:
            resp = {"id": req_id, "error": str(e)}
        except Exception as e:
            resp = {"id": req_id, "error": f"Internal sidecar error: {type(e).__name__}"}

        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == '__main__':
    main()
