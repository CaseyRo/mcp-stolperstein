"""Extract candidate KUs from session summaries.

Primary: LLM-based extraction via OpenAI-compatible API (when configured).
Fallback: heuristic NLP extraction using text splitting and keyword classification.
"""

from __future__ import annotations

import json
import logging
import re

from stolperstein.models import KUKind, KUSeverity, ReflectCandidate

logger = logging.getLogger(__name__)

# ── LLM-based extraction ──────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a knowledge extraction engine for an experiential knowledge base.
Given a session summary from an AI coding agent, extract generalizable learnings
that would help a DIFFERENT agent on a DIFFERENT project in the future.

Rules:
- Only extract learnings that are transferable — skip project-specific decisions.
- Each candidate must have: summary (max 280 chars), detail, action (imperative),
  domains (technology tags, at least one), kind (pitfall|workaround|tool-recommendation),
  and generalizability_score (0.0-1.0).
- generalizability_score: 0.0 = only useful for this exact project,
  1.0 = universally useful across all projects.
- Optionally include: context_languages, context_frameworks, context_environment,
  context_pattern, severity (low|medium|high|critical, default medium).
- Return an empty array if there are no generalizable learnings.
- Be selective — quality over quantity. 3 good candidates beat 8 mediocre ones.

Respond with ONLY a JSON array of objects. No markdown, no explanation."""

_USER_TEMPLATE = """\
Extract generalizable knowledge units from this session summary:

{session_summary}

