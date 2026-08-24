"""Firstmate /stow extract: inspect-then-update routing, no new tools."""

from __future__ import annotations

import pytest

from hermes_memory_provider.stow_route import (
    bind_write_id,
    classify,
    decide_write,
    mutation_metadata,
    plan_mutation,
    route,
    sleep_mutations,
)


def test_preference_goes_to_canonical():
    dest = route("preference", "User prefers uv run and python3, not pip.")
    assert dest.dest == "mnemosyne_canonical"
    assert dest.write == "inspect_then_update"
    assert dest.category == "preference"


def test_project_fact_needs_existing_agents():
    missing = route("project_fact", "Tests run via uv run pytest.", project_agents_exists=False)
    assert missing.dest == "unfiled"
    assert missing.write == "none"
    present = route("project_fact", "Tests run via uv run pytest.", project_agents_exists=True)
    assert present.dest == "project_agents"
    assert present.write == "inspect_then_update"


def test_next_step_is_todo_not_memory():
    dest = route("next_step", "Finish the stow extract docs.")
    assert dest.dest == "session_todo"


def test_ephemeral_is_skip_even_when_labeled_preference():
    dest = route("preference", "PR #843 is MERGEABLE. Phase 3 done.")
    assert dest.dest == "skip"
    assert classify("preference", "api_key=hunter2") == "skip"


def test_external_only_when_user_said_so():
    dest = route(
        "next_step",
        "File the follow-up on the board.",
        user_said_external=True,
    )
    assert dest.dest == "explicit_external"


def test_never_routes_to_firstmate_or_stow_notes():
    dest = route("operational", "Watch patterns cannot be changed after start.")
    assert dest.dest == "mnemosyne_working"
    assert dest.dest not in {".stow-notes.md", "captain.md", "learnings.md"}


def test_inspect_then_update_rewrites_overlap():
    existing = [{"id": "wm-1", "body": "User prefers python, not pip."}]
    decision = decide_write(
        "User prefers python, not pip. Prefer uv run over pip.",
        existing,
    )
    assert decision.action == "update"
    assert decision.memory_id == "wm-1"


def test_inspect_then_update_skips_exact_duplicate():
    existing = [{"id": "wm-1", "content": "User prefers uv run."}]
    decision = decide_write("  User   prefers uv run. ", existing)
    assert decision.action == "skip_duplicate"
    assert decision.memory_id == "wm-1"


def test_inspect_then_update_creates_when_unrelated():
    existing = [{"id": "wm-1", "body": "Desk agent is Gregor."}]
    decision = decide_write("User prefers conventional commits.", existing)
    assert decision.action == "create"


def test_unknown_kind_fails_loudly():
    with pytest.raises(ValueError, match="Unknown stow kind"):
        classify("vibes", "something durable")


def test_create_requires_evidence():
    decision = decide_write("User prefers conventional commits.", [])
    with pytest.raises(ValueError, match="requires evidence"):
        plan_mutation(decision, new_body="User prefers conventional commits.", evidence="")


def test_create_binds_invalidate_id():
    decision = decide_write("User prefers conventional commits.", [])
    planned = plan_mutation(
        decision,
        new_body="User prefers conventional commits.",
        evidence="Tim: use conventional commits",
    )
    assert planned.rollback == "invalidate"
    assert planned.rollback_id is None
    bound = bind_write_id(planned, "wm-9")
    assert bound.rollback_id == "wm-9"
    meta = mutation_metadata(bound)
    assert meta["evidence"] == "Tim: use conventional commits"
    assert meta["rollback_id"] == "wm-9"


def test_update_carries_before_and_restore_id():
    existing = [{"id": "wm-1", "body": "User prefers python, not pip."}]
    decision = decide_write(
        "User prefers python, not pip. Prefer uv run over pip.",
        existing,
    )
    planned = plan_mutation(
        decision,
        new_body="User prefers python, not pip. Prefer uv run over pip.",
        evidence="Tim: uv run, not pip",
        existing=existing,
    )
    assert planned.action == "update"
    assert planned.rollback == "restore"
    assert planned.rollback_id == "wm-1"
    assert planned.before == "User prefers python, not pip."
    assert mutation_metadata(planned)["before"] == planned.before


def test_skip_does_not_require_evidence():
    existing = [{"id": "wm-1", "content": "User prefers uv run."}]
    decision = decide_write("  User   prefers uv run. ", existing)
    planned = plan_mutation(decision, new_body="User prefers uv run.", evidence="")
    assert planned.action == "skip_duplicate"
    assert planned.rollback == "none"
    assert planned.rollback_id is None


def test_sleep_no_op_has_no_mutations():
    assert sleep_mutations({"status": "no_op", "message": "nothing"}) == []
    assert sleep_mutations({"status": "dry_run", "consolidated_ids": ["wm-1"]}) == []


def test_sleep_claims_are_reclaimable():
    mutations = sleep_mutations(
        {
            "status": "consolidated",
            "summaries_created": 1,
            "consolidated_ids": ["wm-1", "wm-2"],
        }
    )
    assert [m.rollback_id for m in mutations] == ["wm-1", "wm-2"]
    assert {m.rollback for m in mutations} == {"reclaim"}
    assert mutations[0].evidence.startswith("sleep consolidated")
