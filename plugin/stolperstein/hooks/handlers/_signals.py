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
    # HTTP status strings
    re.compile(r"\b(?:HTTP[/ ])?[45]\d{2}\b(?:\s+\w+)?"),
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
