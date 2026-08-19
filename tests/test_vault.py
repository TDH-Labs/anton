import os
import sqlite3
import tempfile
import unittest
from harbor.vault import (emit_candidate, find_orphans, provision_vault, scan_vault)


class TestVault(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.vault = provision_vault(os.path.join(self.dir.name, "vault"))

    def tearDown(self):
        self.dir.cleanup()

    def test_provision_creates_layout(self):
        for sub in ("notes", "mocs", "templates", "digests"):
            self.assertTrue(os.path.isdir(os.path.join(self.vault, sub)))
        self.assertTrue(os.path.exists(os.path.join(self.vault, "index.md")))
        self.assertTrue(os.path.exists(os.path.join(self.vault, "vault.db")))

    def test_scan_detects_new_note_and_records_hash(self):
        new_note = os.path.join(self.vault, "notes", "inbox-idea.md")
        with open(new_note, "w", encoding="utf-8") as f:
            f.write("# Inbox Idea\n\nSome thought.\n")
        new_mod, _removed = scan_vault(self.vault)
        self.assertEqual(len(new_mod), 1)
        self.assertEqual(new_mod[0]["path"], os.path.join("notes", "inbox-idea.md"))
        # second scan: no changes
        self.assertEqual(scan_vault(self.vault)[0], [])

    def test_orphan_detection(self):
        a = os.path.join(self.vault, "notes", "a.md")
        b = os.path.join(self.vault, "notes", "b.md")
        c = os.path.join(self.vault, "notes", "c.md")
        with open(a, "w", encoding="utf-8") as f:
            f.write("# A\n\nLinks to [[b]]\n")
        with open(b, "w", encoding="utf-8") as f:
            f.write("# B\n\nLinks to [[a]]\n")
        with open(c, "w", encoding="utf-8") as f:
            f.write("# C\n\nIsolated note.\n")
        scan_vault(self.vault)
        orphans = find_orphans(self.vault)
        self.assertIn(os.path.join("notes", "c.md"), orphans)
        self.assertNotIn(os.path.join("notes", "a.md"), orphans)

    def test_emit_candidate(self):
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        conn.execute("""CREATE TABLE IF NOT EXISTS initiatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
            slug TEXT, source TEXT, risk TEXT, score REAL, status TEXT, ts TEXT)""")
        emit_candidate(conn, "review_vault_note", "vault/notes/x.md")
        row = conn.execute("SELECT slug, status FROM initiatives").fetchone()
        self.assertEqual(row, ("review_vault_note", "pending"))
        conn.close()

    def test_wikilink_alias_and_header_parsing(self):
        from harbor.vault import WIKILINK
        text = "Check [[notes/test|My Test]] and [[mocs/strategy#overview]] as well as [[doc#sub|Doc Title]]."
        matches = WIKILINK.findall(text)
        self.assertEqual(matches, ["notes/test", "mocs/strategy", "doc"])

