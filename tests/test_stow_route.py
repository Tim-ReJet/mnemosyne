"""Firstmate /stow extract: inspect-then-update routing, no new tools."""

from __future__ import annotations

import pytest

from hermes_memory_provider.stow_route import (
    classify,
    decide_write,
    route,
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
