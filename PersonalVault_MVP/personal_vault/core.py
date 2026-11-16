"""Synthetic-only prototype. No networking or script execution."""
from __future__ import annotations
import csv, difflib, hashlib, io, json, os, re, sys, tempfile, threading, unicodedata, uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

MAGIC = b'PVLT\x01'
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 10000
ENTRY_KEYS = {'id', 'account', 'name', 'password', 'aliases', 'description', 'tags', 'url'}

_LOCK_GUARD = threading.Lock()
_ACTIVE_PATHS: set[Path] = set()


class VaultError(Exception):
    pass


@dataclass(frozen=True, repr=False)
class Entry:
    id: str
    account: str
    name: str
    password: str
    aliases: tuple[str, ...] = ()
    description: str = ''
    tags: tuple[str, ...] = ()
    url: str = ''

    @classmethod
    def new(cls, account, name, password, aliases=(), description='', tags=(), url=''):
        return cls(str(uuid.uuid4()), account, name, password, tuple(aliases), description, tuple(tags), url)

    def validate(self):
        if not all(isinstance(x, str) for x in (self.id, self.account, self.name, self.password, self.description, self.url)) or not all(
            isinstance(x, str) for x in (*self.aliases, *self.tags)
        ):
            raise VaultError('Invalid field type.')
        if (
            not self.account.strip()
            or not self.name.strip()
            or not self.password
            or not self.id
            or any(len(x) > 16384 for x in (self.account, self.name, self.password, self.description, self.url, *self.aliases, *self.tags))
        ):
            raise VaultError('Missing or oversized field.')
        if len(self.aliases) > 100 or len(self.tags) > 100:
            raise VaultError('Too many aliases or tags.')


def _derive(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        password.encode('utf-8'),
        salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    )


