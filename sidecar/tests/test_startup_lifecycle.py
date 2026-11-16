"""Regression: first-launch & vault lifecycle (SYNTHETIC data only).

Covers: fresh install, existing vault, missing vault, create -> close -> reopen,
demo isolation. Uses temp dirs only; never touches a real vault.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIDECAR_DIR))

import sidecar_server  # noqa: E402  (also puts PersonalVault_MVP on sys.path)
from sidecar_server import SidecarController  # noqa: E402
from personal_vault.core import Vault, VaultError  # noqa: E402

PW = 'Synthetic-Test-Password-1!'
IMPORT_TXT = 'Account: a' + chr(10) + 'Name: b' + chr(10) + 'Pass: c' + chr(10)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class StartupStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.state = root / 'state'
        self.vaults = root / 'vaults'
        self.vaults.mkdir()
        self._ctls: list[SidecarController] = []
        self.addCleanup(self._lock_all)

    def _lock_all(self):
        for c in self._ctls:
            c.lock()

    def ctl(self) -> SidecarController:
        c = SidecarController(state_dir=self.state)
        self._ctls.append(c)
        return c

    def make_personal(self, name='mine.pvault') -> Path:
        p = self.vaults / name
        c = self.ctl()
        c.create(str(p), PW)
        c.lock()
        return p

    # 1. fresh install -------------------------------------------------
    def test_fresh_install_reports_fresh_and_writes_nothing(self):
        st = self.ctl().startup_state()
        self.assertEqual(st['state'], 'fresh')
        self.assertIsNone(st['path'])
        self.assertFalse(st['demo'])
        self.assertFalse(self.state.exists() and any(self.state.iterdir()),
                         'reading startup state must not create files')

    def test_corrupt_pointer_falls_back_to_fresh(self):
        self.state.mkdir()
        (self.state / sidecar_server.STATE_FILE).write_text('{not json', encoding='utf-8')
        self.assertEqual(self.ctl().startup_state()['state'], 'fresh')

    # 2. existing vault ------------------------------------------------
    def test_existing_vault_reports_locked_with_path(self):
        p = self.make_personal()
        st = self.ctl().startup_state()
        self.assertEqual(st['state'], 'locked')
        self.assertEqual(st['path'], str(p))

    def test_create_makes_empty_vault_and_remembers_it(self):
        c = self.ctl()
        p = self.vaults / 'new.pvault'
        res = c.create(str(p), PW)
        self.assertEqual(res['count'], 0)
        st = c.startup_state()
        self.assertEqual((st['state'], st['path'], st['demo']), ('unlocked', str(p), False))

    def test_create_never_overwrites_existing_file(self):
        p = self.make_personal()
        before = sha(p)
        with self.assertRaises(VaultError):
            self.ctl().create(str(p), 'Another-Synthetic-Pass-2!')
        self.assertEqual(sha(p), before)

    def test_failed_unlock_does_not_move_pointer_and_success_does(self):
        a = self.make_personal('a.pvault')
        b = self.vaults / 'b.pvault'
        Vault.create(b, PW).lock()
        c = self.ctl()
        with self.assertRaises(VaultError):
            c.unlock(str(b), 'wrong-synthetic-pass-9')
        self.assertEqual(c.startup_state()['path'], str(a))
        c.unlock(str(b), PW)
        c.lock()
        self.assertEqual(c.startup_state()['path'], str(b))

    # 3. missing vault -------------------------------------------------
    def test_missing_vault_reports_missing_and_never_recreates(self):
        p = self.make_personal()
        p.unlink()
        c = self.ctl()
        st = c.startup_state()
        self.assertEqual((st['state'], st['path']), ('missing', str(p)))
        self.assertFalse(p.exists())
        with self.assertRaises(VaultError):
            c.unlock(str(p), PW)
        self.assertFalse(p.exists(), 'unlock must not create the vault')
        self.assertEqual(list(self.vaults.glob('*.pvault')), [])

    # 5. demo isolation ------------------------------------------------
    def test_demo_is_isolated_from_personal_vault(self):
        p = self.make_personal()
        c = self.ctl()
        c.unlock(str(p), PW)
        c.save_entry({'account': 'Synthetic Mail', 'name': 'u@example.invalid', 'password': 'CANARY_PERSONAL'})
        c.lock()
        vault_before = sha(p)
        pointer = self.state / sidecar_server.STATE_FILE
        pointer_before = pointer.read_bytes()

        c.open_demo()
        st = c.startup_state()
        self.assertEqual((st['state'], st['demo']), ('unlocked', True))
        self.assertNotEqual(Path(st['path']), p)
        self.assertEqual(Path(st['path']).parent, self.state / 'demo')
        self.assertEqual(len(c.get_entries()), 500)
        self.assertNotIn('Synthetic Mail', {e['account'] for e in c.get_entries()})
        c.lock()

        self.assertEqual(sha(p), vault_before, 'personal vault bytes changed')
        self.assertEqual(pointer.read_bytes(), pointer_before, 'demo moved the pointer')
        st = c.startup_state()
        self.assertEqual((st['state'], st['path']), ('locked', str(p)))

    def test_demo_on_fresh_install_leaves_no_pointer(self):
        c = self.ctl()
        c.open_demo()
        c.lock()
        self.assertEqual(c.startup_state()['state'], 'fresh')
        self.assertFalse((self.state / sidecar_server.STATE_FILE).exists())

    def test_reopening_demo_does_not_accumulate_stale_demo_files(self):
        c = self.ctl()
        c.open_demo()
        c.lock()
        c.open_demo()
        c.lock()
        self.assertEqual(len(list((self.state / 'demo').glob('synthetic-demo-*.pvault'))), 1)


class ContractTests(unittest.TestCase):
    """Wrong password, stale IPC after lock, unchanged password, import, demo count."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.c = SidecarController(state_dir=self.root / 'state')
        self.addCleanup(self.c.lock)
        self.path = self.root / 'vaults' / 'mine.pvault'
        self.c.create(str(self.path), PW)

    def add(self, account='Synthetic Mail', name='u@example.invalid', password='CANARY_ORIGINAL', **kw):
        return self.c.save_entry({'account': account, 'name': name, 'password': password, **kw})['id']

    # wrong password ---------------------------------------------------
    def test_wrong_password_rejected_and_stays_locked(self):
        self.c.lock()
        before = sha(self.path)
        with self.assertRaises(VaultError):
            self.c.unlock(str(self.path), 'wrong-synthetic-pass-9')
        self.assertFalse(self.c.startup_state()['state'] == 'unlocked')
        self.assertEqual(sha(self.path), before)
        self.assertEqual(self.c.unlock(str(self.path), PW)['count'], 0)

    def test_missing_vault_with_missing_parent_creates_no_directories(self):
        ghost = self.root / 'moved-away' / 'deep' / 'gone.pvault'
        with self.assertRaises(VaultError):
            self.c.unlock(str(ghost), PW)
        self.assertFalse((self.root / 'moved-away').exists(), 'unlock created directories for a missing vault')

    # lock / stale IPC -------------------------------------------------
    def test_every_data_call_fails_after_lock(self):
        eid = self.add()
        self.c.lock()
        calls = [
            lambda: self.c.get_entries(),
            lambda: self.c.search('synthetic'),
            lambda: self.c.reveal(eid),
            lambda: self.c.save_entry({'account': 'x', 'name': 'y', 'password': 'z'}),
            lambda: self.c.delete_entry(eid),
            lambda: self.c.inspect_import('Account: a\nName: b\nPass: c\n', '.txt'),
            lambda: self.c.confirm_import(),
            lambda: self.c.backup(str(self.root / 'b.pvault')),
        ]
        for i, call in enumerate(calls):
            with self.subTest(call=i), self.assertRaisesRegex(VaultError, 'locked'):
                call()

    # unchanged password -----------------------------------------------
    def test_edit_without_password_keeps_secret(self):
        eid = self.add()
        for pw in (None, ''):
            self.c.save_entry({'id': eid, 'account': 'Synthetic Mail', 'name': 'u@example.invalid',
                               'password': pw, 'description': f'edited {pw!r}'})
            self.assertEqual(self.c.reveal(eid)['password'], 'CANARY_ORIGINAL')
        self.c.save_entry({'id': eid, 'account': 'Synthetic Mail', 'name': 'u@example.invalid', 'description': 'no key'})
        self.assertEqual(self.c.reveal(eid)['password'], 'CANARY_ORIGINAL')

    def test_edit_with_new_password_replaces_secret(self):
        eid = self.add()
        self.c.save_entry({'id': eid, 'account': 'Synthetic Mail', 'name': 'u@example.invalid', 'password': 'CANARY_NEW'})
        self.assertEqual(self.c.reveal(eid)['password'], 'CANARY_NEW')

    def test_list_and_search_never_expose_passwords(self):
        self.add()
        for e in self.c.get_entries() + self.c.search('synthetic')['items']:
            self.assertNotIn('password', e)

    # import -----------------------------------------------------------
    IMPORT_TXT = ('Account: Synthetic Mail\nName: u@example.invalid\nPass: CANARY_DUP\n\n'
                  'Account: Synthetic Wiki\nName: wiki@example.invalid\nPass: CANARY_WIKI_IMPORTED\n'
                  'Aliases: wiki; docs\nURL: etap://10.0.0.15:8000\n')

    def test_import_preview_counts_and_no_secret_on_wire(self):
        self.add()
        pv = self.c.inspect_import(self.IMPORT_TXT, '.txt')
        self.assertEqual((pv['total'], pv['newCount'], pv['duplicateCount'], pv['invalidCount']), (2, 1, 1, 0))
        for r in pv['records']:
            self.assertNotIn('password', r['entry'])
        self.assertEqual(len(self.c.get_entries()), 1, 'preview must not write')

    def test_import_confirm_stores_real_password_not_a_mask(self):
        self.add()
        self.c.inspect_import(self.IMPORT_TXT, '.txt')
        res = self.c.confirm_import()
        self.assertEqual(res['importedCount'], 1)
        wiki = next(e for e in self.c.get_entries() if e['account'] == 'Synthetic Wiki')
        self.assertEqual(self.c.reveal(wiki['id'])['password'], 'CANARY_WIKI_IMPORTED')
        self.assertEqual(wiki['url'], 'etap://10.0.0.15:8000')  # stored as text only
        with self.assertRaises(VaultError):  # pending is consumed
            self.c.confirm_import()

    def test_import_invalid_file_rejected_and_writes_nothing(self):
        before = sha(self.path)
        for text, ext in (('echo hacked\n', '.bat'), ('not a record', '.txt'), ('[]', '.json'), ('a', '.exe')):
            with self.subTest(ext=ext), self.assertRaises(VaultError):
                self.c.inspect_import(text, ext)
        with self.assertRaises(VaultError):
            self.c.confirm_import()
        self.assertEqual(sha(self.path), before)

    def test_failed_preview_discards_previous_pending(self):
        self.c.inspect_import(self.IMPORT_TXT, '.txt')
        with self.assertRaises(VaultError):
            self.c.inspect_import('garbage', '.txt')
        with self.assertRaises(VaultError):
            self.c.confirm_import()

    # idle auto-lock (backend-enforced, independent of the UI) -----------
    def test_idle_timeout_locks_backend_and_blocks_data_calls(self):
        now = [1000.0]
        c = SidecarController(state_dir=self.root / 's2', idle_seconds=300, clock=lambda: now[0])
        self.addCleanup(c.lock)
        c.create(str(self.root / 'vaults' / 'idle.pvault'), PW)
        now[0] += 299
        c.touch()  # activity resets the window
        now[0] += 299
        self.assertEqual(c.get_entries(), [])
        now[0] += 301
        self.assertEqual(c.startup_state()['state'], 'locked')
        with self.assertRaisesRegex(VaultError, 'locked'):
            c.get_entries()

    def test_lock_bumps_session_generation(self):
        g0 = self.c.search('x')['session_generation']
        self.c.lock()
        self.c.unlock(str(self.path), PW)
        self.assertGreater(self.c.search('x')['session_generation'], g0)

    # chatbot over IPC -------------------------------------------------
    def test_chat_search_fail_closed_when_locked_and_never_returns_passwords(self):
        self.add('PSCAD Demo 1', 'pscad1', 'CANARY_CHAT_SECRET_1')
        self.add('PSCAD Demo 2', 'pscad2', 'CANARY_CHAT_SECRET_2')
        res = self.c.chat_search('pscad')
        self.assertTrue(res['entries'])
        self.assertNotIn('CANARY_CHAT_SECRET', json.dumps(res, ensure_ascii=False))
        self.assertEqual(res['session_generation'], self.c.generation)
        self.c.lock()
        with self.assertRaisesRegex(VaultError, 'locked'):
            self.c.chat_search('pscad')

    def test_chat_followup_context_does_not_survive_lock(self):
        self.add('PSCAD Demo 1', 'pscad1', 'p1')
        self.add('PSCAD Demo 2', 'pscad2', 'p2')
        self.add('ETAP Server 2', 'etap2', 'p3')
        self.c.chat_search('pscad')
        before = self.c.chat_search('máy 2')
        self.assertEqual([e['account'] for e in before['entries']], ['PSCAD Demo 2'])
        self.c.lock()
        self.c.unlock(str(self.path), PW)
        after = self.c.chat_search('máy 2')
        self.assertNotIn('PSCAD Demo 2', [e['account'] for e in after['entries']] if after['status'] == 'exact' else [])

    def test_chat_search_is_in_ipc_allowlist(self):
        self.assertIn('chat_search', sidecar_server.ALLOWED_METHODS)

    # demo count -------------------------------------------------------
    def test_demo_has_exactly_500_unique_accounts(self):
        self.c.open_demo()
        entries = self.c.get_entries()
        self.assertEqual(len(entries), 500)
        self.assertEqual(len({(e['account'].lower(), e['name']) for e in entries}), 500)


class SessionLockAndBuildFlagTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.now = [1000.0]
        self.wall = [5000.0]
        self.c = SidecarController(state_dir=Path(self._tmp.name) / 's', idle_seconds=300, clock=lambda: self.now[0])
        self.addCleanup(self.c.lock)
        self.c.poll_session(False, self.wall[0])  # prime the wall-clock baseline
        self.c.open_demo()

    def tick(self, locked=False, dt=1.0):
        self.wall[0] += dt
        self.now[0] += dt
        return self.c.poll_session(locked, self.wall[0])

    def test_windows_session_lock_locks_backend_without_any_ui_call(self):
        self.assertIsNone(self.tick())
        self.assertEqual(self.c.startup_state()['state'], 'unlocked')
        g = self.c.generation
        self.assertEqual(self.tick(locked=True), 'session')
        self.assertGreater(self.c.generation, g)
        self.assertEqual(self.c.startup_state()['state'], 'fresh')  # demo is never remembered; nothing is unlocked
        for call in (self.c.get_entries, lambda: self.c.chat_search('fb'), lambda: self.c.reveal('x')):
            with self.assertRaisesRegex(VaultError, 'locked'):
                call()

    def test_suspend_resume_gap_locks(self):
        self.assertEqual(self.tick(dt=sidecar_server.SUSPEND_GAP_S + 5), 'suspend')
        self.assertEqual(self.c.startup_state()['state'], 'fresh')

    def test_normal_ticks_do_not_lock(self):
        for _ in range(60):
            self.assertIsNone(self.tick())
        self.assertEqual(self.c.startup_state()['state'], 'unlocked')

    def test_idle_expiry_is_proactive_not_lazy(self):
        for _ in range(299):
            self.assertIsNone(self.tick())
        self.assertEqual(self.tick(dt=2.0), 'idle')  # no IPC call was needed to notice
        self.assertIsNone(self.c.vault)

    def test_activity_resets_idle(self):
        for _ in range(250):
            self.tick()
        self.c.touch()
        for _ in range(250):
            self.assertIsNone(self.tick())

    def test_nothing_to_do_when_already_locked(self):
        self.c.lock()
        self.assertIsNone(self.tick(locked=True))

    @unittest.skipUnless(os.name == 'nt', 'Windows only')
    def test_real_detector_reports_unlocked_in_an_interactive_session(self):
        self.assertFalse(sidecar_server.session_locked())  # positive control; the real lock is not triggered by tests

    # -- build flag: Qwen is off in release, whatever the environment says
    def test_qwen_cannot_be_enabled_in_release_even_with_env(self):
        old = os.environ.get('PVAULT_QWEN')
        os.environ['PVAULT_QWEN'] = '1'
        self.addCleanup(lambda: os.environ.pop('PVAULT_QWEN', None) if old is None else os.environ.__setitem__('PVAULT_QWEN', old))
        self.assertFalse(sidecar_server.QWEN_ALLOWED)
        self.assertIsNone(sidecar_server._make_runner())
        c = SidecarController(state_dir=Path(self._tmp.name) / 's2')
        self.assertFalse(c.startup_state().get('qwen', False))

    def test_experimental_flag_is_required_and_env_still_needed(self):
        sidecar_server.QWEN_ALLOWED = True
        self.addCleanup(setattr, sidecar_server, 'QWEN_ALLOWED', False)
        os.environ.pop('PVAULT_QWEN', None)
        self.assertIsNone(sidecar_server._make_runner())
        os.environ['PVAULT_QWEN'] = '1'
        self.addCleanup(os.environ.pop, 'PVAULT_QWEN', None)
        self.assertEqual(type(sidecar_server._make_runner()).__name__, 'QwenRunner')

    def test_experimental_entry_point_flips_only_in_its_own_process(self):
        code = ("import sys; sys.path.insert(0, %r); import sidecar_experimental, sidecar_server; print(sidecar_server.QWEN_ALLOWED)"
                % str(SIDECAR_DIR))
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, 'True')
        self.assertFalse(sidecar_server.QWEN_ALLOWED)


