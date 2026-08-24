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
from typing import Any, Iterable, Mapping, Sequence

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


@dataclass(frozen=True)
class StowMutation:
    """One intended write, with evidence and a rollback verb.

    Prime Agent /refine analog. No new Hermes tool — the skill applies
    the write through existing remember/update/invalidate/reclaim.
    """

    action: str
    evidence: str
    after: str | None = None
    before: str | None = None
    memory_id: str | None = None
    rollback_id: str | None = None
    rollback: str = "none"  # invalidate | restore | reclaim | none


def _existing_body(
    memory_id: str | None,
    existing: Sequence[Mapping[str, str]] | Iterable[Mapping[str, str]] | None,
) -> str | None:
    if not memory_id:
        return None
    for row in list(existing or []):
        mid = row.get("id") or row.get("memory_id")
        if mid == memory_id:
            return normalize_body(row.get("body") or row.get("content") or "") or None
    return None


def plan_mutation(
    decision: WriteDecision,
    *,
    new_body: str,
    evidence: str,
    existing: Sequence[Mapping[str, str]] | Iterable[Mapping[str, str]] | None = None,
) -> StowMutation:
    """Attach evidence + rollback verb to a decide_write result."""
    ev = (evidence or "").strip()
    after = normalize_body(new_body) or None
    if decision.action in {"create", "update"} and not ev:
        raise ValueError("stow write requires evidence")
    before = _existing_body(decision.memory_id, existing)
    if decision.action == "create":
        return StowMutation(
            action="create",
            evidence=ev,
            after=after,
            rollback="invalidate",
        )
    if decision.action == "update":
        return StowMutation(
            action="update",
            evidence=ev,
            after=after,
            before=before,
            memory_id=decision.memory_id,
            rollback_id=decision.memory_id,
            rollback="restore",
        )
    return StowMutation(
        action=decision.action,
        evidence=ev,
        after=after,
        before=before,
        memory_id=decision.memory_id,
        rollback="none",
    )


def bind_write_id(mutation: StowMutation, memory_id: str) -> StowMutation:
    """Fill rollback_id after remember/update returns an id."""
    mid = (memory_id or "").strip()
    if not mid:
        raise ValueError("write id is required")
    rollback_id = mid if mutation.rollback != "none" else None
    return StowMutation(
        action=mutation.action,
        evidence=mutation.evidence,
        after=mutation.after,
        before=mutation.before,
        memory_id=mid,
        rollback_id=rollback_id,
        rollback=mutation.rollback,
    )


def mutation_metadata(mutation: StowMutation) -> dict[str, str]:
    """Fields to store on the memory row. Keep small."""
    meta = {"evidence": mutation.evidence, "rollback": mutation.rollback}
    if mutation.rollback_id:
        meta["rollback_id"] = mutation.rollback_id
    if mutation.before:
        meta["before"] = mutation.before
    return meta


def sleep_mutations(sleep_result: Mapping[str, Any]) -> list[StowMutation]:
    """Map beam.sleep() output to reclaimable IDs. Does not change sleep."""
    status = str(sleep_result.get("status") or "")
    if status in {"no_op", "dry_run"}:
        return []
    ids = sleep_result.get("consolidated_ids") or []
    if not isinstance(ids, (list, tuple)):
        return []
    evidence = f"sleep {status} summaries={sleep_result.get('summaries_created', 0)}"
    out: list[StowMutation] = []
    for mid in ids:
        if not mid:
            continue
        sid = str(mid)
        out.append(
            StowMutation(
                action="sleep_claim",
                evidence=evidence,
                memory_id=sid,
                rollback_id=sid,
                rollback="reclaim",
            )
        )
    return out
