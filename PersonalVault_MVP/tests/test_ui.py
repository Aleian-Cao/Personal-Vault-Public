import os
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from personal_vault.app import App, IDLE_TIMEOUT_S, SUSPEND_GAP_S
from personal_vault.core import Vault, default_vault_dir, is_inside_app_dir, synthetic_entries


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Requires desktop display')
class UiSmoke(unittest.TestCase):
    def test_unlock_search_select_reveal_lock(self):
        with tempfile.TemporaryDirectory() as t:
            root = tk.Tk()
            self.addCleanup(root.destroy)
            app = App(root, session_locked_fn=lambda: False)
            v = Vault.create(Path(t) / 'demo.pvault', 'Synthetic-Only-123!')
            v.replace(synthetic_entries())
            app.attach(v)
            root.update()
            app.query.set('fb chinh')
            app.run_search()
            root.update()
            self.assertEqual(len(app.tree.get_children()), 1)
            app.tree.selection_set(app.tree.get_children()[0])
            root.update()
            app.select()
            self.assertEqual(app.password.get(), '••••••••')
            app.reveal()
            self.assertEqual(app.password.get(), 'CANARY_DEMO_FB')
            app.lock()
            root.update()
            self.assertFalse(app.tree.get_children())
            self.assertEqual(app.password.get(), '••••••••')
            self.assertIsNone(app.vault)
            self.assertEqual(app.query.get(), '')

    def test_idle_autolock(self):
        with tempfile.TemporaryDirectory() as t:
            root = tk.Tk()
            self.addCleanup(root.destroy)
            app = App(root, session_locked_fn=lambda: False)
            v = Vault.create(Path(t) / 'idle.pvault', 'Synthetic-Only-123!')
            app.attach(v)
            app.last = time.monotonic() - IDLE_TIMEOUT_S - 1
            app.tick()
            self.assertIsNone(app.vault)

    def test_windows_session_lock_autolock(self):
        with tempfile.TemporaryDirectory() as t:
            root = tk.Tk()
            self.addCleanup(root.destroy)
            locked_state = {'locked': False}
            app = App(root, session_locked_fn=lambda: locked_state['locked'])
            v = Vault.create(Path(t) / 'sess.pvault', 'Synthetic-Only-123!')
            app.attach(v)
            locked_state['locked'] = True
            app.tick()
            self.assertIsNone(app.vault)

    def test_suspend_gap_autolock(self):
        with tempfile.TemporaryDirectory() as t:
            root = tk.Tk()
            self.addCleanup(root.destroy)
            app = App(root, session_locked_fn=lambda: False)
            v = Vault.create(Path(t) / 'susp.pvault', 'Synthetic-Only-123!')
            app.attach(v)
            app._last_tick = time.monotonic() - SUSPEND_GAP_S - 1
            app.tick()
            self.assertIsNone(app.vault)

    def test_clipboard_copy_and_lock_clears(self):
        with tempfile.TemporaryDirectory() as t:
            root = tk.Tk()
            self.addCleanup(root.destroy)
            app = App(root, session_locked_fn=lambda: False)
            v = Vault.create(Path(t) / 'clip.pvault', 'Synthetic-Only-123!')
            v.replace(synthetic_entries(5))
            app.attach(v)
            first_id = app.tree.get_children()[0]
            app.tree.selection_set(first_id)
            app.select()
            with mock.patch('personal_vault.app.messagebox.askyesno', return_value=True):
                app.copy('password')
            self.assertEqual(root.clipboard_get(), 'CANARY_DEMO_FB')
            app.lock()
            self.assertIsNone(app.clip)

    def test_default_vault_dir_outside_app_dir(self):
        self.assertFalse(is_inside_app_dir(default_vault_dir()))
