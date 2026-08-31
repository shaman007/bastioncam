import tempfile
import unittest
from pathlib import Path

from bastioncam.db import connect
from bastioncam.security import redact_text, scrub_database


class SecurityTest(unittest.TestCase):
    def test_redacts_assignments_headers_and_private_keys(self):
        source = "TOKEN=very_long_sensitive_value_123456\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz\n-----BEGIN PRIVATE KEY-----\nmaterial\n-----END PRIVATE KEY-----"
        clean = redact_text(source)
        self.assertNotIn("very_long_sensitive", clean)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", clean)
        self.assertNotIn("material", clean)
        self.assertIn("[REDACTED]", clean)

    def test_does_not_redact_generic_hashes_or_identifiers(self):
        source = "build digest 0123456789abcdef0123456789abcdef and public 192.0.2.10"
        self.assertEqual(redact_text(source), source)

    def test_scrubs_existing_snapshot_and_requeues_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            db.execute("INSERT INTO panes(session_name,pane_key,first_seen,last_seen) VALUES('s','terminal_1','x','x')")
            secret = "PASSWORD=very_long_sensitive_value_123456"
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(1,'2026-01-01',?,'x')", (secret,))
            db.execute("""INSERT INTO segments(pane_id,first_snapshot_id,last_snapshot_id,started_at,ended_at,source_text,summary,status,created_at)
                VALUES(1,1,1,'x','x',?,?,'done','x')""", (secret, secret))
            db.commit(); result = scrub_database(db)
            self.assertEqual(result["snapshots"], 1)
            self.assertNotIn("sensitive", db.execute("SELECT content FROM snapshots").fetchone()[0])
            self.assertEqual(db.execute("SELECT status FROM segments").fetchone()[0], "retry")
            db.close()


if __name__ == "__main__": unittest.main()