class RealProcessRestartTests(unittest.TestCase):
    """create -> kill the process (app close) -> new process -> unlock."""

    def _spawn(self, env):
        p = subprocess.Popen(
            [sys.executable, str(SIDECAR_DIR / 'sidecar_server.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', env=env,
        )
        def _cleanup():
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdin.close()
            p.stdout.close()
        self.addCleanup(_cleanup)
        self.assertEqual(json.loads(p.stdout.readline())['event'], 'ready')
        return p

    @staticmethod
    def _rpc(p, rid, method, **params):
        p.stdin.write(json.dumps({'id': rid, 'method': method, 'params': params}) + '\n')
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    def test_ipc_allowlist_rejects_private_and_unknown_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'LOCALAPPDATA': tmp, 'HOME': tmp, 'USERPROFILE': tmp}
            p = self._spawn(env)
            for i, m in enumerate(['_require_unlocked', '__class__', '_remember', 'state_dir', 'nope']):
                self.assertIn('error', self._rpc(p, i, m), m)
            self.assertIn('error', self._rpc(p, 99, 'startup_state', bogus=1))  # bad kwargs -> error, no crash
            self.assertEqual(self._rpc(p, 100, 'startup_state')['result']['state'], 'fresh')  # still alive
            p.kill()
            p.wait()

    def test_create_close_reopen_unlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'LOCALAPPDATA': tmp, 'HOME': tmp, 'USERPROFILE': tmp}
            vault = str(Path(tmp) / 'docs' / 'my-vault.pvault')

            p1 = self._spawn(env)
            self.assertEqual(self._rpc(p1, 1, 'startup_state')['result']['state'], 'fresh')
            self.assertTrue(self._rpc(p1, 2, 'create', path=vault, password=PW)['result']['success'])
            self.assertEqual(self._rpc(p1, 3, 'startup_state')['result']['state'], 'unlocked')
            p1.kill()  # what closing the app does
            p1.wait()

            p2 = self._spawn(env)
            st = self._rpc(p2, 1, 'startup_state')['result']
            self.assertEqual((st['state'], st['path']), ('locked', vault))
            self.assertIn('error', self._rpc(p2, 2, 'unlock', path=vault, password='wrong-synthetic-pass-9'))
            ok = self._rpc(p2, 3, 'unlock', path=vault, password=PW)['result']
            self.assertTrue(ok['success'])
            self.assertEqual(ok['count'], 0)
            self.assertEqual(self._rpc(p2, 4, 'startup_state')['result']['state'], 'unlocked')
            p2.kill()
            p2.wait()


