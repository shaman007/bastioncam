from __future__ import annotations

import json
import os
import re
import subprocess

from .security import redact_text


ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["zellij", *args], text=True, capture_output=True, timeout=10, check=False
    )


def sessions() -> list[str]:
    result = run("list-sessions", "--short")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def panes(session: str) -> list[dict]:
    result = run("--session", session, "action", "list-panes", "--all", "--json")
    if result.returncode != 0:
        return []
    try:
        value = json.loads(result.stdout)
        return value if isinstance(value, list) else value.get("panes", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def pane_key(pane: dict) -> str:
    raw = pane.get("pane_id", pane.get("id", ""))
    text = str(raw)
    return text if text.startswith(("terminal_", "plugin_")) else f"terminal_{text}"


def is_plugin(pane: dict) -> bool:
    """Handle both current and older Zellij list-panes JSON schemas."""
    if "is_plugin" in pane:
        return bool(pane["is_plugin"])
    return str(pane.get("pane_type", "terminal")).lower() == "plugin"


def dump(session: str, key: str) -> str | None:
    result = run("--session", session, "action", "dump-screen", "--full", "--pane-id", key)
    if result.returncode != 0:
        return None
    text = ANSI.sub("", result.stdout).replace("\x00", "")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return redact_text("\n".join(lines))


def field(pane: dict, *names: str) -> str:
    for name in names:
        value = pane.get(name)
        if value is not None:
            if isinstance(value, (list, dict)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)
    return ""
