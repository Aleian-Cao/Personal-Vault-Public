import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from personal_vault.core import (
    Entry,
    Vault,
    VaultError,
    inspect_import,
    parse_import,
    synthetic_entries,
)


class ConcurrencyAndLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "concurrent.pvault"
        self.pw = "Synthetic-Master-Only-123!"

    def test_concurrent_open_blocked_until_lock_released(self):
        v1 = Vault.create(self.path, self.pw)
        try:
            with self.assertRaises(VaultError):
                Vault.open(self.path, self.pw)
        finally:
            v1.lock()
        v2 = Vault.open(self.path, self.pw)
        v2.lock()

    def test_lock_clears_sensitive_state_and_releases_lockfile(self):
        v = Vault.create(self.path, self.pw)
        v.replace([Entry.new("Demo", "user", "CANARY_LOCK_PW")])
        v.lock()
        self.assertIsNone(v._key)
        self.assertEqual(v._entries, [])
        self.assertEqual(v._salt, b"")
        # Re-open must succeed after lock()
        v2 = Vault.open(self.path, self.pw)
        self.assertEqual(len(v2.entries), 1)
        v2.lock()

    def test_external_modification_refuses_overwrite(self):
        v = Vault.create(self.path, self.pw)
        try:
            # Simulate external modification of the vault file on disk
            raw = bytearray(self.path.read_bytes())
            raw[-1] ^= 0xFF
            self.path.write_bytes(bytes(raw))
            with self.assertRaises(VaultError):
                v.replace([Entry.new("Demo", "user", "CANARY_EXT_PW")])
            self.assertEqual(self.path.read_bytes(), bytes(raw))
        finally:
            v.lock()


class TempAndCorruptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "vault.pvault"
        self.pw = "Synthetic-Master-Only-123!"

    def test_no_leftover_temp_files_after_operations(self):
        v = Vault.create(self.path, self.pw)
        v.replace(synthetic_entries(10))
        b = self.dir / "backup.pvault"
        v.backup(b)
        v.lock()
        leftovers = [p.name for p in self.dir.iterdir() if p.name.startswith(".pvault-")]
        self.assertEqual(leftovers, [])

    def test_failed_atomic_write_preserves_original_and_cleans_temp(self):
        v = Vault.create(self.path, self.pw)
        e1 = Entry.new("First", "u1", "CANARY_1")
        v.replace([e1])
        before = self.path.read_bytes()
        try:
            with mock.patch("personal_vault.core.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(VaultError):
                    v.replace([Entry.new("Second", "u2", "CANARY_2")])
            self.assertEqual(self.path.read_bytes(), before)
            leftovers = [p.name for p in self.dir.iterdir() if p.name.startswith(".pvault-")]
            self.assertEqual(leftovers, [])
        finally:
            v.lock()

    def test_truncated_vault_fails_closed(self):
        v = Vault.create(self.path, self.pw)
        v.lock()
        raw = self.path.read_bytes()
        self.path.write_bytes(raw[:20])
        with self.assertRaises(VaultError):
            Vault.open(self.path, self.pw)
        self.assertEqual(self.path.read_bytes(), raw[:20])


class ImportPreviewAndParserTests(unittest.TestCase):
    def test_inspect_import_detects_vault_duplicates_separately(self):
        existing = [Entry.new("Facebook — Demo", "demo@example.invalid", "CANARY_1")]
        text = (
            "Account: Facebook — Demo\nName: demo@example.invalid\nPass: CANARY_NEW\n\n"
            "Account: New App\nName: new@example.invalid\nPass: CANARY_2\n"
        )
        preview = inspect_import(text, ".txt", existing_entries=existing)
        self.assertEqual(len(preview.records), 2)
        self.assertEqual(len(preview.new_entries), 1)
        self.assertEqual(preview.new_entries[0].account, "New App")
        self.assertEqual(len(preview.duplicate_in_vault), 1)
        self.assertEqual(preview.duplicate_in_vault[0].account, "Facebook — Demo")

    def test_bat_rem_and_double_colon_comments_supported(self):
        bat = (
            "REM Account: Bat Demo 1\nREM Name: u1\nREM Pass: CANARY_BAT_1\n\n"
            ":: Account: Bat Demo 2\n:: Name: u2\n:: Pass: CANARY_BAT_2\n"
        )
        items = parse_import(bat, ".bat")
        self.assertEqual([i.account for i in items], ["Bat Demo 1", "Bat Demo 2"])

    def test_bat_rejects_executable_lines(self):
        with self.assertRaises(VaultError):
            parse_import("REM Account: Bat\nREM Name: u\nREM Pass: p\nnet user\n", ".bat")

    def test_csv_extra_columns_rejected(self):
        with self.assertRaises(VaultError):
            parse_import("account,name,pass\nDemo,u,p,extra_col\n", ".csv")


if __name__ == "__main__":
    unittest.main()