if __name__ == '__main__':
    unittest.main()


class QaHookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_hooks_are_off_in_release_and_debug_method_is_not_allowed(self):
        self.assertFalse(sidecar_server.TEST_HOOKS)
        os.environ['PVAULT_TEST_LOCK_FILE'] = str(Path(self._tmp.name) / 'lock')
        self.addCleanup(os.environ.pop, 'PVAULT_TEST_LOCK_FILE', None)
        Path(os.environ['PVAULT_TEST_LOCK_FILE']).write_text('1')
        self.assertFalse(sidecar_server.session_locked())  # file ignored without the QA flag
        self.assertNotIn('debug_activity', sidecar_server.ALLOWED_METHODS)

    def test_lock_file_simulates_a_locked_session_only_with_hooks(self):
        sidecar_server.TEST_HOOKS = True
        self.addCleanup(setattr, sidecar_server, 'TEST_HOOKS', False)
        f = Path(self._tmp.name) / 'lock'
        os.environ['PVAULT_TEST_LOCK_FILE'] = str(f)
        self.addCleanup(os.environ.pop, 'PVAULT_TEST_LOCK_FILE', None)
        self.assertFalse(sidecar_server.session_locked())
        f.write_text('1')
        self.assertTrue(sidecar_server.session_locked())

    def test_activity_log_attributes_every_idle_refresh(self):
        now = [10.0]
        c = SidecarController(state_dir=Path(self._tmp.name) / 's', idle_seconds=300, clock=lambda: now[0])
        self.addCleanup(c.lock)
        c.open_demo()
        now[0] += 5
        c.touch()
        now[0] += 5
        c.get_entries()
        kinds = [k for _, k in c.activity]
        self.assertEqual(kinds[-3:], ['open', 'touch', 'data-call'])
        c.startup_state()
        c.poll_session(False, time.time())
        self.assertEqual([k for _, k in c.activity][-1], 'data-call')  # polls and state reads are NOT activity


