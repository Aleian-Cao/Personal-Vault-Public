"""Search reliability regression (SYNTHETIC only): zero wrong-account on known failure classes.

Sources of cases:
  * E06-17 "mật khẩu wifi nhà tôi" (the one wrong-account of the 138-query eval; gold none)
  * evals/fixtures/redteam_confirmed.json: 34 wrong-account cases found by a blind red team and confirmed by two judges
Scoring semantics are the eval's: gold none -> no entry may be shown; gold entry -> first entry must be the gold and a
status 'exact' may only carry exactly the gold; gold ambiguous -> never 'exact', never an entry outside the allowed set.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sidecar'))

from chat_pipeline import ChatPipeline  # noqa: E402
from personal_vault.core import norm as _norm  # noqa: E402

_spec = importlib.util.spec_from_file_location('qwen_eval', ROOT / 'evals' / 'qwen_eval.py')
_ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ev)
ENTRIES = _ev.build_entries()
REDTEAM = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_confirmed.json').read_text(encoding='utf-8'))['cases']


def run(query, prev=()):
    p = ChatPipeline(None)
    for q in prev:
        p.answer(q, ENTRIES)
    return p.answer(query, ENTRIES)


def accounts(res):
    return [e['account'] for e in res['entries']]


class KnownWrongAccount(unittest.TestCase):
    def test_e06_17_wifi_nha_toi_is_not_the_meeting_room_wifi(self):
        res = run('mật khẩu wifi nhà tôi')
        self.assertEqual(res['entries'], [], res['message'])
        self.assertEqual(res['status'], 'none')

    def test_house_qualifier_unaccented_mid_sentence(self):
        self.assertEqual(run('mat khau wifi nha toi')['entries'], [])

    def test_house_qualifier_never_produces_exact(self):
        for q in ('zalo nhà', 'vpn nhà 3', 'gmail nhà', 'vpn nhà'):
            with self.subTest(q=q):
                res = run(q)
                self.assertEqual(res['entries'], [], q)


class RedTeamConfirmed(unittest.TestCase):
    def test_every_confirmed_case_is_fail_safe(self):
        self.assertGreaterEqual(len(REDTEAM), 30)
        for c in REDTEAM:
            with self.subTest(id=c['id'], query=c['query'], prev=c['prev']):
                res = run(c['query'], c['prev'])
                got, g = accounts(res), c['gold']
                if g['type'] == 'none':
                    self.assertEqual(got, [], f"{res['status']} {got}")
                elif g['type'] == 'entry':
                    self.assertTrue(got and got[0] == g['account'], f"{res['status']} {got}")
                    if res['status'] == 'exact':
                        self.assertEqual(got, [g['account']])
                else:
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                    if g['accounts']:
                        self.assertTrue(set(got) <= set(g['accounts']), f"{got}")


class FollowUpFailSafe(unittest.TestCase):
    def test_two_references_are_a_choice_not_an_exact(self):
        for prev, q in (('etap server', 'máy 5 và 1'), ('pscad', 'cái thứ 2 và 4'), ('etap', 'cái đầu và cái cuối')):
            with self.subTest(q=q):
                res = run(q, [prev])
                self.assertNotEqual(res['status'], 'exact')
                self.assertGreaterEqual(len(res['entries']), 2)

    def test_year_is_not_the_ordinal_five(self):
        for q in ('năm 2024', 'năm nay'):
            self.assertEqual(run(q, ['pscad'])['entries'], [], q)

    def test_pronoun_never_confirms_an_unconfirmed_suggestion(self):
        res = run('nó', ['facebok shop'])
        self.assertNotEqual(res['status'], 'exact')

    def test_bare_digit_after_a_list_is_position_vs_identity_so_ask(self):
        res = run('5', ['etap'])  # position 5 is ETAP Server 51, identity 5 is ETAP Server 5
        self.assertNotEqual(res['status'], 'exact')
        self.assertTrue({'ETAP Server 5', 'ETAP Server 51'} <= set(accounts(res)))


class FuzzyFailSafe(unittest.TestCase):
    def test_shared_suffix_does_not_swamp_a_different_service(self):
        for q in ('etap demo 3', 'ftp demo 3', 'rdp demo 3', 'nas demo 3'):
            self.assertEqual(run(q)['entries'], [], q)

    def test_single_letter_identity_slots_are_exact(self):
        self.assertEqual(run('dev box d')['entries'], [])

    def test_negation_excludes_instead_of_selecting(self):
        shop = run('facebook trừ shop')
        self.assertNotIn('Facebook — Demo Shop', accounts(shop))
        self.assertEqual(accounts(shop)[:1], ['Facebook — Demo Personal'])
        self.assertEqual(run('gmail trừ công ty')['entries'], [])
        self.assertNotIn('ETAP Server 5', accounts(run('etap server trừ 5')))


class PositiveControls(unittest.TestCase):
    """The fixes must not cost the answers that were right."""

    def test_alias_and_natural_sentence_still_exact(self):
        self.assertEqual(accounts(run('cho tôi tài khoản fb chính')), ['Facebook — Demo Personal'])
        self.assertEqual(run('cho tôi tài khoản fb chính')['status'], 'exact')

    def test_numeric_identity_still_strict_and_exact(self):
        res = run('etap server 15')
        self.assertEqual((res['status'], accounts(res)), ('exact', ['ETAP Server 15']))
        self.assertEqual(accounts(run('server15')), ['ETAP Server 15'])

    def test_typos_still_give_the_right_suggestion(self):
        self.assertEqual(accounts(run('facebok shop'))[:1], ['Facebook — Demo Shop'])
        self.assertEqual(accounts(run('etap sever 15')), ['ETAP Server 15'])
        self.assertNotEqual(run('etap sever 15')['status'], 'exact')

    def test_letter_slot_with_the_letter_is_exact(self):
        res = run('dev box a')
        self.assertEqual(accounts(res), ['Dev Box A'])
        self.assertEqual(res['status'], 'exact')

    def test_company_qualifier_present_in_the_entry_still_matches(self):
        self.assertEqual(accounts(run('email công ty'))[:1], ['Gmail Công ty'])

    def test_polite_final_particle_is_still_filler(self):
        self.assertEqual(accounts(run('cho mình xem wifi phòng họp tầng 3 nha')), ['Wifi Phòng họp Tầng 3'])

    def test_followups_still_work(self):
        self.assertEqual(accounts(run('máy thứ hai', ['pscad'])), ['PSCAD Demo 2'])
        self.assertEqual(accounts(run('máy 5', ['etap'])), ['ETAP Server 5'])
        self.assertEqual(run('máy 5', ['etap'])['status'], 'exact')
        self.assertEqual(len(accounts(run('cái cuối', ['etap']))), 1)
        self.assertEqual(accounts(run('cái thứ hai', ['pscad'])), ['PSCAD Demo 2'])


if __name__ == '__main__':
    unittest.main()


REDTEAM2 = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_r2_confirmed.json').read_text(encoding='utf-8'))['cases']


class RedTeamRound2(unittest.TestCase):
    def test_every_confirmed_round2_case_is_fail_safe(self):
        self.assertGreaterEqual(len(REDTEAM2), 20)
        for c in REDTEAM2:
            with self.subTest(id=c['id'], query=c['query'], prev=c['prev']):
                res = run(c['query'], c['prev'])
                got, g = accounts(res), c['gold']
                if g['type'] == 'none':
                    self.assertEqual(got, [], f"{res['status']} {got}")
                elif g['type'] == 'entry':
                    self.assertTrue(got and got[0] == g['account'], f"{res['status']} {got}")
                    if res['status'] == 'exact':
                        self.assertEqual(got, [g['account']])
                else:
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                    if g['accounts']:
                        self.assertTrue(set(got) <= set(g['accounts']), f"{got}")

    def test_no_unicode_digit_can_crash_the_pipeline(self):
        import sys as _s
        chars = [chr(i) for i in range(0x110000) if chr(i).isdigit() and not chr(i).isdecimal()]
        self.assertGreater(len(chars), 50)
        import unicodedata
        for ch in chars[::7] + ['❶', '፩', '²', '①']:
            n = _norm(ch)
            real = n.isascii() and n.isdecimal()  # '²', '⑷', '⒉' really are numbers once normalised; '❶', '፩' are not
            for q, prev in ((f'etap {ch}', ()), (ch, ('etap',)), (f'máy {ch}', ('etap',)), (f'thứ {ch}', ('pscad',))):
                with self.subTest(q=q):
                    res = run(q, prev)  # must not raise
                    if not real:
                        self.assertNotEqual(res['status'], 'exact')

    def test_long_query_is_never_truncated_into_a_different_identity(self):
        padded = (' ' * 394) + 'etap 15'
        res = run(padded)
        self.assertEqual(accounts(res), ['ETAP Server 15'])
        long_filler = 'xin vui lòng giúp tôi ' * 20 + 'etap server 15'
        res = run(long_filler)
        self.assertNotIn(res['status'], ('exact',) if accounts(res) != ['ETAP Server 15'] else ())
        self.assertTrue(accounts(res) in ([], ['ETAP Server 15']), accounts(res))

    def test_letter_glued_to_a_number_is_part_of_the_identity(self):
        for q in ('etap 15a', 'ETAP 15-A', 'vpn a3', 'sao chép mk etap server 5a'):
            self.assertEqual(run(q)['entries'], [], q)

    def test_accented_particle_a_is_not_the_identity_a(self):
        self.assertNotEqual(run('dev box ạ')['status'], 'exact')
        self.assertEqual(run('dev box a')['status'], 'exact')

    def test_person_names_after_a_title_are_not_ordinals(self):
        for q in ('cái của anh Ba', 'máy của em Hai', 'cái của anh Năm', 'cái của anh Sáu'):
            self.assertEqual(run(q, ['pscad'])['entries'], [], q)

    def test_position_word_is_position_even_with_may(self):
        self.assertEqual(accounts(run('máy thứ nhất', ['etap'])), ['ETAP Server 15'])
        res = run('máy 11 và cái đầu', ['etap'])
        self.assertEqual(set(accounts(res)), {'ETAP Server 11', 'ETAP Server 15'})
        self.assertEqual(accounts(run('thứ 3', ['etap'])), ['ETAP Server 5'])

    def test_decimal_or_partly_invalid_reference_is_not_answered_partially(self):
        self.assertEqual(run('máy 0.5', ['etap'])['entries'], [])


REDTEAM3 = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_r3_confirmed.json').read_text(encoding='utf-8'))['cases']


class RedTeamRound3(unittest.TestCase):
    """Wrong-account-free (an abstain is acceptable): the eval's own `wrong` semantics."""

    def test_every_confirmed_round3_case_is_wrong_account_free(self):
        self.assertGreaterEqual(len(REDTEAM3), 25)
        for c in REDTEAM3:
            with self.subTest(id=c['id'], query=c['query'], prev=c['prev']):
                res = run(c['query'], c['prev'])
                got, g = accounts(res), c['gold']
                if g['type'] == 'none':
                    self.assertEqual(got, [], f"{res['status']} {got}")
                elif g['type'] == 'entry':
                    self.assertTrue(not got or got[0] == g['account'], f"{res['status']} {got}")
                    if res['status'] == 'exact':
                        self.assertEqual(got, [g['account']])
                else:
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                    if g['accounts']:
                        self.assertTrue(set(got) <= set(g['accounts']), f"{got}")

    def test_follow_up_lists_inherit_the_machine_marker(self):
        for q in ('máy 5, 1', 'máy 1 5', 'máy 1-5', 'máy số 5 và số 1'):
            res = run(q, ['etap'])
            self.assertEqual(set(accounts(res)), {'ETAP Server 1', 'ETAP Server 5'}, q)
            self.assertEqual(res['status'], 'ambiguous')

    def test_letter_identities_listed_or_excluded(self):
        for q in ('dev box a, b', 'dev box a & b', 'dev box a/b', 'dev box a b'):
            self.assertNotEqual(run(q)['status'], 'exact', q)
        for q in ('dev box trừ a', 'dev box không phải a', 'dev box ngoài a ra', 'dev box trừ A'):
            self.assertEqual(accounts(run(q)), ['Dev Box B'], q)
        self.assertEqual(accounts(run('dev box không phải a mà b')), ['Dev Box B'])

    def test_particle_a_with_accent_never_selects_the_letter_a_in_follow_ups(self):
        for q in ('máy ạ', 'mật khẩu máy ạ'):
            self.assertNotEqual(run(q, ['dev'])['status'], 'exact', q)

    def test_tone_marks_that_conflict_are_different_words(self):
        for q in ('hộp thư', 'phòng 15'):
            self.assertEqual(run(q)['entries'], [], q)
        self.assertEqual(accounts(run('wifi phòng họp tầng 3')), ['Wifi Phòng họp Tầng 3'])
        self.assertEqual(accounts(run('wifi phong hop tang 3')), ['Wifi Phòng họp Tầng 3'])  # no accents at all is still fine

    def test_ordinal_homographs_need_their_accent_or_context(self):
        for q in ('thứ tự', 'kết quả năm nay', 'mục sau cùng'):
            self.assertNotEqual(run(q, ['demo'])['status'], 'exact', q)
        res = run('máy đầu tiên', ['etap'])  # machine 1 or the first result: the user must choose
        self.assertEqual(res['status'], 'ambiguous')
        self.assertEqual(set(accounts(res)), {'ETAP Server 15', 'ETAP Server 1'})