def _atomic(path: Path, raw: bytes, exclusive: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.pvault-', dir=path.parent)
    try:
        try:
            f = os.fdopen(fd, 'wb')
        except Exception:
            os.close(fd)
            raise
        with f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if exclusive:
            # Hard link atomically refuses to replace an existing file.
            os.link(tmp, path)
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


class _VaultLock:
    """Exclusive OS + in-process lockfile to prevent concurrent vault writers."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path.resolve()
        self.lock_path = self.vault_path.with_name(self.vault_path.name + '.lock')
        self._fd: int | None = None
        self._registered = False
        self._acquire()

    def _acquire(self) -> None:
        with _LOCK_GUARD:
            if self.vault_path in _ACTIVE_PATHS:
                raise VaultError('Vault is already open in this session.')
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                if os.name == 'nt':
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                raise VaultError('Vault is locked by another process.') from None
            self._fd = fd
            _ACTIVE_PATHS.add(self.vault_path)
            self._registered = True

    def release(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is not None:
            try:
                if os.name == 'nt':
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass
        if self._registered:
            with _LOCK_GUARD:
                _ACTIVE_PATHS.discard(self.vault_path)
            self._registered = False


class Vault:
    def __init__(self, path: Path, key: bytes, salt: bytes, entries: list[Entry], file_hash: bytes, lock: _VaultLock):
        self.path = Path(path)
        self._key: bytes | None = key
        self._salt = salt
        self._entries = entries
        self._file_hash = file_hash
        self._lock: _VaultLock | None = lock

    def __del__(self):
        lock = getattr(self, '_lock', None)
        if lock is not None:
            lock.release()
            self._lock = None

    @classmethod
    def create(cls, path, password: str) -> Vault:
        if len(password) < 12:
            raise VaultError('Use a master password of at least 12 characters.')
        target = Path(path)
        if target.exists():
            raise VaultError('Vault already exists.')
        vlock = _VaultLock(target)
        try:
            if target.exists():
                raise VaultError('Vault already exists.')
            salt = os.urandom(16)
            key = _derive(password, salt)
            nonce = os.urandom(12)
            header = MAGIC + salt + nonce
            plain = b'[]'
            raw = header + AESGCM(key).encrypt(nonce, plain, header)
            _atomic(target, raw, exclusive=True)
            return cls(target, key, salt, [], hashlib.sha256(raw).digest(), vlock)
        except VaultError:
            vlock.release()
            raise
        except OSError as e:
            vlock.release()
            raise VaultError('Cannot create vault.') from e

    @classmethod
    def open(cls, path, password: str) -> Vault:
        target = Path(path)
        vlock = _VaultLock(target)
        try:
            with target.open('rb') as f:
                raw = f.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or len(raw) < 49 or not raw.startswith(MAGIC):
                raise ValueError()
            salt = raw[5:21]
            nonce = raw[21:33]
            key = _derive(password, salt)
            payload = AESGCM(key).decrypt(nonce, raw[33:], raw[:33])
            data = json.loads(payload)
            if not isinstance(data, list) or len(data) > MAX_ENTRIES:
                raise ValueError()
            items = []
            for d in data:
                if not isinstance(d, dict) or set(d) != ENTRY_KEYS or not isinstance(d.get('aliases'), list) or not isinstance(d.get('tags'), list):
                    raise ValueError()
                e = Entry(**{**d, 'aliases': tuple(d['aliases']), 'tags': tuple(d['tags'])})
                e.validate()
                items.append(e)
            if len({e.id for e in items}) != len(items):
                raise ValueError()
            return cls(target, key, salt, items, hashlib.sha256(raw).digest(), vlock)
        except Exception:
            vlock.release()
            raise VaultError('Cannot unlock: wrong password, invalid vault, or unreadable file.') from None

    def _check(self) -> None:
        if self._key is None:
            raise VaultError('Vault is locked.')

    def _verify_disk_unchanged(self) -> bytes:
        try:
            disk_raw = self.path.read_bytes()
        except OSError:
            raise VaultError('Vault file is unreadable.') from None
        if hashlib.sha256(disk_raw).digest() != self._file_hash:
            raise VaultError('Vault file was modified externally; refusing to overwrite.')
        return disk_raw

    @property
    def entries(self) -> list[Entry]:
        self._check()
        return list(self._entries)

    def _encode(self, entries: list[Entry]) -> bytes:
        self._check()
        nonce = os.urandom(12)
        header = MAGIC + self._salt + nonce
        plain = json.dumps([asdict(e) for e in entries], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(plain) + 49 > MAX_BYTES:
            raise VaultError('Vault size limit exceeded.')
        return header + AESGCM(self._key).encrypt(nonce, plain, header)

    def replace(self, entries: list[Entry]) -> None:
        self._check()
        entries = list(entries)
        if len(entries) > MAX_ENTRIES or len({e.id for e in entries}) != len(entries):
            raise VaultError('Invalid entry count or duplicate IDs.')
        for e in entries:
            e.validate()
        self._verify_disk_unchanged()
        raw = self._encode(entries)
        try:
            _atomic(self.path, raw)
        except OSError:
            raise VaultError('Cannot save vault.') from None
        self._entries = entries
        self._file_hash = hashlib.sha256(raw).digest()

    def backup(self, path) -> None:
        self._check()
        disk_raw = self._verify_disk_unchanged()
        try:
            _atomic(Path(path), disk_raw, exclusive=True)
        except OSError:
            raise VaultError('Cannot create backup (destination must not exist).') from None

    def lock(self) -> None:
        self._entries = []
        self._key = None
        self._salt = b''
        self._file_hash = b''
        if self._lock is not None:
            self._lock.release()
            self._lock = None


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s.casefold().replace('đ', 'd'))
    s = re.sub(r'(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])', ' ', s)
    return ' '.join(re.findall(r'[^\W_]+', ''.join(c for c in s if not unicodedata.combining(c)), re.UNICODE))


@dataclass(frozen=True, repr=False)
class SearchResult:
    kind: str
    items: list[Entry]


def search(entries, query: str) -> SearchResult:
    q = norm(query)
    q = re.sub(r'^(?:(?:cho toi|tim giup toi|tim|xem|lay)\s+)(?:tai khoan\s+)?', '', q)
    entries = list(entries)
    if not q:
        return SearchResult('none', [])
    qt = set(q.split())
    nums = {t for t in qt if t.isdigit()}
    exact = []
    keywords = []
    fuzzy = []
    for e in entries:
        identities = [norm(e.account), *(norm(a) for a in e.aliases)]
        if nums and not any(nums <= set(i.split()) for i in identities):
            continue
        if q in identities:
            exact.append(e)
            continue
        hay = ' '.join([*identities, norm(e.name), norm(e.description), *(norm(t) for t in e.tags), norm(e.url)])
        if qt <= set(hay.split()):
            keywords.append(e)
            continue
        score = max(difflib.SequenceMatcher(None, q, i).ratio() for i in identities)
        if len(q) >= 4 and score >= 0.76:
            fuzzy.append((score, e))
    if exact:
        return SearchResult('exact' if len(exact) == 1 else 'ambiguous', exact)
    if keywords:
        return SearchResult('match' if len(keywords) == 1 else 'ambiguous', keywords)
    if fuzzy:
        return SearchResult('suggestion', [e for _, e in sorted(fuzzy, key=lambda x: -x[0])[:5]])
    return SearchResult('none', [])


FIELDS = {'account', 'name', 'pass', 'aliases', 'description', 'tags', 'url'}


def _record(d: dict) -> Entry:
    if not isinstance(d, dict) or set(d) - FIELDS or not {'account', 'name', 'pass'} <= set(d):
        raise VaultError('Invalid or incomplete record.')

    def parts(key):
        v = d.get(key, '')
        if isinstance(v, str):
            return tuple(x.strip() for x in v.split(';') if x.strip())
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return tuple(x.strip() for x in v if x.strip())
        raise VaultError('Invalid list field.')

    e = Entry.new(d['account'], d['name'], d['pass'], parts('aliases'), d.get('description', ''), parts('tags'), d.get('url', ''))
    e.validate()
    return e


def parse_import(text: str, ext: str) -> list[Entry]:
    if not isinstance(text, str) or len(text) > MAX_BYTES:
        raise VaultError('Import too large.')
    if text.startswith('\ufeff'):
        text = text[1:]
    ext = ext.lower()
    records = []
    try:
        if ext == '.json':
            def unique(pairs):
                d = {}
                for k, v in pairs:
                    if k in d:
                        raise ValueError()
                    d[k] = v
                return d

            records = json.loads(text, object_pairs_hook=unique)
            if not isinstance(records, list):
                raise ValueError()
        elif ext == '.csv':
            reader = csv.DictReader(io.StringIO(text), strict=True)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError()
            records = list(reader)
        elif ext in {'.txt', '.bat', '.ps1'}:
            current = {}
            for line in text.splitlines():
                if not line.strip():
                    if current:
                        records.append(current)
                        current = {}
                    continue
                # Scripts: only explicit data comments; never evaluate executable syntax.
                if ext == '.ps1':
                    m = re.fullmatch(r'\s*#\s*([A-Za-z]+)\s*:[ \t]?(.*)', line)
                elif ext == '.bat':
                    m = re.fullmatch(r'\s*(?:REM\s+|::\s*)([A-Za-z]+)\s*:[ \t]?(.*)', line, re.I)
                else:
                    m = re.fullmatch(r'\s*([A-Za-z]+)\s*:[ \t]?(.*)', line)
                if not m:
                    raise ValueError()
                k = m[1].lower()
                if k in current:
                    raise ValueError()
                current[k] = m[2]
            if current:
                records.append(current)
        else:
            raise ValueError()
        if not records or len(records) > MAX_ENTRIES:
            raise ValueError()
        items = [_record(d) for d in records]
        ids = [(norm(e.account), e.name) for e in items]
        if len(set(ids)) != len(ids):
            raise ValueError()
        return items
    except Exception:
        raise VaultError('Import rejected: unsupported format, invalid field, missing data or duplicate record.') from None


@dataclass(frozen=True, repr=False)
class ImportPreview:
    records: tuple[Entry, ...]
    new_entries: tuple[Entry, ...]
    duplicate_in_vault: tuple[Entry, ...]


def inspect_import(text: str, ext: str, existing_entries=()) -> ImportPreview:
    items = parse_import(text, ext)
    existing_keys = {(norm(e.account), e.name) for e in existing_entries}
    new_entries = []
    dups = []
    for e in items:
        if (norm(e.account), e.name) in existing_keys:
            dups.append(e)
        else:
            new_entries.append(e)
    return ImportPreview(tuple(items), tuple(new_entries), tuple(dups))


def app_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_inside_app_dir(path) -> bool:
    try:
        p = Path(path).resolve()
        base = app_base_dir()
        return p == base or base in p.parents
    except OSError:
        return False


def default_vault_dir() -> Path:
    if os.name == 'nt':
        local_app = os.environ.get('LOCALAPPDATA')
        if local_app:
            return Path(local_app) / 'PersonalVault'
    return Path.home() / 'PersonalVault'


def synthetic_entries(n: int = 500) -> list[Entry]:
    seeds = [
        Entry.new('Facebook — Demo Personal', 'demo.personal@example.invalid', 'CANARY_DEMO_FB', ['fb chính', 'facebook cá nhân'], 'Dữ liệu giả'),
        Entry.new('Facebook — Demo Shop', 'demo.shop@example.invalid', 'CANARY_DEMO_SHOP', ['fb bán hàng']),
        Entry.new('ETAP Server 15', 'demo15', 'CANARY_DEMO_15', ['etap 15'], 'Máy chủ mô phỏng'),
    ]
    seeds += [Entry.new(f'PSCAD Demo {i}', f'pscad{i}', f'CANARY_DEMO_PSCAD_{i}') for i in range(1, 6)]
    seeds += [Entry.new(f'ETAP Server {i}', f'etap{i}', f'CANARY_DEMO_ETAP_{i}') for i in (1, 5, 11, 51)]
    seeds += [Entry.new(f'Synthetic Account {i}', f'demo{i}', f'CANARY_DEMO_{i}') for i in range(max(0, n - len(seeds)))]
    return seeds[:n]
