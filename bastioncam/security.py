from __future__ import annotations

import hashlib
import re

try:
    from detect_secrets.core.scan import scan_line
    from detect_secrets.settings import default_settings
except ImportError:  # Safe fallback for maintenance before dependencies exist.
    scan_line = None
    default_settings = None

REDACTED = "[REDACTED]"
PEM = re.compile(r"-----BEGIN [^-]*(?:PRIVATE KEY|CERTIFICATE)-----.*?-----END [^-]*(?:PRIVATE KEY|CERTIFICATE)-----", re.S)
ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|token|secret|api[_-]?key|client[_-]?secret|access[_-]?key)\b\s*[=:]\s*)(['\"]?)([^\s'\"]+)(\2)"
)
AUTH = re.compile(r"(?i)(\b(?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+)(\S+)")
KNOWN = [
    re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\b(?:sk|pk)-(?:live|test)?-?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
KEY_NAMES = {"password", "passwd", "token", "secret", "authorization", "api_key", "apikey"}


def redact_text(text: str) -> str:
    if not text:
        return text
    text = PEM.sub("[REDACTED PEM BLOCK]", text)
    output: list[str] = []
    context = default_settings() if default_settings else None
    if context:
        settings = context.__enter__()
        settings.disable_plugins("Base64HighEntropyString", "HexHighEntropyString", "IPPublicDetector")
    try:
        for line in text.splitlines(keepends=True):
            values: set[str] = set()
            if scan_line:
                for finding in scan_line(line):
                    value = finding.secret_value
                    if len(value) >= 8 and value.lower() not in KEY_NAMES and "=" not in value:
                        values.add(value)
            for pattern in KNOWN:
                values.update(match.group(0) for match in pattern.finditer(line))
            for value in sorted(values, key=len, reverse=True):
                line = line.replace(value, REDACTED)
            line = ASSIGNMENT.sub(lambda m: m.group(1) + m.group(2) + REDACTED + m.group(4), line)
            line = AUTH.sub(lambda m: m.group(1) + REDACTED, line)
            output.append(line)
    finally:
        if context:
            context.__exit__(None, None, None)
    return "".join(output)


def scrub_database(db) -> dict[str, int]:
    counts = {"snapshots": 0, "segments": 0, "panes": 0, "period_summaries": 0}
    db.execute("BEGIN IMMEDIATE")
    try:
        for row in db.execute("SELECT id,content FROM snapshots").fetchall():
            clean = redact_text(row["content"])
            if clean != row["content"]:
                digest = hashlib.sha256(clean.encode()).hexdigest()
                db.execute("UPDATE snapshots SET content=?,content_hash=?,summary=NULL,embedding=NULL WHERE id=?",
                           (clean, digest, row["id"])); counts["snapshots"] += 1
        for row in db.execute("SELECT id,source_text,summary FROM segments").fetchall():
            source = redact_text(row["source_text"]); summary = redact_text(row["summary"] or "")
            if source != row["source_text"] or summary != (row["summary"] or ""):
                db.execute("UPDATE segments SET source_text=?,summary=NULL,embedding=NULL,status='retry',error=NULL WHERE id=?",
                           (source, row["id"])); counts["segments"] += 1
        for row in db.execute("SELECT id,title,command,cwd FROM panes").fetchall():
            values = tuple(redact_text(row[key]) for key in ("title", "command", "cwd"))
            if values != (row["title"], row["command"], row["cwd"]):
                db.execute("UPDATE panes SET title=?,command=?,cwd=? WHERE id=?", (*values, row["id"])); counts["panes"] += 1
        counts["period_summaries"] = db.execute("SELECT count(*) FROM period_summaries").fetchone()[0]
        db.execute("DELETE FROM period_summaries")
        db.commit()
    except Exception:
        db.rollback(); raise
    return counts