REDTEAM4 = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_r4_confirmed.json').read_text(encoding='utf-8'))['cases']


class RedTeamRound4(unittest.TestCase):
    def test_every_confirmed_round4_case_is_wrong_account_free(self):
        self.assertGreaterEqual(len(REDTEAM4), 18)
        for c in REDTEAM4:
            with self.subTest(id=c['id'], query=c['query'], prev=c['prev']):
                res = run(c['query'], c['prev'])
                got, g = accounts(res), c['gold']
                if g['type'] == 'none':
                    self.assertEqual(got, [], f"{res['status']} {got}")
                elif g['type'] == 'entry':
                    self.assertTrue(not got or got[0] == g['account'], f"{res['status']} {got}")
                    if res['status'] == 'exact':
                        self.assertEqual(got, [g['account']])
                else:
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                    if g['accounts']:
                        self.assertTrue(set(got) <= set(g['accounts']), f"{got}")

    def test_invisible_format_characters_do_not_split_numbers(self):
        self.assertEqual(accounts(run('ETAP Server 1\u200b1')), ['ETAP Server 11'])
        self.assertEqual(accounts(run('máy 1\u200b5', ['etap server'])), ['ETAP Server 15'])

    def test_decomposed_accent_is_the_same_particle(self):
        self.assertNotEqual(run('dev box a\u0323')['status'], 'exact')
        self.assertNotEqual(run('máy a\u0323', ['dev box'])['status'], 'exact')

    def test_filler_words_do_not_cause_accent_conflicts(self):
        self.assertIn('ETAP Server 15', accounts(run('mở etap')))
        self.assertEqual(accounts(run('mở etap server 15')), ['ETAP Server 15'])

    def test_machine_reference_without_that_machine_is_none(self):
        for q in ('máy hai', 'máy bốn', 'máy cuối'):
            self.assertEqual(run(q, ['etap'])['entries'], [], q)

    def test_names_that_fold_to_number_words_are_names(self):
        for q in ('máy Hải', 'máy Nhật', 'máy bay', 'mật khẩu máy đâu', 'máy hai tư'):
            self.assertEqual(run(q, ['pscad'])['entries'], [], q)

    def test_house_word_in_follow_up(self):
        for q in ('số nhà 3', 'nhà máy 3'):
            self.assertEqual(run(q, ['pscad'])['entries'], [], q)

    def test_possessive_between_machine_and_number_is_transparent(self):
        self.assertEqual(accounts(run('máy của tôi số 5', ['etap'])), ['ETAP Server 5'])

    def test_bare_number_without_context_reaches_fresh_search(self):
        self.assertEqual(accounts(run('tài khoản 12')), ['Synthetic Account 12'])

    def test_exclusion_needs_all_excluded_words(self):
        self.assertEqual(accounts(run('dev server trừ box a')), ['Dev Box B'])
        self.assertNotIn('ETAP Server 15', accounts(run('etap trừ mô phỏng')))