class FailClosedAfterEveryLockCause(unittest.TestCase):
    """Every read / reveal / write / export method of the IPC allowlist refuses once the backend is locked, whatever locked it:
    explicit lock, idle expiry, Windows session lock, suspend/resume gap. The native 'copy password' goes through `reveal`, so it is covered too."""
    NON_DATA = {'startup_state', 'is_unlocked', 'touch', 'unlock', 'lock', 'create', 'open_demo', 'default_dir'}  # pre-auth or lock-neutral
    DATA = {'get_entries', 'search', 'chat_search', 'reveal', 'save_entry', 'delete_entry', 'inspect_import', 'confirm_import', 'backup'}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.now, self.wall = [1000.0], [5000.0]
        self.c = SidecarController(state_dir=self.root / 's', idle_seconds=300, clock=lambda: self.now[0])
        self.addCleanup(self.c.lock)
        self.c.poll_session(False, self.wall[0])
        self.c.open_demo()
        self.eid = self.c.get_entries()[0]['id']

    def calls(self):
        return {
            'get_entries': lambda: self.c.get_entries(),
            'search': lambda: self.c.search('synthetic'),
            'chat_search': lambda: self.c.chat_search('etap server 1'),
            'reveal': lambda: self.c.reveal(self.eid),
            'save_entry': lambda: self.c.save_entry({'account': 'x', 'name': 'y', 'password': 'z'}),
            'delete_entry': lambda: self.c.delete_entry(self.eid),
            'inspect_import': lambda: self.c.inspect_import(IMPORT_TXT, '.txt'),
            'confirm_import': lambda: self.c.confirm_import(),
            'backup': lambda: self.c.backup(str(self.root / 'b.pvault')),
        }

    def test_every_allowlisted_method_is_classified(self):
        self.assertEqual(set(sidecar_server.ALLOWED_METHODS), self.NON_DATA | self.DATA,
                         'a new IPC method must be classified here (and fail closed if it touches data)')
        self.assertEqual(set(self.calls()), self.DATA)

    def test_sanity_calls_work_while_unlocked(self):
        self.assertTrue(self.c.get_entries())
        self.assertIn('password', self.c.reveal(self.eid))

    def _assert_all_refuse(self, why):
        self.assertNotEqual(self.c.startup_state()['state'], 'unlocked', why)   # a demo vault has no pointer -> 'fresh', a personal one -> 'locked'
        for name, call in self.calls().items():
            with self.subTest(cause=why, method=name):
                with self.assertRaisesRegex(VaultError, 'locked'):
                    call()
        self.assertEqual(self.c.touch(), {'unlocked': False}, why)       # activity can never reopen a locked vault
        self.assertFalse(self.c.is_unlocked()['unlocked'], why)
        self.assertEqual(self.c.is_unlocked()['count'], 0, why)

    def test_after_explicit_lock(self):
        self.c.lock()
        self._assert_all_refuse('explicit lock')

    def test_after_idle_expiry(self):
        self.now[0] += 301
        self.c.poll_session(False, self.wall[0])
        self._assert_all_refuse('idle expiry')

    def test_after_windows_session_lock(self):
        self.wall[0] += 1
        self.now[0] += 1
        self.assertEqual(self.c.poll_session(True, self.wall[0]), 'session')
        self._assert_all_refuse('session lock')

    def test_after_suspend_resume_gap(self):
        self.wall[0] += 3600
        self.now[0] += 1
        self.assertEqual(self.c.poll_session(False, self.wall[0]), 'suspend')
        self._assert_all_refuse('suspend/resume')

    def test_data_call_after_idle_without_watcher_is_refused_lazily(self):
        self.now[0] += 301      # the watcher thread has not ticked: each call still checks expiry itself
        for name, call in self.calls().items():
            with self.subTest(method=name), self.assertRaisesRegex(VaultError, 'locked'):
                call()
            self.c.open_demo() if self.c.startup_state()['state'] != 'unlocked' else None
            self.now[0] += 301


