"""Chat-search pipeline: deterministic-first router over personal_vault.core.search, Qwen only for hard queries.

Public API:  ChatPipeline(runner=None).answer(query, entries) -> dict ;  .clear()
- entries=None means locked -> VaultError('Vault is locked.'). entries=[] is a valid empty vault.
- runner=None disables the model completely (deterministic only, route is always 'deterministic').
- Returns metadata only (never a password). Actions are *suggestions* the UI performs on an explicit click.
- Nothing about the vault is kept between calls: context is {service, server_id, ids} in RAM, cleared by clear().
"""
from __future__ import annotations

import functools
import re
import sys
import time
import unicodedata
from collections import OrderedDict
from difflib import SequenceMatcher
from pathlib import Path

MVP_DIR = Path(__file__).resolve().parent.parent / 'PersonalVault_MVP'
if str(MVP_DIR) not in sys.path:
    sys.path.insert(0, str(MVP_DIR))

from personal_vault.core import VaultError, norm, search  # noqa: E402
from qwen_runner import secret_like, validate_intent  # noqa: E402  (pure functions, spawns nothing)

MAX_ITEMS, MAX_Q, ELIGIBLE_MAX = 10, 400, 200
MAX_RAW = 5000


def _dig(t: str) -> bool:
    """A real number token: ASCII decimal digits only ('❶', '፩', '²' pass str.isdigit() but int() raises)."""
    return t.isascii() and t.isdecimal()

STATUS = {'exact': 'exact', 'ambiguous': 'ambiguous', 'match': 'suggested', 'suggestion': 'suggested', 'none': 'none'}
RANK = {'exact': 5, 'match': 4, 'ambiguous': 3, 'suggestion': 2, 'none': 0}

# Accent-free (core.norm) filler phrases, longest first. 'cai/may/so/thu' are "soft": dropped only in a second attempt.
_HARD = ['vui long', 'lam on', 'xin', 'cho toi', 'cho minh', 'cho em', 'cho anh', 'toi muon', 'toi can', 'minh muon', 'minh can', 'tim giup', 'tim kiem',
         'giup toi', 'giup minh', 'giup em', 'hien thi', 'sao chep', 'ten dang nhap', 'mat khau', 'tai khoan', 'cua toi', 'la gi',
         'o dau', 'giup', 'tim', 'xem', 'lay', 'mo', 'hien', 'copy', 'mk', 'pass', 'password', 'tk', 'acc', 'account', 'user',
         'username', 'cua', 'nhe', 'nha', 'nhi', 'di', 'voi', 'a', 'ah', 'oi', 'ho', 'cho', 'toi', 'minh', 'em', 'anh', 'la',
         'cai', 'ay', 'nao', 'day', 'do', 'nay']
_SOFT = ['may', 'so', 'thu', 'ket qua', 'muc', 'dong']


@functools.lru_cache(maxsize=64)
def _hard_re(protect: frozenset = frozenset()) -> re.Pattern:
    """Filler-word regex; `protect` words are NOT dropped (they carry meaning in this query / vault)."""
    return re.compile(r'\b(?:' + '|'.join(sorted((w for w in _HARD if w not in protect), key=len, reverse=True)) + r')\b')


_HARD_RE = _hard_re()
_HARD_SET = set(_HARD)
_SOFT_RE = re.compile(r'\bmay\b|\b(?:so|ket qua|muc|dong)\b(?=\s+\d)|\bthu\b(?=\s+(?:\d|nhat|nhi|hai|ba|tu|nam|sau|bay|tam|chin))')  # 'dòng/mục/kết quả' only before a number ('Đông Á' is a name)
_MARK = {'thu', 'cai', 'may', 'so', 'ket', 'qua', 'muc', 'dong'}
_STRONG = {'thu', 'so', 'may', 'muc', 'dong', 'qua'}  # these make ANY ordinal word an ordinal ('thứ ba', 'máy sáu')
_ORD_SAFE = {'nhat', 'dau', 'cuoi', 'hai', 'mot', 'nhi'}  # these also work after the weak marker 'cái' ('cái đầu'); 'ba/tư/năm/sáu' do not
_POS_MARK = {'thu', 'muc', 'dong', 'cai'}  # ... and a digit a list *position* (not an identity number)
_NEG_WORDS = {'tru', 'ngoai'}  # 'trừ shop', 'ngoại trừ ...': an exclusion, never a selection
_PRON_AFTER_NHA = {'toi', 'minh', 'em', 'anh', 'chi', 'ta', 'cua', 'chung'}  # 'nhà tôi' = my house, not the particle 'nha'
_ORD = {'nhat': 1, 'mot': 1, 'dau': 1, 'hai': 2, 'nhi': 2, 'ba': 3, 'tu': 4, 'bon': 4, 'nam': 5, 'sau': 6, 'bay': 7, 'tam': 8,
        'chin': 9, 'cuoi': -1}