class ExactGate(unittest.TestCase):
    """Structural rule: 'exact' needs a unique identity AND no dropped word that could be content.
    (Cases HB-392 / HB-563 come from the first run of the blind held-out and are regression-only from now on.)"""

    def test_bare_number_after_a_list_is_position_or_identity_so_ask(self):
        for q in ('số năm ạ', 'số 5', 'số năm'):
            res = run(q, ['etap'])
            self.assertNotEqual(res['status'], 'exact', q)
            self.assertTrue({'ETAP Server 5', 'ETAP Server 51'} <= set(accounts(res)), q)

    def test_machine_number_stays_an_identity(self):
        self.assertEqual(accounts(run('máy số năm', ['etap'])), ['ETAP Server 5'])
        self.assertEqual(run('máy số năm', ['etap'])['status'], 'exact')

    def test_code_like_syntax_is_not_a_question(self):
        for q in ('{{7*7}}', '${jndi:ldap://x}', '<script>alert(1)</script>', 'etap `15`', '%(x)s'):
            self.assertEqual(run(q)['entries'], [], q)

    def test_dropped_word_that_is_vault_content_caps_exact_at_suggestion(self):
        # 'mô' appears in the vault (ETAP Server 15: "mô phỏng"), so a dropped 'mở' may be that word
        res = run('mở etap 15')
        self.assertEqual(accounts(res), ['ETAP Server 15'])
        self.assertNotEqual(res['status'], 'exact')
        self.assertEqual(run('etap 15')['status'], 'exact')

    def test_pure_function_words_do_not_cap_exact(self):
        for q in ('cho tôi tài khoản fb chính', 'vui lòng cho tôi mật khẩu etap server 15', 'sao chép mật khẩu etap 15 giúp tôi'):
            self.assertEqual(run(q)['status'], 'exact', q)

    def test_unaccented_particle_not_in_vault_does_not_cap_exact(self):
        self.assertEqual(run('xem etap server 15 nhe')['status'], 'exact')


