import tempfile
import unittest
from pathlib import Path

from bastioncam.db import connect
from bastioncam.llm import build_segments, compact_snapshots, refresh_period_summary


class DatabaseTest(unittest.TestCase):
    def test_fts_trigger_indexes_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            db.execute("INSERT INTO panes(session_name,pane_key,first_seen,last_seen) VALUES('work','terminal_1','2026-01-01','2026-01-01')")
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(1,'2026-01-01','cargo build finished','x')")
            row = db.execute("SELECT rowid FROM snapshots_fts WHERE snapshots_fts MATCH 'cargo'").fetchone()
            self.assertEqual(row[0], 1)
            db.close()

    def test_segment_building_and_compaction(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            db.execute("INSERT INTO panes(session_name,pane_key,first_seen,last_seen) VALUES('work','terminal_1','2026-01-01','2026-01-01')")
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(1,'2026-01-01T10:00:00+00:00','prompt','a')")
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(1,'2026-01-01T10:00:10+00:00','prompt\ncargo build','b')")
            db.commit()
            self.assertEqual(build_segments(db, settle_seconds=0), 1)
            row = db.execute("SELECT first_snapshot_id,last_snapshot_id,source_text FROM segments").fetchone()
            self.assertEqual((row[0], row[1]), (1, 2))
            self.assertIn("cargo build", row[2])
            db.close()

    def test_compact_snapshots(self):
        text = compact_snapshots(["one", "one\ntwo"])
        self.assertIn("two", text)

    def test_period_summary_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            db.execute("INSERT INTO panes(session_name,pane_key,first_seen,last_seen) VALUES('work','terminal_1','2026-01-01','2026-01-01')")
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(1,'2026-01-01T10:00:00+00:00','build','a')")
            db.execute("""INSERT INTO segments(pane_id,first_snapshot_id,last_snapshot_id,started_at,ended_at,
                source_text,summary,status,created_at) VALUES(1,1,1,'2026-01-01T10:00:00+00:00',
                '2026-01-01T10:05:00+00:00','build','Build completed','done','2026-01-01')""")
            db.commit()
            def fake(*args, **kwargs): return {"response": "- Build completed"}
            self.assertEqual(refresh_period_summary(db,"http://unused","model",request=fake), 1)
            self.assertEqual(db.execute("SELECT count(*) FROM period_summaries").fetchone()[0], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
