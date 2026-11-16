"""Optional local intent extractor (Qwen3-0.6B GGUF, CPU, one-shot subprocess, stdin/stdout only).

The model only turns a question into a search-intent JSON. It never sees the vault and never produces credentials:
every output is schema-validated here and credential-looking strings are dropped.
Nothing runs at import time; no process is spawned until extract_intent() is called with usable files.

Backends (auto): 'completion' loads llama-completion-impl.dll through a tiny `python -I -c` launcher: no sockets,
stdout holds only the generated text. 'cli' runs llama-cli.exe (this llama.cpp build makes it a client of an
embedded loopback HTTP server inside the same process) and is only used when the launcher is unusable (frozen exe).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROMPT_VERSION = 'pv-intent-1'
DEFAULT_MODEL = ''  # Optional: pass model_path or set PVAULT_MODEL_PATH
DEFAULT_LLAMA_DIR = ''  # Optional: pass llama_dir or set PVAULT_LLAMA_DIR
INTENTS = ('find_account', 'refine_search', 'clarify', 'unsupported')
CTX_SIZE, MAX_TOKENS = 2048, 128
MAX_QUERY, MAX_SERVICE = 80, 40

SCHEMA = json.dumps({
    'type': 'object',
    'properties': {
        'intent': {'enum': list(INTENTS)},
        'query': {'type': 'string', 'maxLength': MAX_QUERY},
        'service': {'type': 'string', 'maxLength': MAX_SERVICE},
        'server_id': {'type': 'integer', 'minimum': 0, 'maximum': 9999},
    },
    'required': ['intent', 'query'],
    'additionalProperties': False,
}, separators=(',', ':'))

# Few-shot examples are generic on purpose: nothing here comes from a vault.
SYSTEM = (
    f'[{PROMPT_VERSION}] Trích từ khóa tìm tài khoản. Chỉ xuất MỘT JSON: intent (find_account|refine_search|clarify|unsupported), '
    'query (<=80 ký tự, bỏ từ thừa), service và server_id (tùy chọn). Giữ nguyên số người dùng nêu, không thêm số. '
    'refine_search = câu nối tiếp theo ngữ cảnh. Không xuất mật khẩu.\n'
    'Q: cho mình xin mật khẩu gmail công ty nhé\n'
    'A: {"intent":"find_account","query":"gmail công ty","service":"gmail"}\n'
    'Q: [ngữ cảnh: service=zoom] máy thứ hai thôi\n'
    'A: {"intent":"refine_search","query":"zoom 2","service":"zoom","server_id":2}\n'
    'Q: hôm nay trời đẹp không\n'
    'A: {"intent":"unsupported","query":""}'
)

_CLASSES = (str.islower, str.isupper, str.isdigit)


def secret_like(tok: str) -> bool:
    """Heuristic for password-ish / random tokens. Conservative: false positives only keep us deterministic."""
    tok = tok.strip('.,;:!?()[]"\'')
    if len(tok) >= 20:
        return True
    if len(tok) < 10:
        return False
    sym = any(not c.isalnum() for c in tok)
    n = sum(any(f(c) for c in tok) for f in _CLASSES) + sym
    # e.g. CANARY_DEMO_FB: >=10 chars with a symbol plus upper/digit is treated as a possible password
    return n >= 3 or (any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)) or (
        len(tok) >= 10 and sym and any(c.isupper() or c.isdigit() for c in tok))


_BAD_CHARS = re.compile(r'[\x00-\x1f\\/;{}<>$`|&]|://|\.\.')


def _clean_str(v, limit):
    if not isinstance(v, str) or len(v) > limit or _BAD_CHARS.search(v):
        return None
    return None if any(secret_like(t) for t in v.split()) else v.strip()


def validate_intent(d):
    """Strict allow-list validation. Returns a fresh dict or None. Extra keys / wrong types are rejected."""
    if not isinstance(d, dict) or not {'intent', 'query'} <= set(d) <= {'intent', 'query', 'service', 'server_id'}:
        return None
    if d['intent'] not in INTENTS:
        return None
    out = {'intent': d['intent'], 'query': _clean_str(d['query'], MAX_QUERY)}
    if out['query'] is None:
        return None
    if 'service' in d:
        out['service'] = _clean_str(d['service'], MAX_SERVICE)
        if not out['service']:
            return None
    if 'server_id' in d:
        sid = d['server_id']
        if isinstance(sid, bool) or not isinstance(sid, int) or not 0 <= sid <= 9999:
            return None
        out['server_id'] = sid
    return out


def build_prompt(question: str, prev_intent: dict | None = None) -> str:
    """Raw ChatML, non-thinking: the empty <think></think> block is pre-filled so the model answers directly."""
    q = re.sub(r'<\||\|>|[\x00-\x1f]+', ' ', question)
    q = ' '.join(q.split())[:240]
    ctx = ''
    if prev_intent:
        bits = [f'{k}={prev_intent[k]}' for k in ('service', 'server_id') if prev_intent.get(k) not in (None, '')]
        if bits:
            ctx = f'[ngữ cảnh: {" ".join(bits)}] '
    return (f'<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{ctx}{q}<|im_end|>\n'
            '<|im_start|>assistant\n<think>\n\n</think>\n\n')


_LAUNCH = (
    'import ctypes,os,sys\n'
    'd=sys.argv[1]; os.add_dll_directory(d); os.environ["PATH"]=d+os.pathsep+os.environ.get("PATH","")\n'
    'ctypes.CDLL(os.path.join(d,"ggml.dll")).ggml_backend_load_all_from_path(d.encode())\n'
    'f=getattr(ctypes.CDLL(os.path.join(d,"llama-completion-impl.dll")),"?llama_completion@@YAHHPEAPEAD@Z")\n'
    'a=[b"llama-completion"]+[x.encode("utf-8") for x in sys.argv[2:]]\n'
    'v=(ctypes.c_char_p*(len(a)+1))(*a,None)\n'
    'rc=f(len(a),v)\n'
    'ctypes.CDLL("ucrtbase").fflush(None); os._exit(rc)\n'
)
_ENV_KEEP = ('SystemRoot', 'windir', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP')


def _peak_rss_mb(proc) -> float | None:
    """Peak working set of an (exited) child via psapi; needs only the Popen handle."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t), ('a', ctypes.c_size_t), ('b', ctypes.c_size_t),
                        ('c', ctypes.c_size_t), ('d', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t)]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(pmc)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(int(proc._handle)), ctypes.byref(pmc), pmc.cb)
        return round(pmc.PeakWorkingSetSize / 1048576, 1) if ok else None
    except Exception:
        return None


