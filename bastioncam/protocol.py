from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


PROTOCOL_VERSION = 1
MIN_PROTOCOL_VERSION = 1
MAX_PROTOCOL_VERSION = 1


def collector_version() -> str:
    try:
        return version("bastioncam")
    except PackageNotFoundError:
        return "0.1.0+source"


def compatibility_error(protocol_version: int) -> str:
    if protocol_version < MIN_PROTOCOL_VERSION:
        return f"collector protocol {protocol_version} is too old; server requires {MIN_PROTOCOL_VERSION}"
    if protocol_version > MAX_PROTOCOL_VERSION:
        return f"collector protocol {protocol_version} is newer than server maximum {MAX_PROTOCOL_VERSION}"
    return ""
