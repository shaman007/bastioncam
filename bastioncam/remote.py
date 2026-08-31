from __future__ import annotations

import json
import platform
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .db import connect
from .protocol import PROTOCOL_VERSION, collector_version
from .terminal_backend import version as backend_version


class RemoteError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _request(server_url: str, token: str, path: str, payload: dict,
             timeout: float = 10) -> dict:
    request = urllib.request.Request(server_url.rstrip("/") + path,
        data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}",
            "X-BastionCam-Protocol": str(PROTOCOL_VERSION)})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try: message=json.loads(error.read()).get("error",str(error))
        except Exception: message=str(error)
        raise RemoteError(error.code,message) from error


def queue_size(db_path: str) -> int:
    db=connect(db_path)
    try:return db.execute("SELECT count(*) FROM snapshots WHERE delivered_at IS NULL").fetchone()[0]
    finally:db.close()


def poll_config(db_path: str, server_url: str, token: str, last_error: str = "",
                timeout: float = 10) -> dict:
    return _request(server_url,token,"/api/collector/heartbeat",{
        "protocol_version":PROTOCOL_VERSION,"collector_version":collector_version(),
        "hostname":socket.gethostname(),"operating_system":platform.platform(),
        "backend_version":backend_version(),"queue_size":queue_size(db_path),
        "last_error":last_error[:2000],
    },timeout)


def push_pending(db_path: str, server_url: str, token: str,
                 limit: int = 100, timeout: float = 10,
                 config_revision: int = 0) -> int:
    db = connect(db_path)
    rows = db.execute("""SELECT s.id,s.captured_at,s.content,p.session_name,p.pane_key,
        p.tab_name,p.title,p.command,p.cwd FROM snapshots s JOIN panes p ON p.id=s.pane_id
        WHERE s.delivered_at IS NULL ORDER BY s.id LIMIT ?""", (limit,)).fetchall()
    delivered = 0
    try:
        for row in rows:
            payload = dict(row); payload.pop("id")
            request = urllib.request.Request(server_url.rstrip("/") + "/api/ingest",
                data=json.dumps(payload).encode(), headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {token}",
                    "X-BastionCam-Protocol":str(PROTOCOL_VERSION),
                    "X-BastionCam-Config-Revision":str(config_revision)})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if response.status not in (200, 201):break
            except urllib.error.HTTPError as error:
                try:message=json.loads(error.read()).get("error",str(error))
                except Exception:message=str(error)
                raise RemoteError(error.code,message) from error
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.execute("UPDATE snapshots SET delivered_at=? WHERE id=?", (stamp, row["id"])); db.commit()
            delivered += 1
    finally:
        db.close()
    return delivered
