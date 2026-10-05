"""Explicit data minimization at the report boundary."""
from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Any


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()
                if k.lower() not in {"api_key", "authorization", "cookie", "set-cookie", "proxy", "base_url"}}
    if isinstance(value, list):
        return [redact(x, secrets) for x in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            for form in (secret, urllib.parse.quote(secret, safe=""),
                         base64.b64encode(secret.encode()).decode()):
                value = value.replace(form, "[REDACTED]")
    value = re.sub(r"\b(?:sk|sess)-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
    value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value)
    value = re.sub(r"https?://[^\s\"'<>]+", "[URL]", value)
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n\"'<>]+", "[LOCAL_PATH]", value)
    value = re.sub(r"/(?:home|Users|mnt/[a-z])/[^\s\"'<>]+", "[LOCAL_PATH]", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", value)
    return value


def private_report(report: dict, secrets: tuple[str, ...] = ()) -> dict:
    # Copy: scrubbing must not mutate the live conversation/tool context.
    return redact(json.loads(json.dumps(report, ensure_ascii=False)), secrets)