REDTEAM6 = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_r6_confirmed.json').read_text(encoding='utf-8'))['cases']


class RedTeamRound6(unittest.TestCase):
    def test_every_confirmed_round6_case_is_wrong_account_free(self):
        self.assertGreaterEqual(len(REDTEAM6), 10)
        for c in REDTEAM6:
            with self.subTest(id=c['id'], query=c['query'], prev=c['prev']):
                res = run(c['query'], c['prev'])
                got, g = accounts(res), c['gold']
                if g['type'] == 'none':
                    # uncertain => at most a suggestion the user must confirm; only a confident (exact) answer is wrong here
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                elif g['type'] == 'entry':
                    self.assertTrue(not got or got[0] == g['account'], f"{res['status']} {got}")
                else:
                    self.assertNotEqual(res['status'], 'exact', f"{got}")
                    if g['accounts']:
                        self.assertTrue(set(got) <= set(g['accounts']), f"{got}")

    def test_exact_also_requires_no_accent_conflict(self):
        self.assertEqual(run('fb chính')['status'], 'exact')
        self.assertEqual(run('fb chinh')['status'], 'exact')            # accent-free typing stays compatible
        self.assertNotEqual(run('fb chỉnh')['status'], 'exact')          # a different accented word is a conflict
        self.assertNotEqual(run('wifi phòng họp tầng 3')['status'], 'none')
        self.assertNotEqual(run('wifi phỏng họp tầng 3')['status'], 'exact')

    def test_follow_up_group_is_not_truncated(self):
        self.assertEqual(accounts(run('máy 120', ['synthetic account'])), ['Synthetic Account 120'])

    def test_reference_into_a_single_result_is_not_a_confirmation(self):
        for prev, q in (('etap server 15', '1'), ('pscad demo 2', 'mk 1'), ('etap 5', 'số 1'), ('zalo', '1')):
            self.assertNotEqual(run(q, [prev])['status'], 'exact', (prev, q))
        self.assertEqual(run('nó', ['etap server 15'])['status'], 'exact')  # a pronoun still refers to the confirmed entry

    def test_capitalised_word_is_a_name_not_a_filler(self):
        for q in ('zalo của anh Minh', 'zalo cho em Hoa', 'gmail của chị Lan'):
            self.assertNotEqual(run(q)['status'], 'exact', q)
        self.assertEqual(run('cho tôi tài khoản fb chính')['status'], 'exact')
        self.assertEqual(run('Cho tôi mật khẩu Zalo Demo')['status'], 'exact')  # sentence-initial capital is not a name

    def test_exclusion_lists_and_machine_word(self):
        for q, excluded in (('etap trừ 1 và 5', {'ETAP Server 1', 'ETAP Server 5'}), ('etap trừ máy 1', {'ETAP Server 1'}),
                            ('etap ngoại trừ 5', {'ETAP Server 5'}), ('etap server trừ 5 và 1', {'ETAP Server 1', 'ETAP Server 5'}),
                            ('etap trừ máy 5', {'ETAP Server 5'})):
            got = set(accounts(run(q)))
            self.assertTrue(got, q)
            self.assertFalse(got & excluded, (q, got))
        self.assertEqual(run('facebook trừ shop và personal')['entries'], [])

    def test_plural_may_is_not_machine(self):
        self.assertNotEqual(run('mấy cái đầu', ['etap server'])['status'], 'exact')


