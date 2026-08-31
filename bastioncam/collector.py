from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone

from . import terminal_backend
from .auth import register_embedded_collector
from .db import connect

LOG = logging.getLogger("bastioncam")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect_once(db_path: str, embedded_hostname: str = "") -> tuple[int, int]:
    db = connect(db_path)
    embedded = register_embedded_collector(db, embedded_hostname, now()) if embedded_hostname else None
    seen = saved = 0
    for session in terminal_backend.sessions():
        for pane in terminal_backend.panes(session):
            if terminal_backend.is_plugin(pane):
                continue
            key = terminal_backend.pane_key(pane)
            content = terminal_backend.dump(session, key)
            if not content or not content.strip():
                continue
            stamp = now()
            tab = terminal_backend.field(pane, "tab_name", "tab")
            title = terminal_backend.field(pane, "title", "pane_name", "name")
            command = terminal_backend.field(pane, "pane_command", "terminal_command", "command", "command_name")
            cwd = terminal_backend.field(pane, "pane_cwd", "cwd", "current_working_directory")
            db.execute(
                """INSERT INTO panes(collector_id,session_name,pane_key,tab_name,title,command,cwd,first_seen,last_seen)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_name,pane_key) DO UPDATE SET
                   collector_id=excluded.collector_id,
                   tab_name=excluded.tab_name,title=excluded.title,command=excluded.command,
                   cwd=excluded.cwd,last_seen=excluded.last_seen""",
                (embedded["id"] if embedded else None,session,key,tab,title,command,cwd,stamp,stamp),
            )
            pane_id = db.execute(
                "SELECT id FROM panes WHERE session_name=? AND pane_key=?", (session, key)
            ).fetchone()[0]
            digest = hashlib.sha256(content.encode()).hexdigest()
            previous = db.execute(
                "SELECT content_hash FROM snapshots WHERE pane_id=? ORDER BY id DESC LIMIT 1",
                (pane_id,),
            ).fetchone()
            if not previous or previous[0] != digest:
                db.execute(
                    "INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(?,?,?,?)",
                    (pane_id, stamp, content, digest),
                )
                saved += 1
            seen += 1
    if embedded:
        register_embedded_collector(db, embedded_hostname, now())
    db.commit()
    db.close()
    return seen, saved


def collect_forever(db_path: str, interval: float, server_url: str | None = None,
                    token: str = "", embedded_hostname: str = "") -> None:
    LOG.info("collector started; interval=%ss database=%s", interval, db_path)
    config={"paused":False,"config_revision":0,"poll_interval":30}
    next_poll=0.0;last_error=""
    while True:
        try:
            if server_url and time.monotonic() >= next_poll:
                from .remote import poll_config
                if not token:raise ValueError("remote server configured without a collector token")
                try:
                    config=poll_config(db_path,server_url,token,last_error)
                    last_error="";next_poll=time.monotonic()+max(5,int(config.get("poll_interval",30)))
                except Exception as error:
                    last_error=str(error);next_poll=time.monotonic()+30
                    LOG.warning("collector config poll failed: %s",error)
            if server_url and config.get("paused"):
                LOG.info("collector paused by server; revision=%s",config.get("config_revision"))
                time.sleep(interval);continue
            seen, saved = collect_once(db_path, embedded_hostname)
            delivered = 0
            if server_url:
                try:
                    from .remote import push_pending
                    if not token:
                        raise ValueError("remote server configured without a collector token")
                    delivered = push_pending(db_path,server_url,token,
                        config_revision=int(config.get("config_revision",0)))
                except Exception as error:
                    last_error=str(error)
                    LOG.warning("remote delivery failed; snapshots remain queued: %s", error)
            LOG.info("panes=%d new_snapshots=%d delivered=%d", seen, saved, delivered)
        except Exception:
            LOG.exception("collection cycle failed")
        time.sleep(interval)
