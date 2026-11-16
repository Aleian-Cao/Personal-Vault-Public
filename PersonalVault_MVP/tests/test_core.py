import json, os, tempfile, unittest
from pathlib import Path
from personal_vault.core import Entry, Vault, VaultError, search, parse_import, synthetic_entries

class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.pvault'; self.pw='Synthetic-Master-Only-123!'
        self.entry=Entry.new('ETAP Server 15','demo15','CANARY_SECRET_15', ['etap 15'], 'demo only')
    def test_roundtrip_and_ciphertext(self):
        v=Vault.create(self.path,self.pw); v.replace([self.entry]); v.lock()
        raw=self.path.read_bytes()
        for s in ('CANARY_SECRET_15','ETAP Server 15','demo15','demo only','etap 15',self.pw): self.assertNotIn(s.encode(),raw)
        self.assertEqual(Vault.open(self.path,self.pw).entries,[self.entry])
    def test_wrong_password(self):
        Vault.create(self.path,self.pw).lock()
        with self.assertRaises(VaultError): Vault.open(self.path,'wrong')
    def test_corruption_no_overwrite(self):
        Vault.create(self.path,self.pw).lock(); b=bytearray(self.path.read_bytes()); b[-2]^=1; self.path.write_bytes(b)
        with self.assertRaises(VaultError): Vault.open(self.path,self.pw)
        self.assertEqual(self.path.read_bytes(),b)
    def test_locked(self):
        v=Vault.create(self.path,self.pw); v.lock()
        with self.assertRaises(VaultError): _=v.entries
        with self.assertRaises(VaultError): v.replace([self.entry])
    def test_no_overwrite_create(self):
        Vault.create(self.path,self.pw).lock()
        with self.assertRaises(VaultError): Vault.create(self.path,self.pw)
    def test_backup(self):
        v=Vault.create(self.path,self.pw); v.replace([self.entry]); b=self.path.with_name('backup.pvault'); v.backup(b)
        self.assertEqual(Vault.open(b,self.pw).entries,[self.entry]); self.assertEqual(b.read_bytes(),self.path.read_bytes())
    def test_nonce_changes(self):
        v=Vault.create(self.path,self.pw); a=self.path.read_bytes(); v.replace([]); self.assertNotEqual(a,self.path.read_bytes())
    def test_duplicate_id(self):
        v=Vault.create(self.path,self.pw)
        with self.assertRaises(VaultError): v.replace([self.entry,self.entry])
        self.assertEqual(v.entries,[])
    def test_invalid_header(self):
        self.path.write_bytes(b'not a vault')
        with self.assertRaises(VaultError): Vault.open(self.path,self.pw)

class SearchTests(unittest.TestCase):
    def setUp(self): self.items=synthetic_entries(500)
    def test_alias(self): self.assertEqual(search(self.items,'fb chính').items[0].account,'Facebook — Demo Personal')
    def test_unaccented(self): self.assertEqual(search(self.items,'fb chinh').items[0].account,'Facebook — Demo Personal')
    def test_pscad(self): self.assertEqual(len(search(self.items,'PSCAD').items),5)
    def test_server_number(self): self.assertEqual([x.account for x in search(self.items,'etap server 15').items],['ETAP Server 15'])
    def test_natural_prefix(self): self.assertEqual(search(self.items,'Cho tôi tài khoản fb chính').items[0].account,'Facebook — Demo Personal')
    def test_attached_number(self): self.assertEqual([x.account for x in search(self.items,'etap server15').items],['ETAP Server 15'])
    def test_wrong_number(self): self.assertEqual(search(self.items,'etap server 999').items,[])
    def test_fuzzy_suggest(self): self.assertEqual(search(self.items,'etap sever 15').kind,'suggestion')
    def test_collision(self):
        a=Entry.new('A','a','p',['shared']); b=Entry.new('B','b','p',['shared']); self.assertEqual(search([a,b],'shared').kind,'ambiguous')
    def test_unknown(self): self.assertEqual(search(self.items,'zzzzzzzzzzzz').items,[])
    def test_description(self): self.assertEqual(search(self.items,'mô phỏng').items[0].account,'ETAP Server 15')
    def test_empty(self): self.assertEqual(search(self.items,'').items,[])
    def test_password_not_indexed(self): self.assertEqual(search(self.items,self.items[0].password).items,[])

class ImportTests(unittest.TestCase):
    def test_text(self):
        items=parse_import('Account: Demo\nName: demo\nPass: CANARY_TEST\nAliases: fb chính; fb cá nhân\nDescription: demo', '.txt'); self.assertEqual(items[0].aliases,('fb chính','fb cá nhân'))
    def test_csv(self): self.assertEqual(parse_import('account,name,pass\nDemo,demo,fake\n','.csv')[0].password,'fake')
    def test_json(self): self.assertEqual(parse_import('[{"account":"Demo","name":"demo","pass":"fake"}]','.json')[0].name,'demo')
    def test_script_comments(self): self.assertEqual(parse_import('# Account: Demo\n# Name: demo\n# Pass: fake','.ps1')[0].account,'Demo')
    def test_script_reject_commands(self):
        with self.assertRaises(VaultError): parse_import('# Account: Demo\n# Name: demo\n# Pass: fake\nStart-Process calc','.ps1')
    def test_missing(self):
        with self.assertRaises(VaultError): parse_import('Account: Demo\nName: demo','.txt')
    def test_duplicate_field(self):
        with self.assertRaises(VaultError): parse_import('Account: Demo\nName: demo\nPass: fake\nPass: other','.txt')
    def test_duplicate_records(self):
        with self.assertRaises(VaultError): parse_import('account,name,pass\nDemo,demo,fake\nDemo,demo,other\n','.csv')
    def test_unsupported(self):
        with self.assertRaises(VaultError): parse_import('x','.exe')
    def test_bad_json(self):
        with self.assertRaises(VaultError): parse_import('{"pass":"fake"}', '.json')

if __name__=='__main__': unittest.main()
