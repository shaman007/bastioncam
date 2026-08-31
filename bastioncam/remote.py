from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from .db import connect


def push_pending(db_path: str, server_url: str, token: str,
                 limit: int = 100, timeout: float = 10) -> int:
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
                    "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status not in (200, 201):
                    break
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.execute("UPDATE snapshots SET delivered_at=? WHERE id=?", (stamp, row["id"])); db.commit()
            delivered += 1
    finally:
        db.close()
    return delivered
