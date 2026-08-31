import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bastioncam.db import connect
from bastioncam.protocol import PROTOCOL_VERSION, compatibility_error
from bastioncam.remote import poll_config, push_pending
from bastioncam.auth import create_collector
from bastioncam.web import App


class FakeResponse:
    status = 201

    def __init__(self, payload=None):
        self.payload = payload or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class CollectorProtocolTest(unittest.TestCase):
    def test_protocol_compatibility_bounds(self):
        self.assertEqual("", compatibility_error(PROTOCOL_VERSION))
        self.assertIn("too old", compatibility_error(PROTOCOL_VERSION - 1))
        self.assertIn("newer", compatibility_error(PROTOCOL_VERSION + 1))

    def test_schema_adds_collector_control_and_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            columns = {row[1] for row in db.execute("PRAGMA table_info(collectors)")}
            self.assertTrue({"paused","revoked_at","config_revision","owner","labels",
                "hostname","operating_system","collector_version","backend_version",
                "protocol_version","queue_size","last_upload_at","last_error",
                "compatibility_error"}.issubset(columns))
            db.close()

    @patch("bastioncam.remote.backend_version", return_value="zellij 1.0")
    @patch("bastioncam.remote.urllib.request.urlopen")
    def test_heartbeat_advertises_metadata_and_receives_revision(self, urlopen, _backend):
        urlopen.return_value = FakeResponse({"paused":False,"config_revision":4,"poll_interval":30})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collector.db"
            connect(path).close()
            config = poll_config(str(path), "https://example.test", "jwt")
            request = urlopen.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(PROTOCOL_VERSION, payload["protocol_version"])
            self.assertIn("hostname", payload)
            self.assertIn("operating_system", payload)
            self.assertEqual("zellij 1.0", payload["backend_version"])
            self.assertEqual("4", str(config["config_revision"]))
            self.assertEqual(str(PROTOCOL_VERSION), request.headers["X-bastioncam-protocol"])

    @patch("bastioncam.remote.urllib.request.urlopen")
    def test_upload_includes_protocol_and_config_revision(self, urlopen):
        urlopen.return_value = FakeResponse()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collector.db"
            db=connect(path)
            db.execute("""INSERT INTO panes(session_name,pane_key,first_seen,last_seen)
                VALUES('work','terminal_1','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')""")
            pane_id=db.execute("SELECT id FROM panes").fetchone()[0]
            db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(?,?,?,?)",
                (pane_id,"2026-01-01T00:00:00+00:00","hello","hash"));db.commit();db.close()
            self.assertEqual(1,push_pending(str(path),"https://example.test","jwt",config_revision=7))
            request=urlopen.call_args.args[0]
            self.assertEqual(str(PROTOCOL_VERSION),request.headers["X-bastioncam-protocol"])
            self.assertEqual("7",request.headers["X-bastioncam-config-revision"])

    def test_server_rejects_paused_stale_and_incompatible_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"server.db";db=connect(path)
            collector,token=create_collector(db,"Laptop")
            handler=type("TestApp",(App,),{"db_path":str(path)})
            server=ThreadingHTTPServer(("127.0.0.1",0),handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"

            def post(protocol=PROTOCOL_VERSION,revision=1):
                request=urllib.request.Request(base+"/api/ingest",data=json.dumps({
                    "session_name":"work","pane_key":"terminal_1",
                    "captured_at":"2026-01-01T00:00:00+00:00","content":"hello",
                }).encode(),headers={"Content-Type":"application/json",
                    "Authorization":f"Bearer {token}","X-BastionCam-Protocol":str(protocol),
                    "X-BastionCam-Config-Revision":str(revision)})
                try:
                    with urllib.request.urlopen(request) as response:return response.status
                except urllib.error.HTTPError as error:return error.code

            try:
                self.assertEqual(201,post())
                db.execute("UPDATE collectors SET paused=1,config_revision=2 WHERE id=?",(collector["id"],));db.commit()
                self.assertEqual(409,post(revision=2))
                db.execute("UPDATE collectors SET paused=0 WHERE id=?",(collector["id"],));db.commit()
                self.assertEqual(409,post(revision=1))
                self.assertEqual(426,post(protocol=PROTOCOL_VERSION+1,revision=2))
                self.assertEqual(1,db.execute("SELECT count(*) FROM snapshots").fetchone()[0])
            finally:
                server.shutdown();server.server_close();thread.join();db.close()


if __name__ == "__main__":
    unittest.main()