Return a JSON array where each element has:
- "summary": string (max 280 chars, concise description of the learning)
- "detail": string (full context of what happened and why it matters)
- "action": string (imperative — what to do when encountering this)
- "domains": string[] (technology tags like ["docker", "webhooks", "attio"], min 1)
- "kind": "pitfall" | "workaround" | "tool-recommendation"
- "generalizability_score": number 0.0-1.0
- Optional: "context_languages": string[], "context_frameworks": string[],
  "context_environment": string, "context_pattern": string,
  "severity": "low" | "medium" | "high" | "critical" """


async def _llm_extract(session_summary: str) -> list[ReflectCandidate] | None:
    """Extract candidates using an OpenAI-compatible chat completions API."""
    from stolperstein.config import settings

    if not settings.cq_llm_api_url:
        return None

    import httpx  # noqa: E402 — lazy import to avoid hard dep when unconfigured

    url = settings.cq_llm_api_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    llm_key = settings.cq_llm_api_key.get_secret_value()
    if llm_key:
        headers["Authorization"] = f"Bearer {llm_key}"

    payload = {
        "model": settings.cq_llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_TEMPLATE.format(session_summary=session_summary)},
        ],
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        raw = json.loads(content)
        if not isinstance(raw, list):
            logger.warning("LLM returned non-array: %s", type(raw))
            return None

        # Proposable kinds only — tool-gap-signal is emergent-only.
        proposable_kinds = {"pitfall", "workaround", "tool-recommendation"}
        valid_severities = {s.value for s in KUSeverity}
        candidates = []
        for item in raw:
            kind_val = item.get("kind", "pitfall")
            if kind_val not in proposable_kinds:
                kind_val = "pitfall"
            sev_val = item.get("severity", "medium")
            if sev_val not in valid_severities:
                sev_val = "medium"
            # Accept both `domains` (new) and `domain` (legacy from old LLM prompts).
            domains = item.get("domains") or item.get("domain") or ["general"]
            if not isinstance(domains, list) or not domains:
                domains = ["general"]
            candidates.append(
                ReflectCandidate(
                    summary=str(item.get("summary", ""))[:280],
                    detail=str(item.get("detail", "")),
                    action=str(item.get("action", "")),
                    domains=domains,
                    kind=KUKind(kind_val),
                    generalizability_score=max(0.0, min(1.0, float(item.get("generalizability_score", 0.5)))),
                    context_languages=item.get("context_languages") or [],
                    context_frameworks=item.get("context_frameworks") or [],
                    context_environment=item.get("context_environment"),
                    context_pattern=item.get("context_pattern"),
                    severity=KUSeverity(sev_val),
                )
            )

        candidates.sort(key=lambda c: c.generalizability_score, reverse=True)
        logger.info("LLM extracted %d candidates", len(candidates))
        return candidates

    except Exception:
        logger.warning("LLM extraction failed, falling back to heuristics", exc_info=True)
        return None


# ── Heuristic fallback ─────────────────────────────────────────────────

# Technology/domain keywords — lowercase
_DOMAIN_KEYWORDS: dict[str, str] = {
    "docker": "docker", "container": "docker", "dockerfile": "docker",
    "caddy": "caddy", "nginx": "nginx", "traefik": "traefik",
    "kubernetes": "kubernetes", "k8s": "kubernetes",
    "tailscale": "tailscale", "wireguard": "wireguard",
    "vercel": "vercel", "aws": "aws", "gcp": "gcp", "azure": "azure",
    "komodo": "komodo", "hetzner": "hetzner",
    "sqlite": "sqlite", "postgres": "postgres", "postgresql": "postgres",
    "redis": "redis", "mysql": "mysql", "neon": "neon",
    "python": "python", "node": "node", "deno": "deno", "bun": "bun",
    "typescript": "typescript", "javascript": "javascript",
    "rust": "rust", "go": "golang", "swift": "swift",
    "next.js": "nextjs", "nextjs": "nextjs", "react": "react",
    "fastapi": "fastapi", "django": "django", "flask": "flask",
    "express": "express", "hono": "hono",
    "rest": "rest", "graphql": "graphql", "webhook": "webhooks",
    "webhooks": "webhooks", "oauth": "oauth", "oidc": "oidc",
    "mcp": "mcp", "sse": "sse", "websocket": "websocket",
    "git": "git", "github": "github", "gitlab": "gitlab",
    "slack": "slack", "attio": "attio", "linear": "linear",
    "sentry": "sentry", "grafana": "grafana",
    "homeassistant": "homeassistant", "home assistant": "homeassistant",
    "zigbee": "zigbee", "mqtt": "mqtt",
    "keycloak": "keycloak", "clerk": "clerk", "hmac": "auth",
    "jwt": "auth", "api key": "auth",
    "dns": "dns", "tls": "tls", "ssl": "tls", "cors": "cors",
    "fts5": "sqlite", "sqlite-vec": "sqlite",
}

_KIND_SIGNALS: dict[KUKind, list[str]] = {
    KUKind.pitfall: [
        r"(?:silent(?:ly)?|quiet(?:ly)?)\s+fail",
        r"doesn't?\s+(?:work|log|error|return|throw)",
        r"(?:wrong|incorrect|unexpected|surprising)\s+(?:behavior|result|response|output|format)",
        r"(?:poorly|not well|barely)\s+documented",
        r"(?:easy|common)\s+to\s+(?:get wrong|miss|overlook|forget)",
        r"(?:mismatch|mismatched)",
        r"(?:caused|causes)\s+(?:\d+|4\d{2}|5\d{2})",
        r"(?:gotcha|trap|caveat|footgun)",
        r"invisible|unnoticed|hidden",
        r"no\s+(?:logging|error|warning|feedback)",
    ],
    KUKind.workaround: [
        r"(?:had to|need to|must|should)\s+(?:rewrite|add|change|update|switch|use)",
        r"(?:fix|solution|workaround|resolution|remedy)",
        r"(?:instead|rather)\s+(?:of|than)",
        r"(?:the\s+(?:fix|trick|solution)\s+(?:is|was))",
        r"rewrit(?:e|ten)",
    ],
    KUKind.tool_recommendation: [
        r"(?:use|try|switch to|recommend|prefer)\s+\w+",
        r"(?:better|easier|faster)\s+(?:with|using|than)",
        r"(?:tool|library|package|framework|service)\s+(?:that|which)",
    ],
    # gap-signal is emergent-only (not proposable) — gap-like language falls
    # through to `workaround` or `pitfall` below.
}

_SPECIFIC_SIGNALS = [
    r"\b(?:our|my|we|us)\b",
    r"\bthis\s+(?:project|repo|codebase|app)\b",
    r"\b(?:PR|MR)\s*#\d+\b",
    r"\b[a-f0-9]{7,40}\b",
]

_GENERAL_SIGNALS = [
    r"(?:any|every|all)\s+(?:project|app|service|developer|team)",
    r"(?:in general|generally|always|typically|commonly)",
    r"(?:best practice|anti-pattern|pattern|principle)",
    r"(?:documentation|docs)\s+(?:say|claim|state|don't mention|poorly)",
]


def _split_into_segments(text: str) -> list[str]:
    """Split a session summary into discrete issue/learning segments."""
    numbered = re.split(
        r"(?:^|\n)\s*(?:\*{0,2}\d+[\.\)]\s*\*{0,2}|[-*]\s+\*{2})",
        text,
    )
    numbered = [s.strip() for s in numbered if s.strip() and len(s.strip()) > 40]
    if len(numbered) >= 2:
        return numbered

    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 40]
    if len(paragraphs) >= 2:
        return paragraphs

    if len(text.strip()) > 60:
        return [text.strip()]
    return []


def _extract_domains(text: str) -> list[str]:
    text_lower = text.lower()
    found: set[str] = set()
    for keyword, domain in _DOMAIN_KEYWORDS.items():
        if keyword in text_lower:
            found.add(domain)
    return sorted(found) or ["general"]


def _classify_kind(text: str) -> KUKind:
    text_lower = text.lower()
    scores: dict[KUKind, int] = {k: 0 for k in _KIND_SIGNALS}
    for kind, patterns in _KIND_SIGNALS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                scores[kind] += 1
    if not scores:
        return KUKind.pitfall
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else KUKind.pitfall


def _score_generalizability(text: str) -> float:
    score = 0.5
    text_lower = text.lower()
    for pattern in _SPECIFIC_SIGNALS:
        if re.search(pattern, text_lower):
            score -= 0.1
    for pattern in _GENERAL_SIGNALS:
        if re.search(pattern, text_lower):
            score += 0.1
    domain_count = sum(1 for kw in _DOMAIN_KEYWORDS if kw in text_lower)
    if domain_count >= 2:
        score += 0.1
    if domain_count >= 4:
        score += 0.05
    if re.search(r"(?:whenever|every time|always|never|any time)", text_lower):
        score += 0.1
    if len(text) < 100:
        score -= 0.15
    return round(max(0.0, min(1.0, score)), 2)


def _extract_summary(text: str) -> str:
    # Bold header
    header = re.match(r"\*{2}([^*]+)\*{2}[:\s]*", text)
    if header:
        return header.group(1).strip()[:280]
    # First sentence
    match = re.match(r"([^.!?\n]{20,280}[.!?])", text)
    if match:
        return match.group(1).strip()
    first_line = text.split("\n")[0].strip()
    return first_line[:280] if len(first_line) <= 280 else first_line[:277] + "..."


def _extract_action(text: str) -> str:
    text_lower = text.lower()
    patterns = [
        r"(?:had to|need to|must|should)\s+(.{20,200}?)(?:\.|$|\n)",
        r"(?:the (?:fix|trick|solution) (?:is|was))\s+(.{10,200}?)(?:\.|$|\n)",
        r"(?:instead,?\s+)(.{10,200}?)(?:\.|$|\n)",
        r"(?:use|add|check|verify|ensure|configure|set|enable)\s+(.{10,200}?)(?:\.|$|\n)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            action = match.group(0).strip().rstrip(".")
            return action[0].upper() + action[1:]
    return "Verify this behavior in your environment before proceeding."


def _heuristic_extract(session_summary: str) -> list[ReflectCandidate]:
    """Extract candidate KUs using heuristic text analysis."""
    segments = _split_into_segments(session_summary)
    if not segments:
        return []

    candidates: list[ReflectCandidate] = []
    for segment in segments:
        detail = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", segment).strip()
        candidates.append(
            ReflectCandidate(
                summary=_extract_summary(segment),
                detail=detail,
                action=_extract_action(segment),
                domains=_extract_domains(segment),
                kind=_classify_kind(segment),
                generalizability_score=_score_generalizability(segment),
                severity=KUSeverity.medium,
            )
        )

    candidates.sort(key=lambda c: c.generalizability_score, reverse=True)
    return candidates


# ── Public API ─────────────────────────────────────────────────────────

async def reflect_with_dedup(
    session_summary: str,
    store: object | None = None,
) -> dict:
    """Extract candidates via LLM (preferred) or heuristics (fallback).

    Optionally dedup against existing KUs via embedding similarity.
    """
    # Try LLM extraction first
    candidates = await _llm_extract(session_summary)
    method = "llm"

    # Fall back to heuristics
    if candidates is None:
        candidates = _heuristic_extract(session_summary)
        method = "heuristic"

    if not candidates:
        return {
            "candidates": [],
            "message": "No generalizable learnings extracted from session summary.",
        }

    # Dedup against existing KUs via embedding similarity
    if store is not None:
        deduped = []
        for candidate in candidates:
            try:
                embedder = store._get_embedder()
                text = f"{candidate.summary} {candidate.detail}"
                embedding = await embedder.embed(text)
                if embedding:
                    from stolperstein.store import _serialize_f32

                    db = store._get_db()
                    rows = db.execute(
                        """
                        SELECT ku_id, distance
                        FROM ku_embeddings
                        WHERE embedding MATCH ?
                          AND k = 1
                        ORDER BY distance
                        """,
                        [_serialize_f32(embedding)],
                    ).fetchall()

                    if rows and rows[0]["distance"] < 0.15:
                        logger.info(
                            "Skipping duplicate candidate (sim=%.2f): %s",
                            1 - rows[0]["distance"],
                            candidate.summary[:60],
                        )
                        continue
            except Exception:
                logger.debug("Dedup check failed for candidate", exc_info=True)

            deduped.append(candidate)
        candidates = deduped

    return {
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "method": method,
        "message": f"Extracted {len(candidates)} candidate(s) via {method}. Call propose on any you want to keep.",
    }