class InvariantSweep(unittest.TestCase):
    """Structural invariants over EVERY fixture query (held-out v2, red-team 1-6, original eval, generated red-team): they do not depend on gold labels.
      I1  a secret action (suggested_action) exists only for ONE entry with status exact  -> fuzzy / uncertain / ambiguous never trigger a secret operation
      I2  status exact carries exactly one entry
      I3  no stored password value appears anywhere in the answer
      I4  exact for a fresh (no-context) query: that entry's own account/name/alias is literally in the query (a fuzzy or semantic hit can never be exact)
    """
    @classmethod
    def setUpClass(cls):
        import re
        sys.path.insert(0, str(ROOT / 'evals'))
        spec = importlib.util.spec_from_file_location('search_eval_inv', ROOT / 'evals' / 'search_eval.py')
        se = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(se)
        cls.cases = []
        for f in ('heldout_blind_v2', 'redteam_confirmed', 'redteam_r2_confirmed', 'redteam_r3_confirmed', 'redteam_r4_confirmed', 'redteam_r6_confirmed'):
            for c in json.loads((ROOT / 'evals' / 'fixtures' / f'{f}.json').read_text(encoding='utf-8'))['cases']:
                cls.cases.append((c['query'], c.get('prev', [])))
        cls.cases += [(q['query'], q.get('prev', [])) for q in _ev.FIX['queries']]
        cls.cases += [(q['query'], q.get('prev', [])) for q in se.redteam_queries(ENTRIES)]
        cls.secrets = {str(e.password) for e in ENTRIES if getattr(e, 'password', None) and len(str(e.password)) >= 6}
        cls.re = re

    def _toks(self, s):
        return _norm(self.re.sub(r'[​-‏⁠﻿]', '', s)).split()

    def test_invariants_hold_for_every_query(self):
        self.assertGreaterEqual(len(self.cases), 1000)
        bad = []
        for q, prev in self.cases:
            res = run(q, prev)
            ents, st, act = res['entries'], res['status'], res.get('suggested_action')
            if act and not (st == 'exact' and len(ents) == 1):
                bad.append(('I1', q, prev, st))
            if st == 'exact' and len(ents) != 1:
                bad.append(('I2', q, prev, st))
            if any(w in json.dumps(res, ensure_ascii=False) for w in self.secrets):
                bad.append(('I3', q, prev, st))
            if st == 'exact' and len(ents) == 1 and not prev:
                qt = self._toks(self.re.sub(r'không phải .*? mà ', '', q))   # "dev box không phải a mà b" -> "dev box b"
                e = ents[0]
                ids = [e.get('account', ''), e.get('name', '')] + list(e.get('aliases', []) or [])
                if not any((t := self._toks(i)) and any(qt[k:k + len(t)] == t for k in range(len(qt) - len(t) + 1)) for i in ids):
                    bad.append(('I4', q, prev, e.get('account')))
        self.assertEqual(bad, [], bad[:10])


