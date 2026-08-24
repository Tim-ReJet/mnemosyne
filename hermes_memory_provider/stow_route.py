"""Inspect-then-update routing for session stow (firstmate extract).

No new Hermes tools. The interactive skill classifies findings; this module
picks a destination and whether to update, create, or skip. Destinations are
existing surfaces only: Mnemosyne canonical/working, project AGENTS.md, or
the session todo list.

Never invents ``.stow-notes.md``, ``data/captain.md``, or an issue tracker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

KINDS = frozenset(
    {
        "preference",
        "identity",
        "environment",
        "project_fact",
        "operational",
        "next_step",
        "skip",
    }
)

CANONICAL_KINDS = frozenset({"preference", "identity", "environment"})

# Same family as model_refresh._EPHEMERAL_RE — kept local so the router
# stays importable without a live Beam.
_SKIP_RE = re.compile(
    r"("
    r"\bpr\s*#?\d+\b|\bissue\s*#?\d+\b|\bcommit\s+[0-9a-f]{7,}\b|"
    r"\b[0-9a-f]{12,}\b|\btemporary\b|\btransient\b|\bone[- ]off\b|"
    r"\bdebugging state\b|\btask progress\b|\bphase\s+\d+\s+done\b|"
    r"\bapi[_-]?key\b|\bpassword\b|\bsecret\b|\btoken\b"
    r")",
    re.IGNORECASE,
)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class StowRoute:
    dest: str
    write: str
    reason: str
    category: str | None = None


@dataclass(frozen=True)
class WriteDecision:
    action: str
    memory_id: str | None = None
    reason: str = ""


def normalize_body(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def is_skip_body(body: str) -> bool:
    return bool(_SKIP_RE.search(body or ""))


def classify(kind: str, body: str) -> str:
    """Validate the agent's kind. Ephemeral / secret bodies become skip."""
    if is_skip_body(body):
        return "skip"
    label = (kind or "").strip().lower()
    if label not in KINDS:
        known = ", ".join(sorted(KINDS))
        raise ValueError(f"Unknown stow kind {kind!r}. Expected one of: {known}")
    return label


def route(
    kind: str,
    body: str,
    *,
    project_agents_exists: bool = False,
    user_said_external: bool = False,
) -> StowRoute:
    """Pick a destination. Explicit user instruction is the only external path."""
    label = classify(kind, body)
    if label == "skip":
        return StowRoute("skip", "none", "ephemeral, secret, or classified skip")
    if user_said_external:
        return StowRoute(
            "explicit_external",
            "create",
            "user named an external tracker for this kind",
        )
    if label in CANONICAL_KINDS:
        return StowRoute(
            "mnemosyne_canonical",
            "inspect_then_update",
            "user-level durable slot",
            category=label,
        )
    if label == "project_fact":
        if project_agents_exists:
            return StowRoute(
                "project_agents",
                "inspect_then_update",
                "project-intrinsic fact belongs in existing AGENTS.md",
            )
        return StowRoute(
            "unfiled",
            "none",
            "no project AGENTS.md; do not invent one from stow",
        )
    if label == "operational":
        return StowRoute(
            "mnemosyne_working",
            "inspect_then_update",
            "fleet-local gotcha; inspect then update working memory",
        )
    if label == "next_step":
        return StowRoute("session_todo", "create", "undone work is a todo, not a memory")
    return StowRoute("skip", "none", "unhandled kind")


def decide_write(
    new_body: str,
    existing: Sequence[Mapping[str, str]] | Iterable[Mapping[str, str]],
) -> WriteDecision:
    """Inspect-then-update: rewrite an overlapping note; never append a twin."""
    incoming = normalize_body(new_body)
    if not incoming:
        return WriteDecision("skip_empty", reason="blank body")
    rows = list(existing)
    for row in rows:
        body = normalize_body(row.get("body") or row.get("content") or "")
        mid = row.get("id") or row.get("memory_id")
        if not body:
            continue
        if body == incoming:
            return WriteDecision("skip_duplicate", memory_id=mid, reason="exact match")
        if incoming in body or body in incoming:
            return WriteDecision("update", memory_id=mid, reason="overlapping note")
    return WriteDecision("create", reason="no existing note to rewrite")