_PRON = {'no', 'do', 'nay', 'ay', 'day'}
_KEEP = {'cai', 'do', 'nay', 'ay', 'day'}
_FU = set(_ORD) | _PRON | {'cai', 'may', 'so', 'thu', 'ket', 'qua', 'muc', 'dong', 'tien', 'cung', 'va', 'trong'}
_INJECT = re.compile(r'bo qua (?:moi )?(?:huong dan|chi dan|lenh)|ignore (?:all |the |any )?(?:previous|prior|above)|system prompt|'
                     r'master (?:password|pass)|mat khau master|jailbreak|developer mode')
_CRED = re.compile(r'(?i)\b(?:pass(?:word|wd)?|pwd|mk|m[aậ]t kh[aẩ]u|secret|token|api[-_ ]?key)\s*[:=]')
_SCRIPT = re.compile(r'(?i)[;|&`<>{}\\]|\$\(|://|\b(?:curl|wget|powershell|cmd|bash|sudo|rm|del|eval|exec|import|select)\b|'
                     r'\.(?:exe|ps1|bat|sh|py)\b')


def _identity_tokens(e):
    return [set(norm(i).split()) for i in (e.account, *e.aliases)]


def _meta(e):
    return {'id': e.id, 'account': e.account, 'name': e.name, 'aliases': list(e.aliases), 'description': e.description,
            'tags': list(e.tags), 'url': e.url}


def eligible_for_model(raw: str) -> bool:
    """Spec 5.2: input that may carry a secret / script never reaches the model."""
    if len(raw) > ELIGIBLE_MAX or any(ord(c) < 32 for c in raw):
        return False
    if _CRED.search(raw) or _SCRIPT.search(raw):
        return False
    return not any(secret_like(t) for t in raw.split())


def _action(q: str):
    has_copy = re.search(r'\b(?:copy|sao chep)\b', q)
    if re.search(r'\b(?:user|username|ten dang nhap)\b', q):
        return 'copy_username'
    if re.search(r'\b(?:mat khau|mk|pass|password)\b', q):
        return 'copy_password' if has_copy else 'show'
    return None


def _clean(q: str, protect: frozenset = frozenset()):
    hard = ' '.join(_hard_re(protect).sub(' ', q).split())
    return hard, ' '.join(_SOFT_RE.sub(' ', hard).split())


def _protected_fillers(raw: str, q: str, singles: frozenset = frozenset()) -> frozenset:
    """Filler words that must NOT be dropped for this query because the raw text shows they are content:
    'nhà' (house) / 'mô' (model, as in 'mô phỏng') lose their accent in the normalised text and then look like the
    particles 'nha' / 'mở'; an unaccented 'nha' followed by a pronoun or real words; and a letter glued to a number
    ('15a', 'a3', '15-A') which is part of an identity, not the particle 'a'."""
    cf = unicodedata.normalize('NFC', raw.casefold())
    keep = set()
    if re.search(r'(?<!\w)nhà(?!\w)', cf):
        keep.add('nha')
    if re.search(r'(?<!\w)mô(?!\w)', cf):
        keep.add('mo')
    if re.search(r'(?<![a-z])[a-z][-_/.]?\d|\d[-_/.]?[a-z](?![a-z])', cf):
        keep.add('a')
    toks = q.split()
    if 'a' in singles and 'a' in toks[:-1]:  # 'dev box a b', 'dev box a, b': not the sentence-final particle
        keep.add('a')
    for i, t in enumerate(toks):
        if t == 'nha' and i + 1 < len(toks) and (toks[i + 1] in _PRON_AFTER_NHA or any(x not in _HARD_SET for x in toks[i + 1:])):
            keep.add('nha')
    return frozenset(keep)


def _hay_tokens(e) -> set:
    return {t for x in (e.account, e.name, e.description, *e.aliases, *e.tags) for t in norm(x).split()}


# Words that are function words in every context we handle. Dropping one of THESE never makes an answer uncertain.
_SAFE_DROP = {'cho toi', 'cho minh', 'cho em', 'cho anh', 'toi muon', 'toi can', 'minh muon', 'minh can', 'tim giup', 'tim kiem',
              'giup toi', 'giup minh', 'giup em', 'hien thi', 'sao chep', 'ten dang nhap', 'mat khau', 'tai khoan', 'cua toi', 'la gi',
              'vui long', 'lam on', 'xin', 'giup', 'copy', 'password', 'pass', 'username', 'account', 'tk', 'mk', 'acc', 'user', 'nhe',
              'voi', 'oi', 'cua', 'toi', 'may', 'so', 'thu', 'muc', 'dong', 'ket qua', 'tim', 'xem', 'lay'}