class BackgroundPollsDoNotExtendIdle(unittest.TestCase):
    """The UI polls startup_state every 3 s (main window) and every 2 s (Quick Access). That must never count as user activity."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.now, self.wall = [1000.0], [5000.0]
        self.c = SidecarController(state_dir=Path(self._tmp.name) / 's', idle_seconds=300, clock=lambda: self.now[0])
        self.addCleanup(self.c.lock)
        self.c.poll_session(False, self.wall[0])
        self.c.open_demo()

    def run_polls(self, call, every=2.0, total=299.0):
        t = 0.0
        while t < total:
            self.now[0] += every
            self.wall[0] += every
            t += every
            call()
            self.c.poll_session(False, self.wall[0])

    def test_state_polls_alone_let_the_vault_lock_on_schedule(self):
        for name, call in (('startup_state', lambda: self.c.startup_state()), ('is_unlocked', lambda: self.c.is_unlocked())):
            with self.subTest(poll=name):
                self.setUp() if self.c.vault is None else None
                self.run_polls(call, every=2.0, total=290.0)
                self.assertIsNotNone(self.c.vault, 'locked early')
                self.now[0] += 20
                self.wall[0] += 20
                call()
                self.assertIsNone(self.c.vault, f'{name} polling extended the idle window')
                self.assertEqual({k for _, k in self.c.activity} - {'open'}, set(), f'{name} polling was recorded as activity')

    def test_only_touch_and_data_calls_count_as_activity(self):
        self.now[0] += 200
        self.c.touch()
        self.assertIn('touch', {k for _, k in self.c.activity})
        self.now[0] += 200
        self.assertIsNotNone(self.c.vault)         # 200 s since the touch: still open although 400 s since unlock
        self.now[0] += 101
        self.c.poll_session(False, self.wall[0] + 301)
        self.assertIsNone(self.c.vault)

