from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from .llm import post


TIME_SCHEMA = {
    "type": "object",
    "properties": {
        "search_text": {"type": "string"},
        "start": {"type": ["string", "null"]},
        "end": {"type": ["string", "null"]},
        "interpretation": {"type": ["string", "null"]},
    },
    "required": ["search_text", "start", "end", "interpretation"],
}


def _utc(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("time parser returned a timestamp without timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_query(query: str, timezone_name: str = "Europe/Prague", *,
                now: datetime | None = None,
                request: Callable[..., dict] = post) -> tuple[str, str | None, str | None, str | None]:
    """Let the local model extract an arbitrary natural-language time range."""
    local_now = now or datetime.now(ZoneInfo(timezone_name))
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo(timezone_name))
    prompt = f"""Parse a multilingual terminal-history search query. The current time is
{local_now.isoformat(timespec='seconds')} in the {timezone_name} time zone. Separate the content search
text from every natural-language time expression. Always write interpretation in English.
Return an absolute half-open [start, end) interval as ISO 8601 timestamps with time-zone offsets.

Rules:
- "an hour ago" and "during the last hour" mean current time minus one hour through current time.
- "yesterday" means the entire previous calendar day in the specified time zone.
- Support weekdays, parts of a day, N minutes/hours/days ago, last week/month, dates, and ranges in any language.
- Remove time expressions from search_text, leaving only terms that should be matched against terminal content.
- If the query has no time expression, start, end, and interpretation must be null.
- Never invent search terms.

Examples at 2025-01-15T12:00:00+01:00:
- "codex an hour ago" -> search_text "codex", start 2025-01-15T11:00:00+01:00,
  end 2025-01-15T12:00:00+01:00, interpretation "last hour".
- "error yesterday" -> search_text "error", start 2025-01-14T00:00:00+01:00,
  end 2025-01-15T00:00:00+01:00, interpretation "yesterday".
- "cargo build" -> search_text "cargo build" and all other fields null.

Query: {query}
"""
    try:
        response = request("http://127.0.0.1:11434", "/api/generate", {
            "model": "qwen3:4b", "prompt": prompt, "stream": False,
            "think": False,
            "format": TIME_SCHEMA,
            "options": {"temperature": 0, "num_predict": 180},
            "keep_alive": "5m",
        }, timeout=12)
        value = json.loads(response.get("response", "{}"))
        text = " ".join(str(value.get("search_text") or "").split())
        start, end = _utc(value.get("start")), _utc(value.get("end"))
        if (start is None) != (end is None) or (start and start >= end):
            raise ValueError("invalid time interval")
        interpretation = value.get("interpretation")
        if not start and interpretation:
            raise ValueError("interpretation without time interval")
        return text, start, end, interpretation
    except Exception:
        # Search remains usable if Ollama is temporarily unavailable.
        return query.strip(), None, None, None


def fts_expression(text: str) -> str:
    words = re.findall(r"[\w.-]+", text, re.UNICODE)
    return " AND ".join('"' + word.replace('"', '""') + '"' for word in words)