_CODE_LIKE = re.compile(r'[{}<>$`\\|]|://')  # template / markup / shell syntax is not a question about an account


def _all_vocab(entries) -> set:
    """Every word the vault itself contains (identity, username, description, tags): the only authority on what is content."""
    return {t for e in entries for x in (e.account, e.name, e.description, *e.aliases, *e.tags) for t in norm(x).split()}


def _risky_drop(head: str, hard: str, protect: frozenset, vocab_all: set, rawf: dict, caps: frozenset = frozenset()) -> bool:
    """True if a word dropped as filler could actually be content. Then the answer can still be SUGGESTED, never auto-confirmed.
    Risk = the dropped word is in the vault's own vocabulary, is a single letter / number, or (for non-function words) the user
    typed an accented variant of it. This replaces growing stop-word lists: unknown or ambiguous words just cap confidence."""
    risky = False
    spans = [m.group(0) for m in _hard_re(protect).finditer(head)] + [m.group(0) for m in _SOFT_RE.finditer(hard)]
    for text in spans:
        toks = text.split()
        if any(t in vocab_all or len(t) == 1 or _dig(t) for t in toks):
            risky = True
        elif text not in _SAFE_DROP and (any(f != t for t in toks for f in rawf.get(t, ())) or any(t in caps for t in toks)):
            risky = True
    return risky


def _vocab(entries) -> set:
    return {t for e in entries for i in (e.account, *e.aliases) for t in norm(i).split()}


def _split_negation(q: str, vocab: set, protect: frozenset = frozenset()):
    """'facebook trừ shop' -> ('facebook', (('shop',),)); 'etap trừ 1 và 5' -> ('etap', (('1',), ('5',)));
    'dev box không phải a mà b' -> ('dev box b', (('a',),)). Each item is excluded when ALL its words describe an entry;
    an entry is dropped if ANY item matches. A negator that is itself a vault word is not one; single-letter identities survive."""
    toks = q.split()
    letters = frozenset(w for w in vocab if len(w) == 1) | protect

    def items_of(tail):
        out, cur = [], []
        for t in tail + ['va']:
            if t in ('va', 'hoac', 'voi', 'cung'):
                words = tuple(x for x in _hard_re(letters).sub(' ', ' '.join(cur)).split() if x not in ('ra', 'may', 'so'))
                if words:
                    out.append(words)
                cur = []
            else:
                cur.append(t)
        return tuple(out)

    for i, t in enumerate(toks):
        if t in _NEG_WORDS and t not in vocab:
            j = i + 1
        elif t == 'khong' and toks[i + 1:i + 2] == ['phai'] and 'khong' not in vocab:
            j = i + 2
        else:
            continue
        tail = toks[j:]
        if tail[:1] == ['tru']:  # 'ngoại trừ'
            tail = tail[1:]
        if 'ma' in tail:  # 'not A but B': exclude A, search for B
            k = tail.index('ma')
            return ' '.join(toks[:i] + tail[k + 1:]), items_of(tail[:k])
        return ' '.join(toks[:i]), items_of(tail)
    return q, ()


def _raw_forms(text: str) -> dict:
    """normalised word -> the raw (accented, casefolded) spellings seen in `text`."""
    out = {}
    for tok in re.findall(r'[^\W_]+', unicodedata.normalize('NFC', text.casefold())):
        n = norm(tok)
        if n and ' ' not in n:
            out.setdefault(n, set()).add(tok)
    return out


def _accent_conflict(qforms: dict, e) -> bool:
    """'hộp' and 'họp' (or 'phòng' / 'phỏng') are different words that collapse to the same accent-free text. If the user
    typed an accented word and the entry only has OTHER accented spellings of it, they are not the same word.
    A plain (unaccented) spelling on either side stays compatible, so accent-free typing keeps working."""
    eforms = _raw_forms(' '.join([e.account, e.name, e.description, *e.aliases, *e.tags]))
    for k, qa in qforms.items():
        accented = {f for f in qa if f != k}
        ef = eforms.get(k)
        if accented and ef and all(f != k for f in ef) and not (ef & accented):
            return True
    return False


_CANON = {'sau': 'sáu', 'nam': 'năm', 'tu': 'tư', 'bay': 'bảy', 'tam': 'tám', 'chin': 'chín', 'bon': 'bốn', 'mot': 'một',
          'nhat': 'nhất', 'dau': 'đầu', 'cuoi': 'cuối', 'nhi': 'nhì', 'hai': 'hai', 'ba': 'ba'}
