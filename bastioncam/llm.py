from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOG = logging.getLogger("bastioncam.enricher")
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}
META_SUMMARY = re.compile(
    r"(?is)^\s*(?:i need to|let me|we need to|first[, ]+i(?:'ll| will)|the task is to)"
)


def post(base_url: str, endpoint: str, payload: dict, timeout: float = 300) -> dict:
    request = urllib.request.Request(base_url.rstrip("/") + endpoint,
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def generate_summary(base_url: str, model: str, prompt: str, max_tokens: int) -> str:
    response = post(base_url, "/api/generate", {
        "model": model, "prompt": prompt + "\n\nReturn JSON with the summary field only. Do not include reasoning or a preamble.",
        "stream": False, "think": False, "format": SUMMARY_SCHEMA,
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    })
    value = json.loads(response.get("response", "{}")); summary = str(value.get("summary") or "").strip()
    if not summary or META_SUMMARY.search(summary):
        raise ValueError("model returned a meta-commentary instead of a final summary")
    return summary


def requeue_invalid_summaries(db) -> int:
    changed = 0
    for row in db.execute("SELECT id,summary FROM segments WHERE status='done'").fetchall():
        if not row["summary"] or META_SUMMARY.search(row["summary"]):
            db.execute("UPDATE segments SET summary=NULL,embedding=NULL,status='retry',error=NULL WHERE id=?", (row["id"],))
            changed += 1
    if changed:
        db.execute("DELETE FROM period_summaries"); db.commit()
    return changed


def compact_snapshots(contents: list[str], limit: int = 16000) -> str:
    """Keep the first screen and meaningful additions from later redraws."""
    if not contents:
        return ""
    pieces = [contents[0]]
    previous = contents[0].splitlines()
    for content in contents[1:]:
        current = content.splitlines()
        additions = [line[2:] for line in difflib.ndiff(previous, current)
                     if line.startswith("+ ") and line[2:].strip()]
        if additions:
            pieces.append("\n".join(additions))
        previous = current
    return "\n\n--- screen change ---\n\n".join(pieces)[-limit:]


def build_segments(db, settle_seconds: int = 45, gap_seconds: int = 120,
                   max_snapshots: int = 20) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=settle_seconds)).isoformat(timespec="seconds")
    rows = db.execute(
        """SELECT s.id,s.pane_id,s.captured_at,s.content FROM snapshots s
           WHERE s.captured_at<=? AND NOT EXISTS(
             SELECT 1 FROM segments g WHERE g.first_snapshot_id<=s.id AND g.last_snapshot_id>=s.id
               AND g.pane_id=s.pane_id)
           ORDER BY s.pane_id,s.captured_at,s.id""", (cutoff,)).fetchall()
    groups: list[list] = []
    for row in rows:
        if not groups or groups[-1][-1]["pane_id"] != row["pane_id"]:
            groups.append([row]); continue
        previous = datetime.fromisoformat(groups[-1][-1]["captured_at"])
        current = datetime.fromisoformat(row["captured_at"])
        if (current - previous).total_seconds() > gap_seconds or len(groups[-1]) >= max_snapshots:
            groups.append([row])
        else:
            groups[-1].append(row)
    created = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for group in groups:
        db.execute(
            """INSERT OR IGNORE INTO segments(pane_id,first_snapshot_id,last_snapshot_id,
               started_at,ended_at,source_text,created_at) VALUES(?,?,?,?,?,?,?)""",
            (group[0]["pane_id"], group[0]["id"], group[-1]["id"],
             group[0]["captured_at"], group[-1]["captured_at"],
             compact_snapshots([row["content"] for row in group]), stamp))
        created += db.execute("SELECT changes()").fetchone()[0]
    db.commit()
    return created


def enrich_pending(db, base_url: str, chat_model: str, embed_model: str, limit: int) -> int:
    rows = db.execute("SELECT id,source_text FROM segments WHERE status IN ('pending','retry') ORDER BY id LIMIT ?", (limit,)).fetchall()
    done = 0
    for row in rows:
        db.execute("UPDATE segments SET status='processing',error=NULL WHERE id=?", (row["id"],)); db.commit()
        try:
            prompt = (
                "You are indexing terminal history. Summarize one work episode in English. "
                "Include the goal, commands, projects and files, significant errors, and outcome. "
                "Do not narrate the interface or invent facts. Use one compact paragraph.\n\n"
                + row["source_text"])
            summary = generate_summary(base_url, chat_model, prompt, 400)
            vector = post(base_url, "/api/embed", {"model": embed_model,
                "input": summary + "\n" + row["source_text"][-6000:]}).get("embeddings", [[]])[0]
            db.execute("UPDATE segments SET summary=?,embedding=?,status='done',error=NULL WHERE id=?",
                       (summary, json.dumps(vector), row["id"])); db.commit(); done += 1
        except Exception as error:
            db.execute("UPDATE segments SET status='retry',error=? WHERE id=?",
                       (str(error)[:1000], row["id"])); db.commit()
            LOG.warning("segment %s failed: %s", row["id"], error); break
    return done