class RedTeamRound7(unittest.TestCase):
    """Round 7 (red team of the round-6 patch) + held-out v3 first run: exact + a secret action must only come from a reference the user
    really made, to an entry the user could see. Serious classes are fixed; the exclusion-list class is a documented residual (fail-safe only)."""

    def _not_confident(self, q, prev):
        res = run(q, prev)
        self.assertNotEqual(res['status'], 'exact', (q, prev, accounts(res)))
        self.assertIsNone(res['suggested_action'], (q, prev))

    def test_name_after_possessive_is_not_a_machine_number(self):
        for q in ('copy mật khẩu máy của Ba', 'mật khẩu máy của Sáu', 'copy máy của Tư'):
            with self.subTest(q=q):
                self._not_confident(q, ['pscad demo'])

    def test_ordinal_plus_pronoun_never_confirms_a_single_unconfirmed_suggestion(self):
        for q in ('cái thứ nhất copy mật khẩu của nó', 'thứ nhất của nó', 'cái đầu tiên, copy nó'):
            with self.subTest(q=q):
                self._not_confident(q, ['pscad3'])
        self.assertEqual(run('nó', ['etap server 15'])['status'], 'exact')  # after a CONFIRMED entry a pronoun still works

    def test_position_reference_only_reaches_displayed_entries(self):
        for q in ('mật khẩu cái cuối', 'cái cuối cùng', 'cái thứ 50', 'thứ 11'):
            with self.subTest(q=q):
                self._not_confident(q, ['synthetic account'])    # 488 entries, 10 shown
        self.assertEqual(run('cái thứ 3', ['synthetic account'])['status'], 'exact')    # inside the displayed list: explicit position
        self.assertEqual(accounts(run('máy 120', ['synthetic account'])), ['Synthetic Account 120'])  # identity number stays reachable
        self.assertEqual(run('cái cuối', ['etap server'])['status'], 'exact')            # a fully displayed group still has a last item

    def test_unmarked_number_that_matches_only_a_position_is_not_exact(self):
        for q in ('số 2', 'số 3'):
            with self.subTest(q=q):
                res = run(q, ['etap'])
                self.assertNotEqual(res['status'], 'exact', (q, accounts(res)))
                self.assertIsNone(res['suggested_action'])
                self.assertTrue(res['entries'], q)               # still offered as a choice, the user confirms
        for q in ('thứ 2', 'mục 2', 'dòng 2'):
            self.assertEqual(run(q, ['etap'])['status'], 'exact', q)   # explicit position markers keep working
        self.assertEqual(run('máy 5', ['etap'])['status'], 'exact')

    def test_exclusion_lists_are_fail_safe_even_when_the_separator_is_not_understood(self):
        cases = json.loads((ROOT / 'evals' / 'fixtures' / 'redteam_r7_confirmed.json').read_text(encoding='utf-8'))['cases']
        self.assertGreaterEqual(len(cases), 13)
        for c in cases:
            with self.subTest(q=c['query']):
                self._not_confident(c['query'], c['prev'])

