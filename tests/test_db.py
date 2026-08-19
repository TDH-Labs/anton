import os
import sqlite3
import tempfile
import unittest
from anton.db import init_db
from anton.vault_db import init_vault_db

EXPECTED_ISOLATION = {"sessions", "initiatives", "approvals", "budgets", "metering",
                      "seen_external_items", "skill_dependencies", "confidence_log", "playbooks"}
EXPECTED_VAULT = {"notes", "graph_edges", "entities", "mocs", "seen_items",
                  "digest_history", "embeddings"}


def tables(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


class TestDb(unittest.TestCase):
    def test_isolation_schema(self):
        with tempfile.TemporaryDirectory() as d:
            conn = init_db(os.path.join(d, "isolation.db"))
            self.assertTrue(EXPECTED_ISOLATION <= tables(conn))
            conn.close()

    def test_vault_schema(self):
        with tempfile.TemporaryDirectory() as d:
            conn = init_vault_db(os.path.join(d, "vault.db"))
            self.assertTrue(EXPECTED_VAULT <= tables(conn))
            conn.close()
