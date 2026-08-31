import tempfile
import unittest
from pathlib import Path

from bastioncam.auth import TokenError, authenticate, create_collector, register_embedded_collector
from bastioncam.db import connect


class CollectorAuthTest(unittest.TestCase):
    def test_generated_jwt_authenticates_named_collector(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            collector, token = create_collector(db, "Office workstation")
            authenticated = authenticate(db, f"Bearer {token}")
            self.assertEqual(authenticated["id"], collector["id"])
            self.assertEqual(authenticated["name"], "Office workstation")
            self.assertEqual(len(token.split(".")), 3)
            db.close()

    def test_tampered_and_missing_tokens_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            _, token = create_collector(db, "Laptop")
            with self.assertRaises(TokenError):
                authenticate(db, None)
            with self.assertRaises(TokenError):
                authenticate(db, f"Bearer {token[:-1]}x")
            db.close()

    def test_disabled_collector_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            collector, token = create_collector(db, "Laptop")
            db.execute("UPDATE collectors SET disabled=1 WHERE id=?", (collector["id"],))
            db.commit()
            with self.assertRaises(TokenError):
                authenticate(db, f"Bearer {token}")
            db.close()

    def test_revoked_collector_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            collector, token = create_collector(db, "Retired laptop")
            db.execute("UPDATE collectors SET revoked_at=? WHERE id=?",
                       ("2026-01-01T00:00:00+00:00", collector["id"]))
            db.commit()
            with self.assertRaisesRegex(TokenError, "revoked"):
                authenticate(db, f"Bearer {token}")
            db.close()

    def test_embedded_collector_registration_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            first = register_embedded_collector(db, "fedora", "2026-01-01T00:00:00+00:00")
            second = register_embedded_collector(db, "fedora", "2026-01-01T00:01:00+00:00")
            db.commit()
            self.assertEqual(first["id"], second["id"])
            row = db.execute("SELECT name,last_seen_at FROM collectors").fetchone()
            self.assertEqual(row["name"], "fedora (embedded)")
            self.assertEqual(row["last_seen_at"], "2026-01-01T00:01:00+00:00")
            db.close()


if __name__ == "__main__":
    unittest.main()
