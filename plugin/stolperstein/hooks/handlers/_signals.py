"""Structured error-signal detection.

Returns True on a real error indicator — exception class, non-zero exit
code mention, HTTP status, traceback, or explicit error-tag prefix. Does
NOT match bare conversational lowercase words (`error`, `failed`,
`denied`, etc.) because those false-positive on normal prose.

Per-project override: `STOLPERSTEIN_ERROR_PATTERNS` env var (JSON array
of regex strings) replaces the default set.
"""

from __future__ import annotations

import json
import os
import re

# Ordered list of regexes. Case-sensitive where casing is a real signal.
_DEFAULT_PATTERNS: list[re.Pattern[str]] = [
    # Exception class names: CamelCase with Error/Exception suffix.
    re.compile(r"\b(?:[A-Z][a-zA-Z]+(?:Error|Exception|Warning))\b"),
    # Specific common errors that don't follow the Error/Exception suffix pattern
    re.compile(r"\b(?:Traceback|NullPointerException|OutOfMemoryError|SegmentationFault)\b"),
    # Traceback / stack trace markers
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\bat\s+\S+\s*\(\S*:\d+(:\d+)?\)"),
    # Non-zero exit code mentions
    re.compile(r"\b(?:exit(?:\s+code|ed\s+with)?|error\s+code)\s+(?:[1-9]\d*)\b", re.I),
    re.compile(r"\bexited non[- ]?zero\b", re.I),
    # HTTP 4xx/5xx status — only WITH context. A bare 400–599 number is
    # most often a byte count, line number, or record count ("545" in an
    # ls listing triggered the error path live), so the number alone is
    # never enough: it needs an HTTP-ish prefix or an RFC reason phrase.
    re.compile(
        r"""
        (?:
            # Prefix context: "HTTP 403", "HTTP/1.1 500", "http 404",
            # "status 502", "status code 503", "error 404", "returned 500".
            # Curated verbs only — "processed 404 records" must NOT match.
            \b(?:HTTP(?:/\d(?:\.\d)?)?|status(?:\s+code)?|error|returned)\s+[45]\d{2}\b
            |
            # Arrow context from pretty request logs: "GET /api/foo → 404".
            # Unicode arrow only — ASCII "->" is everywhere in benign
            # output ("downloading -> 450 KB/s", "step 3 -> 500 items").
            →\s*[45]\d{2}\b
            |
            # Suffix context: curated RFC reason phrases — "404 Not Found",
            # "502 Bad Gateway", "500 Internal Server Error", ...
            \b[45]\d{2}\s+(?:
                Bad\ Request|Unauthorized|Forbidden|Not\ Found
                |Method\ Not\ Allowed|Request\ Timeout|Conflict|Gone
                |Too\ Many\ Requests|Internal\ Server\ Error|Not\ Implemented
                |Bad\ Gateway|Service\ Unavailable|Gateway\ Timeout
            )\b
        )
        """,
        re.I | re.X,
    ),
    # Explicit error-tag prefixes at line start or on their own token.
    re.compile(r"(?:^|\n|\s)(?:fatal|panic|ERROR|FAILED):", re.M),
    re.compile(r"^Error:\s", re.M),
]


def _compile_patterns_from_env() -> list[re.Pattern[str]]:
    raw = os.environ.get("STOLPERSTEIN_ERROR_PATTERNS", "").strip()
    if not raw:
        return _DEFAULT_PATTERNS
    try:
        patterns = json.loads(raw)
        if not isinstance(patterns, list):
            return _DEFAULT_PATTERNS
        return [re.compile(p) for p in patterns if isinstance(p, str)]
    except (json.JSONDecodeError, re.error):
        return _DEFAULT_PATTERNS


def is_structured_error(text: str) -> bool:
    """Return True if `text` contains at least one structured error signal."""
    if not text:
        return False
    for pattern in _compile_patterns_from_env():
        if pattern.search(text):
            return True
    return False
