from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bastioncam.db import connect
from bastioncam.web import App, collector_presence


class CaptureApp(App):
    def send_page(self, body: str, status: int = 200) -> None:
        self.captured_body = body
        self.captured_status = status


class CollectorWebTest(unittest.TestCase):
    def test_collector_presence_thresholds_and_age(self):
        now=datetime(2026,8,31,12,10,tzinfo=ZoneInfo("UTC"))
        self.assertEqual(("offline","never seen",2),collector_presence(None,now))
        self.assertEqual(("online","1m ago",0),collector_presence("2026-08-31T12:09:00+00:00",now))
        self.assertEqual(("stale","2m ago",1),collector_presence("2026-08-31T12:08:00+00:00",now))
        self.assertEqual(("offline","10m ago",2),collector_presence("2026-08-31T12:00:00+00:00",now))

    @patch("bastioncam.web.parse_query",return_value=("needle",None,None,None))
    def test_search_is_scoped_to_selected_collector(self, _parse):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"test.db";db=connect(path)
            for collector_id,name,pane_key,title in (("one","One","pane-one","first"),("two","Two","pane-two","second")):
                db.execute("INSERT INTO collectors(id,name,created_at) VALUES(?,?,?)",(collector_id,name,"2026-08-31T12:00:00+00:00"))
                db.execute("INSERT INTO panes(collector_id,session_name,pane_key,title,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                    (collector_id,name,pane_key,title,"2026-08-31T12:00:00+00:00","2026-08-31T12:00:00+00:00"))
                pane_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(?,?,?,?)",
                    (pane_id,"2026-08-31T12:00:00+00:00",f"needle from {name}",collector_id))
            db.commit();db.close()
            app=object.__new__(CaptureApp);app.db_path=str(path)
            app.index("needle",collector_id="two")
            self.assertIn("needle from Two",app.captured_body)
            self.assertNotIn("needle from One",app.captured_body)
            self.assertIn("value='two' selected",app.captured_body)
            self.assertIn("collector=two",app.captured_body)


if __name__ == "__main__":
    unittest.main()