class QwenRunner:
    def __init__(self, model_path=None, llama_dir=None, timeout_s=10, threads=None, backend='auto'):
        self.model_path = str(model_path or os.environ.get('PVAULT_MODEL_PATH') or DEFAULT_MODEL)
        self.llama_dir = str(llama_dir or os.environ.get('PVAULT_LLAMA_DIR') or DEFAULT_LLAMA_DIR)
        self.timeout_s = timeout_s
        self.threads = threads or max(2, min(8, (os.cpu_count() or 4) // 2))
        self.backend = backend
        self.prompt_log: list[str] = []  # RAM only; exists so tests can prove nothing from the vault is sent
        self.last_latency_ms = 0
        self.last_tokens_per_s: float | None = None
        self.last_peak_rss_mb: float | None = None
        self.last_error: str | None = None
        self.calls = 0

    def available(self) -> bool:
        try:
            return bool(self.model_path and self.llama_dir) and Path(self.model_path).is_file() and self._backend() is not None
        except OSError:
            return False

    def _backend(self):
        if not self.llama_dir:
            return None
        d = Path(self.llama_dir)
        if self.backend in ('auto', 'completion') and not getattr(sys, 'frozen', False) \
                and (d / 'llama-completion-impl.dll').is_file() and (d / 'ggml.dll').is_file():
            return 'completion'
        if self.backend in ('auto', 'cli') and (d / 'llama-cli.exe').is_file():
            return 'cli'
        return None

    @staticmethod
    def _validate(d):
        return validate_intent(d)

    def _argv(self, prompt: str):
        base = ['-m', self.model_path, '-n', str(MAX_TOKENS), '-c', str(CTX_SIZE), '-t', str(self.threads),
                '--temp', '0', '--no-warmup', '--json-schema', SCHEMA, '--no-display-prompt']
        if self._backend() == 'completion':
            return [sys.executable, '-I', '-c', _LAUNCH, self.llama_dir, *base, '-p', prompt, '-no-cnv']
        sysm = re.search(r'<\|im_start\|>system\n(.*?)<\|im_end\|>', prompt, re.S).group(1)
        user = re.search(r'<\|im_start\|>user\n(.*?)<\|im_end\|>', prompt, re.S).group(1)
        return [str(Path(self.llama_dir) / 'llama-cli.exe'), *base, '-st', '--no-jinja', '--simple-io',
                '-sys', sysm, '-p', user]

    def _exec(self, prompt: str):
        """Run one inference; returns stdout text or None. Hard timeout -> kill."""
        kw = {}
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kw = {'creationflags': 0x08000000, 'startupinfo': si}
        env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}  # no vault path / key can reach the worker
        p = subprocess.Popen(self._argv(prompt), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=self.llama_dir, env=env, **kw)
        try:
            out, err = p.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            self.last_error = 'timeout'
            return None
        self.last_peak_rss_mb = _peak_rss_mb(p)
        m = re.search(r'(?<!prompt )eval time[^\n]*?([\d.]+) tokens per second', err.decode('utf-8', 'replace'))
        self.last_tokens_per_s = float(m.group(1)) if m else None
        if p.returncode != 0:
            self.last_error = f'exit {p.returncode}'
            return None
        return out.decode('utf-8', 'replace')

    @staticmethod
    def _parse(text):
        dec, best = json.JSONDecoder(), None
        for m in re.finditer(r'\{', text or ''):
            try:
                obj, _ = dec.raw_decode(text, m.start())
            except ValueError:
                continue
            if isinstance(obj, dict):
                best = obj  # last object wins: llama-cli may echo the user text before the answer
        return best

    def extract_intent(self, question, prev_intent=None):
        """Never raises. Returns a validated intent dict or None (unavailable / timeout / garbage)."""
        self.last_error = None
        t0 = time.perf_counter()
        try:
            if not self.available() or not isinstance(question, str):
                return None
            prompt = build_prompt(question, prev_intent)
            self.prompt_log.append(prompt)
            del self.prompt_log[:-200]
            self.calls += 1
            return validate_intent(self._parse(self._exec(prompt)))
        except Exception as e:  # noqa: BLE001 - contract: never raise
            self.last_error = type(e).__name__
            return None
        finally:
            self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