def refresh_period_summary(db, base_url: str, chat_model: str,
                           timezone_name: str = "Europe/Prague", request=post) -> int:
    """Refresh at most one changed hour/day bucket per enrichment cycle."""
    tz = ZoneInfo(timezone_name); now = datetime.now(tz)
    rows = db.execute("""SELECT id,started_at,ended_at,summary FROM segments
        WHERE status='done' AND summary IS NOT NULL AND summary<>'' ORDER BY started_at""").fetchall()
    buckets: dict[tuple[str, datetime], list] = {}
    for row in rows:
        local = datetime.fromisoformat(row["started_at"]).astimezone(tz)
        hour = local.replace(minute=0, second=0, microsecond=0)
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets.setdefault(("hour", hour), []).append(row)
        buckets.setdefault(("day", day), []).append(row)
    candidates = sorted(buckets, key=lambda x: (x[1], x[0] == "hour"), reverse=True)
    for period_type, local_start in candidates:
        delta = timedelta(hours=1) if period_type == "hour" else timedelta(days=1)
        local_end = local_start + delta
        start = local_start.astimezone(timezone.utc).isoformat(timespec="seconds")
        end = local_end.astimezone(timezone.utc).isoformat(timespec="seconds")
        source = "\n".join(f"- {r['started_at']}: {r['summary']}" for r in buckets[(period_type, local_start)])
        digest = hashlib.sha256(source.encode()).hexdigest()
        existing = db.execute("SELECT source_hash,updated_at FROM period_summaries WHERE period_type=? AND period_start=?",
                              (period_type, start)).fetchone()
        if existing and existing["source_hash"] == digest:
            continue
        if existing and local_start <= now < local_end:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(existing["updated_at"])
            minimum = timedelta(minutes=10 if period_type == "hour" else 60)
            if age < minimum:
                continue
        label = "hour" if period_type == "hour" else "day"
        prompt = f"""Summarize the terminal work for this {label} in English using the episode descriptions below.
Write 3–6 concise bullet points covering major tasks, important results, errors, and unfinished work.
Do not invent facts or repeat the same information.\n\n{source}"""
        if request is post:
            summary = generate_summary(base_url, chat_model, prompt, 500)
        else:
            response = request(base_url, "/api/generate", {"model": chat_model, "prompt": prompt,
                "stream": False, "think": False, "format": SUMMARY_SCHEMA,
                "options": {"temperature": .1, "num_predict": 300}})
            raw = response.get("response", "").strip()
            try: summary = json.loads(raw).get("summary", "")
            except json.JSONDecodeError: summary = raw
        if not summary:
            return 0
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.execute("""INSERT INTO period_summaries(period_type,period_start,period_end,summary,source_hash,segment_count,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(period_type,period_start) DO UPDATE SET
            period_end=excluded.period_end,summary=excluded.summary,source_hash=excluded.source_hash,
            segment_count=excluded.segment_count,updated_at=excluded.updated_at""",
            (period_type, start, end, summary, digest, len(buckets[(period_type, local_start)]), stamp))
        db.commit(); return 1
    return 0


def enrich_loop(db_path: str, base_url: str, chat_model: str, embed_model: str,
                interval: int, settle_seconds: int, batch: int) -> None:
    from .db import connect
    LOG.info("enricher started; chat=%s embeddings=%s", chat_model, embed_model)
    while True:
        db = connect(db_path)
        try:
            repaired = requeue_invalid_summaries(db)
            created = build_segments(db, settle_seconds=settle_seconds)
            done = enrich_pending(db, base_url, chat_model, embed_model, batch)
            periods = refresh_period_summary(db, base_url, chat_model)
            LOG.info("summaries_requeued=%d segments_created=%d enriched=%d period_summaries=%d", repaired, created, done, periods)
        except Exception:
            LOG.exception("enrichment cycle failed")
        finally:
            db.close()
        time.sleep(interval)


def embed_query(base_url: str, model: str, query: str, timeout: float = 3) -> list[float]:
    return post(base_url, "/api/embed", {"model": model, "input": query}, timeout=timeout).get("embeddings", [[]])[0]