_POSSESSIVE = {'cua', 'toi', 'minh'}  # 'máy của tôi số 5': transparent between a marker and its number (but 'của anh Ba' is not)
_CONJ = ('va', 'hoac', 'voi', 'cung')


def _token_ok(tok: str, itoks: set) -> bool:
    if tok in itoks:
        return True
    if _dig(tok) or len(tok) <= 3:  # numbers, single letters and short words are identities: exact token only
        return False
    # a typo of a real word: close spelling, or the same letters transposed ('eatp' ~ 'etap')
    return any(len(u) >= 4 and (SequenceMatcher(None, tok, u).ratio() >= 0.85 or (len(tok) == len(u) and sorted(tok) == sorted(u))) for u in itoks)


def _guard_fuzzy(e, qtokens) -> bool:
    """A fuzzy hit is only a suggestion if EVERY query word matches a word of one identity of the entry; a shared
    suffix like 'demo 3' must never outweigh a different service name."""
    return any(all(_token_ok(t, itoks) for t in qtokens) for itoks in _identity_tokens(e))


class ChatPipeline:
    def __init__(self, runner=None, cache_size: int = 64):
        self.runner = runner
        self._cache: OrderedDict = OrderedDict()
        self._cache_size = cache_size
        self._ctx = None  # {'service', 'server_id', 'ids'} of the last confirmed result
        self.history: list[dict] = []  # intents + result ids only, RAM only

    def clear(self):
        self._cache.clear()
        self._ctx = None
        self.history.clear()

    # ---------------------------------------------------------------- public
    def answer(self, query, entries) -> dict:
        t0 = time.perf_counter()
        if entries is None:
            raise VaultError('Vault is locked.')
        if not isinstance(query, str):
            raise VaultError('Invalid query.')
        # invisible format characters (zero-width space/joiner, bidi marks) must not split words or numbers; NFC makes 'a'+U+0323 the same 'ạ'
        query = unicodedata.normalize('NFC', ''.join(c for c in query if unicodedata.category(c) != 'Cf'))
        if len(query) > MAX_RAW:
            res = self._pack('deterministic', 'none', [], 'Câu hỏi quá dài. Hãy viết ngắn gọn.', True)
        else:
            try:
                res = self._answer(query, list(entries))
            except VaultError:
                raise
            except Exception:  # noqa: BLE001 - fail safe: an odd input must give 'no answer', never a crash or a guess
                res = self._pack('deterministic', 'none', [], 'Không xử lý được câu hỏi này. Hãy viết lại ngắn gọn.', True)
        res['latency_ms'] = int((time.perf_counter() - t0) * 1000)
        return res

    # --------------------------------------------------------------- helpers
    def _pack(self, route, kind, items, message, clarify, action=None, intent=None, ctx=None, keep_ctx=False):
        status = STATUS[kind]
        if not (status == 'exact' and len(items) == 1):
            action = None  # an action is only suggested when exactly one entry is confidently identified
        if not keep_ctx:
            self._ctx = {**ctx, 'ids': [e.id for e in items[:2000]], 'status': status} if ctx and items else None
            self.history.append({'intent': intent, 'ids': [e.id for e in items[:MAX_ITEMS]]})
            del self.history[:-10]
        return {'route': route, 'kind': kind, 'status': status, 'entries': [_meta(e) for e in items[:MAX_ITEMS]],
                'message': message, 'clarify': clarify, 'suggested_action': action, 'latency_ms': 0, 'intent': intent,
                'total': len(items)}

    @staticmethod
    def _msg(status, items, action):
        n = len(items)
        names = '; '.join(f'{i}) {e.account}' for i, e in enumerate(items[:5], 1))
        if status == 'exact':
            hint = {'copy_password': ' Bấm «Sao chép mật khẩu» để sao chép.', 'copy_username': ' Bấm «Sao chép tên đăng nhập» để sao chép.',
                    'show': ' Bấm «Hiện mật khẩu» để xem.'}.get(action, '')
            return f'Tìm thấy «{items[0].account}».{hint}'
        if status == 'ambiguous':
            return f'Có {n} kết quả phù hợp, bạn muốn cái nào? {names}'
        if status == 'suggested':
            return (f'Có phải bạn muốn «{items[0].account}»? Hãy xác nhận.' if n == 1
                    else f'Chưa chắc chắn, gợi ý: {names}. Bạn chọn cái nào?')
        return 'Không tìm thấy tài khoản phù hợp.'

    def _search(self, entries, hard, soft, prot=None, rawf=None):
        best = ('none', [], None)
        for q in dict.fromkeys(x for x in (prot, hard, soft) if x):
            r = search(entries, q)
            kind, items = r.kind, list(r.items)
            if rawf:
                qw = set(norm(q).split())  # fillers such as 'mở' are not part of the query and cannot conflict
                qf = {k: v for k, v in rawf.items() if k in qw}
                if kind == 'exact':
                    if any(_accent_conflict(qf, e) for e in items):  # same ASCII text, different accented word: not a unique basis
                        kind = 'match' if len(items) == 1 else 'ambiguous'
                else:
                    items = [e for e in items if not _accent_conflict(qf, e)]
                    if not items:
                        kind = 'none'
            words = [t for t in norm(q).split() if not _dig(t)]
            if kind in ('match', 'ambiguous') and words and all(len(t) <= 3 for t in words):
                # short words ('ba', 'may', 'anh') are too ambiguous to select an account through a description/url hit alone
                items = [e for e in items if any(t in itoks for itoks in _identity_tokens(e) for t in words)]
                if not items:
                    kind = 'none'
            if kind == 'suggestion':
                toks = norm(q).split()
                items = [e for e in items if _guard_fuzzy(e, toks)]
                if not items:
                    kind = 'none'
            if RANK[kind] > RANK[best[0]]:
                best = (kind, items, q)
        return best

    @staticmethod
    def _service_ctx(cleaned: str):
        toks = cleaned.split()
        nums = [t for t in toks if _dig(t)]
        svc = next((t for t in toks if t.isalpha()), None)
        return {'service': svc, 'server_id': int(nums[-1]) if len(nums) == 1 else None}

    def _intent_of(self, kind, cleaned, ctx):
        d = {'intent': kind, 'query': cleaned[:80]}
        d.update({k: v for k, v in (ctx or {}).items() if k in ('service', 'server_id') and v is not None})
        return d

    # ------------------------------------------------------------- follow-up
    def _followup(self, q, entries, action, singles=frozenset(), rawf=None, protect=frozenset(), accented=False):
        rawf = rawf or {}
        toks = q.split()
        if 'may' in toks and rawf.get('may') and not ({'máy', 'may'} & rawf['may']):
            return None  # 'mấy' (several) is not 'máy' (machine)
        spans = [(m.start(), m.end()) for m in _hard_re(protect).finditer(q) if m.group(0) not in _KEEP]
        rest, prevs, directs, pos = [], [], [], 0
        for i, t in enumerate(toks):
            a = q.index(t, pos)
            pos = a + len(t)
            letter = len(t) == 1 and t.isalpha() and t in singles  # a standalone ASCII letter ('ạ' is not one)
            if letter or not any(s0 <= a and pos <= e0 for s0, e0 in spans):
                rest.append(t)
                j = i - 1
                while j >= 0 and toks[j] in _POSSESSIVE:
                    j -= 1
                k = j - 1
                while k >= 0 and toks[k] in _POSSESSIVE:
                    k -= 1
                prevs.append((toks[j] if j >= 0 else '', toks[k] if k >= 0 else ''))  # ORIGINAL neighbours: 'của anh Ba' has no marker
                directs.append(toks[i - 1] if i > 0 else '')
        if not rest:
            return None

        def is_machine(pv):  # 'máy 5', 'máy số 5' = identity number; 'máy thứ hai' = position
            return pv[0] == 'may' or (pv[0] == 'so' and pv[1] == 'may')

        refs, last, last_word, kind_of_last = [], None, None, None
        for i, w in enumerate(rest):
            pv = prevs[i]
            follows_ref = last is not None and (pv[0] in _CONJ or pv[0] == last_word or (pv[0] == 'so' and pv[1] in _CONJ and is_machine(last)))
            if w in _ORD:
                nxt = rest[i + 1] if i + 1 < len(rest) else ''
                forms = rawf.get(w, set())
                if w in _CANON and (_CANON[w] not in forms and (not forms or w not in forms or (accented and _CANON[w] != w))  # 'tự', 'Hải', 'đâu', 'bay'
                                    or (w == 'nam' and nxt == 'nay') or (w == 'sau' and nxt == 'cung')):  # 'năm nay', 'sau cùng'
                    return None
                if last is not None and rest[i - 1] == last_word and kind_of_last == 'word':
                    return None  # 'hai tư' = 24, not two separate references
                if directs[i] == 'cua':
                    return None  # 'máy của Ba' = somebody's machine (a possessor), not machine 3
                if not (pv[0] in _STRONG or (pv[0] == 'cai' and w in _ORD_SAFE) or follows_ref):
                    return None  # bare 'năm', 'sáu', 'ba', 'tư' (or after a title like 'anh') are ordinary words, not ordinals
                kind = 'word'
            elif _dig(w):
                kind = 'digit'
            elif len(w) == 1 and w.isalpha() and w in singles and (pv[0] == 'may' or (follows_ref and is_machine(last))):
                kind = 'letter'
            elif len(w) == 1 and w in singles and i == len(rest) - 1:
                continue  # sentence-final particle 'a'
            elif w in _FU:
                continue
            else:
                return None
            use = last if follows_ref else pv
            refs.append((_ORD[w] if kind == 'word' else int(w) if kind == 'digit' else w, kind, use, w))
            last, last_word, kind_of_last = use, w, kind
        pron = any(w in _PRON for w in rest)
        if not refs and not pron:
            return None
        by_id = {e.id: e for e in entries}
        group = [by_id[i] for i in (self._ctx or {}).get('ids', []) if i in by_id]
        intent = {'intent': 'refine_search', 'query': ' '.join(rest)[:80]}
        if len(group) == 1 and refs and not pron:
            # a number/ordinal is not a reference into a list of one: it must never re-confirm that entry
            if any(r[2][0] == 'may' or r[2][0] in _POS_MARK or r[2][0] == 'qua' for r in refs):
                return self._pack('deterministic', 'none', [], 'Chỉ có 1 kết quả trước đó, không có mục nào khác để chọn. Bạn muốn tìm tài khoản nào?',
                                  True, intent=intent, keep_ctx=True)
            return None  # bare number: search afresh
        if not group:
            if not pron and all(r[1] == 'digit' and not (is_machine(r[2]) or r[2][0] in _POS_MARK or r[2][0] == 'qua') for r in refs):
                return None  # 'tài khoản 12' with nothing to refine: let the normal search handle it
            return self._pack('deterministic', 'none', [], 'Chưa có kết quả trước đó để chọn. Bạn muốn tìm tài khoản nào?',
                              True, intent=intent, keep_ctx=True)
        keep = {'service': self._ctx.get('service'), 'server_id': self._ctx.get('server_id')}

        def by_identity(n):
            return [e for e in group if any(str(n) in t for t in _identity_tokens(e))]

        shown = group[:MAX_ITEMS]  # the user can only point at what was displayed; the rest of the group stays reachable by identity number

        def by_position(n):
            if n == -1:  # 'cái cuối' is the last DISPLAYED item, so it is only unambiguous when the whole group was displayed
                return [group[-1]] if len(group) <= MAX_ITEMS else []
            return [shown[n - 1]] if 0 < n <= len(shown) else []

        soft_pos = []  # unmarked numbers ('số 2', '2') resolved ONLY by list position: offered, never confirmed

        def clash(n):  # a number is both a list position and an identity number: if they differ, ask
            pos_hit, ident = by_position(n), by_identity(n)
            if pos_hit and ident and pos_hit[0] not in ident:
                return pos_hit + ident
            if not ident and pos_hit:
                soft_pos.append(n)
            return ident or pos_hit

        def resolve(n, kind, pv, w):
            if kind == 'letter':
                return by_identity(n)
            if kind == 'word':
                if not is_machine(pv):
                    return clash(n) if pv[0] == 'so' else by_position(n)  # 'số năm' = number five OR the fifth: ask
                if pv[0] == 'so':  # 'máy số năm' = machine number five
                    return by_identity(n)
                pos_hit, ident = by_position(n), by_identity(n)  # 'máy hai' / 'máy đầu tiên': machine N or the N-th result
                if ident and pos_hit and pos_hit[0] not in ident:
                    return pos_hit + ident  # both readings exist: ask
                return ident  # only the position exists: 'máy 2' that does not exist is NOT answered with the 2nd result
            if is_machine(pv):
                return by_identity(n)
            if pv[0] in _POS_MARK or pv[0] == 'qua':  # 'thứ 2', 'số 3', 'cái 4'
                return by_position(n)
            return clash(n)

        if refs:
            hit, missing = [], False
            for r in refs:
                got = resolve(*r)
                missing = missing or not got
                for e in got:
                    if e not in hit:
                        hit.append(e)
            if not hit or missing:  # one unresolved reference makes the whole request unanswerable: never answer only part of it
                n = refs[0][0]
                msg = (f'Không có máy {n} trong nhóm vừa tìm.' if is_machine(refs[0][2])
                       else f'Danh sách có {len(group)} kết quả nhưng chỉ hiển thị {MAX_ITEMS}. Hãy chọn theo số trong danh sách đang hiển thị, hoặc nêu rõ số máy / tên.'
                       if len(group) > MAX_ITEMS
                       else f'Chỉ có {len(group)} kết quả trước đó, không có cái thứ {n}.')
                return self._pack('deterministic', 'none', [], msg, True, intent=intent, keep_ctx=True)
            if len(hit) == 1 and len(refs) == 1 and (soft_pos or (len(group) == 1 and self._ctx.get('status') != 'exact')):
                if len(group) == 1:  # a reference into an unconfirmed single suggestion is not a confirmation, with or without 'nó'
                    return self._pack('deterministic', 'none', [], f'Bạn đang nói tới gợi ý «{group[0].account}»? Hãy gõ rõ tên tài khoản để xác nhận.',
                                      True, intent=intent, keep_ctx=True)
                return self._pack('deterministic', 'match', hit, f'Ý bạn là mục thứ {refs[0][0]} trong danh sách, «{hit[0].account}»? Hãy xác nhận bằng tên hoặc nói rõ «thứ {refs[0][0]}».',
                                  True, None, intent, keep)
            if len(hit) == 1 and len(refs) == 1:
                new_ctx = {**keep, 'server_id': refs[0][0]} if is_machine(refs[0][2]) and refs[0][1] == 'digit' else keep
                return self._pack('deterministic', 'exact', hit, self._msg('exact', hit, action), False, action, intent, new_ctx)
            kind = 'ambiguous' if len(hit) > 1 else 'match'  # several references (or a position/identity clash): the user picks
            return self._pack('deterministic', kind, hit, self._msg(STATUS[kind], hit, action), True, None, intent, keep)
        if len(group) == 1:
            if self._ctx.get('status') == 'exact':
                return self._pack('deterministic', 'exact', group, self._msg('exact', group, action), False, action, intent, keep)
            # 'nó' / 'no' after an unconfirmed suggestion is not a confirmation: ask for the name.
            return self._pack('deterministic', 'none', [], f'Bạn đang nói tới gợi ý «{group[0].account}»? Hãy gõ rõ tên tài khoản để xác nhận.',
                              True, intent=intent, keep_ctx=True)
        return self._pack('deterministic', 'ambiguous', group, 'Bạn muốn nói tới cái nào? ' + self._msg('ambiguous', group, action),
                          True, intent=intent, keep_ctx=True)

    # ------------------------------------------------------------------ main
    def _answer(self, raw, entries):
        q = norm(raw)
        if not q:
            return self._pack('deterministic', 'none', [], 'Bạn muốn tìm tài khoản nào?', True)
        if _CODE_LIKE.search(raw):
            return self._pack('deterministic', 'none', [], 'Câu hỏi có ký tự lạ (mã/định dạng). Hãy viết lại bằng chữ thường.', True)
        if len(q) > MAX_Q:  # never cut the tail off: 'etap server 15' must not become 'etap server 1'
            return self._pack('deterministic', 'none', [], 'Câu hỏi quá dài. Hãy viết ngắn gọn.', True)
        if _INJECT.search(q):
            return self._pack('deterministic', 'none', [], 'Mình chỉ tìm tài khoản trong kho; không thực hiện yêu cầu này.', False)
        action = _action(q)
        singles = frozenset(re.findall(r'(?<![^\W\d_])[a-z](?![^\W\d_])', raw.casefold()))  # standalone ASCII letters ('ạ' is not 'a')
        rawf = _raw_forms(raw)
        mand = _protected_fillers(raw, q, singles)  # never dropped for this query
        fu = self._followup(q, entries, action, singles, rawf, mand, any(ord(c) > 127 for c in raw))
        if fu is not None:
            return fu
        vocab = _vocab(entries)
        head, neg = _split_negation(q, vocab, mand)
        hard, soft = _clean(head, mand)
        if not hard:
            return self._pack('deterministic', 'none', [], 'Bạn muốn tìm tài khoản nào?', True)
        prot_set = frozenset(w for w in vocab & _HARD_SET if len(w) > 1 or w in singles)
        prot = _clean(head, mand | prot_set)[0]  # also try with filler words that are identity words here ('Dev Box A')
        user_nums = {t for t in q.split() if _dig(t)} - {t for it in neg for t in it}
        kind, items, cand = self._search(entries, hard, soft, prot, rawf)
        extra_keep = (prot_set if cand == prot else frozenset())
        words_raw = re.findall(r'[^\W_]+', raw)
        caps = frozenset(norm(w) for i, w in enumerate(words_raw) if i > 0 and w[:1].isupper() and not w.isupper())  # 'anh Minh', not 'Cho tôi', not 'ETAP'
        risky = bool(cand) and _risky_drop(head, hard, mand | extra_keep, _all_vocab(entries), rawf, caps)
        if neg and items:  # exclusion: drop entries that carry any excluded word
            kept = [e for e in items if not any(all(t in _hay_tokens(e) for t in item) for item in neg)]  # an item excludes only if ALL its words describe the entry
            if len(kept) != len(items):
                kind = 'none' if not kept else 'match' if len(kept) == 1 and kind != 'suggestion' else kind
                items = kept
        base_ctx = self._service_ctx(soft or hard)
        intent = self._intent_of('find_account', soft or hard, base_ctx)
        ntok = len((soft or hard).split())
        conversational = ntok >= 3 or len(q.split()) >= 6
        need_model = kind == 'none' or (kind in ('suggestion', 'ambiguous') and conversational)
        route = 'deterministic'
        if need_model and self.runner is not None:
            if not eligible_for_model(raw):
                return self._finish('deterministic', kind, items, user_nums, action, intent, base_ctx,
                                    extra='Câu hỏi có vẻ chứa thông tin nhạy cảm, quá dài hoặc giống lệnh nên không dùng mô hình; hãy viết lại ngắn gọn.')
            route, got = 'fallback', self._ask_model(raw, q, user_nums)
            if got:
                m_intent, m_kind, m_items = self._research(entries, got)
                intent = m_intent
                if m_kind != 'none' and m_items:
                    route, kind, items = 'qwen', m_kind, m_items
                    base_ctx = {'service': got.get('service') or base_ctx['service'], 'server_id': got.get('server_id', base_ctx['server_id'])}
                elif got['intent'] in ('clarify', 'unsupported'):
                    route = 'qwen'
        return self._finish(route, kind, items, user_nums, action, intent, base_ctx, capped=risky)

    def _finish(self, route, kind, items, user_nums, action, intent, ctx, extra='', capped=False):
        if capped and kind == 'exact':  # exact gate: a dropped word that may be content -> suggestion, never auto-confirmed
            kind = 'match' if len(items) == 1 else 'ambiguous'
        if user_nums:  # numeric identity is exact-token on account/alias, whatever path produced the items
            ok = [e for e in items if any(user_nums <= t for t in _identity_tokens(e))]
            if len(ok) != len(items):
                kind = 'none' if not ok else kind if kind == 'suggestion' else 'match' if len(ok) == 1 else 'ambiguous'
                items = ok
        status = STATUS[kind]
        msg = self._msg(status, items, action) + (' ' + extra if extra else '')
        return self._pack(route, kind, items, msg, status in ('ambiguous', 'suggested') or bool(extra), action, intent, ctx)

    # ----------------------------------------------------------------- model
    def _ask_model(self, raw, q, user_nums):
        """At most one runner call per turn. Returns a validated, identity-consistent intent or None."""
        prev = None
        if self._ctx and (self._ctx.get('service') or self._ctx.get('server_id') is not None):
            prev = {'service': self._ctx.get('service'), 'server_id': self._ctx.get('server_id')}
        key = (q, prev and tuple(prev.items()))
        got = self._cache.get(key)
        if got is not None:
            self._cache.move_to_end(key)
            return got
        try:
            got = validate_intent(self.runner.extract_intent(raw, prev))
        except Exception:  # noqa: BLE001 - a broken runner must never break search
            got = None
        if got is None:
            return None
        allowed = set(user_nums) | ({str(prev['server_id'])} if prev and prev['server_id'] is not None else set())
        if got['intent'] == 'refine_search':  # spelled-out ordinals ('máy thứ hai') may legitimately become digits
            allowed |= {str(_ORD[w]) for w in q.split() if _ORD.get(w, 0) > 0}
        model_nums = {t for t in norm(got['query']).split() if _dig(t)}
        if 'server_id' in got:
            model_nums.add(str(got['server_id']))
        if (user_nums and not user_nums <= model_nums) or not model_nums <= allowed:
            return None  # model changed or invented an identity number: discard
        utoks = set(q.split())
        if not all(_dig(t) or t in utoks or any(len(t) >= 4 and SequenceMatcher(None, t, u).ratio() >= 0.8 for u in utoks)
                   for t in norm(got['query']).split()):
            return None  # words the user never said (e.g. a copied few-shot example): discard
        got = {k: v for k, v in got.items() if k != 'service' or all(t in utoks for t in norm(v).split())}
        self._cache[key] = got
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return got

    def _research(self, entries, got):
        hard, soft = _clean(norm(got['query']))
        if not hard:
            return got, 'none', []
        scope = entries
        if got['intent'] == 'refine_search' and self._ctx:  # filter inside the confirmed group first
            ids = set(self._ctx['ids'])
            scope = [e for e in entries if e.id in ids] or entries
            kind, items, _ = self._search(scope, hard, soft)
            if kind != 'none':
                return got, kind, items
        kind, items, _ = self._search(entries, hard, soft)
        return got, kind, items
