"""Tests for the per-finding comment thread (t_32edb612).

The comment thread lets a biller ask "why is this flagged?" or "I
disagree — what's the appeal basis?" on any finding. Every comment
is also a FeedbackEntry(action="comment") in the feedback log so
the per_clinic_f1 rollup and the audit_actions chain see it. This
module covers the four cases the task spec calls out:

  1. POST a top-level comment.
  2. POST a reply (parent_comment_id).
  3. GET the thread — comments come back in created_at order.
  4. Comment writes to the feedback log (action="comment").

The test suite exercises both the FeedbackStore helper API
(:func:`add_comment` / :func:`list_comments`) and the HTTP
endpoints in :mod:`ai_billing_audit.api` so a future regression
that breaks one path but not the other is still caught.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from ai_billing_audit.clinical_note_storage import read_encrypted_json_records

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Import the module (not the names) so tests can resolve the
# currently-loaded class. Some sibling tests do
# ``importlib.reload(fb_mod)`` to point the feedback log at a tmp
# path; reloading re-creates the ``Comment`` and ``FeedbackEntry``
# classes, so a top-level ``from ... import Comment`` reference
# would mismatch ``isinstance(obj, Comment)`` for objects built
# by the reloaded module. Going through ``fb_mod.Comment`` keeps
# the check live.
from ai_billing_audit import feedback as _fb  # noqa: E402
from ai_billing_audit.feedback import (  # noqa: E402
    CommentStore,
    FeedbackStore,
    add_comment,
    list_comments,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fb_log(tmp_path: Path) -> Path:
    return tmp_path / "feedback.jsonl"


@pytest.fixture()
def comments_log(tmp_path: Path) -> Path:
    return tmp_path / "finding_comments.jsonl"


@pytest.fixture()
def store(fb_log: Path) -> FeedbackStore:
    return FeedbackStore(log_path=fb_log)


# ``Comment`` and ``FeedbackEntry`` resolved at call time so a
# ``importlib.reload(fb_mod)`` from a sibling test doesn't make
# the ``isinstance`` checks fail.
def Comment() -> type:  # noqa: N802 — mirrors dataclass name
    return _fb.Comment


def FeedbackEntry() -> type:  # noqa: N802
    return _fb.FeedbackEntry


# ---------------------------------------------------------------------------
# 1. POST a top-level comment
# ---------------------------------------------------------------------------


def test_add_top_level_comment_writes_to_comments_log(
    store: FeedbackStore, comments_log: Path
) -> None:
    """add_comment returns a Comment with a fresh id, no parent, and
    persists exactly one line to the comments log."""
    comment, entry = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="Why is this flagged?",
        comments_log=comments_log,
    )
    assert isinstance(comment, Comment())
    assert comment.comment_id
    assert comment.encounter_id == "enc-1"
    assert comment.finding_id == "f-1"
    assert comment.author_id == "biller-A"
    assert comment.body == "Why is this flagged?"
    assert comment.parent_comment_id is None
    assert comment.created_at  # ISO timestamp populated
    # The comments log exists and has exactly one line.
    assert comments_log.is_file()
    assert b"Why is this flagged?" not in comments_log.read_bytes()
    rows = read_encrypted_json_records(comments_log)
    assert len(rows) == 1
    assert rows[0]["comment_id"] == comment.comment_id
    assert rows[0]["body"] == "Why is this flagged?"
    assert rows[0]["parent_comment_id"] is None


def test_add_top_level_comment_writes_feedback_entry(
    store: FeedbackStore, comments_log: Path
) -> None:
    """The paired FeedbackEntry has action='comment' and lives in the
    feedback log (so it shows up in per_clinic_f1 and the audit chain)."""
    _comment, entry = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="Why is this flagged?",
        comments_log=comments_log,
    )
    assert isinstance(entry, FeedbackEntry())
    assert entry.action == "comment"
    assert entry.encounter_id == "enc-1"
    assert entry.finding_id == "f-1"
    assert entry.biller_id == "biller-A"
    # The body is folded into ``note`` so the chain carries the gist
    # without needing to join the comments log.
    assert entry.note == "Why is this flagged?"
    # And it's persisted in the feedback store.
    rows = store.read_for_encounter("enc-1")
    assert len(rows) == 1
    assert rows[0].action == "comment"
    assert rows[0].note == "Why is this flagged?"


# ---------------------------------------------------------------------------
# 2. POST a reply (parent_comment_id)
# ---------------------------------------------------------------------------


def test_add_reply_sets_parent_comment_id(
    store: FeedbackStore, comments_log: Path
) -> None:
    """A reply carries the parent's comment_id and round-trips it."""
    parent, _e1 = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="Why is this flagged?",
        comments_log=comments_log,
    )
    reply, _e2 = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="auditor-1",
        body="Because documentation gaps in HPI.",
        parent_comment_id=parent.comment_id,
        comments_log=comments_log,
    )
    assert reply.parent_comment_id == parent.comment_id
    assert reply.author_id == "auditor-1"
    assert reply.body == "Because documentation gaps in HPI."
    # Comment ids are distinct.
    assert reply.comment_id != parent.comment_id


def test_add_reply_writes_paired_feedback_entry(
    store: FeedbackStore, comments_log: Path
) -> None:
    """The reply also creates a paired FeedbackEntry(action='comment')."""
    parent, _ = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="Why is this flagged?",
        comments_log=comments_log,
    )
    _reply, entry = add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="auditor-1",
        body="Because documentation gaps in HPI.",
        parent_comment_id=parent.comment_id,
        comments_log=comments_log,
    )
    assert entry.action == "comment"
    # Two feedback rows for the encounter (one per comment).
    rows = store.read_for_encounter("enc-1")
    assert len(rows) == 2
    assert all(r.action == "comment" for r in rows)


# ---------------------------------------------------------------------------
# 3. GET the thread in order
# ---------------------------------------------------------------------------


def test_list_comments_returns_thread_in_created_at_order(
    store: FeedbackStore, comments_log: Path
) -> None:
    """list_comments returns all comments for a finding, oldest first.

    Append order is the secondary tiebreak, so the test is
    deterministic without sleeping between writes.
    """
    cstore = CommentStore(log_path=comments_log)
    cstore.add(
        encounter_id="enc-1", finding_id="f-1", author_id="biller-A", body="First"
    )
    cstore.add(
        encounter_id="enc-1", finding_id="f-1", author_id="biller-B", body="Second"
    )
    cstore.add(
        encounter_id="enc-1", finding_id="f-1", author_id="biller-A", body="Third"
    )
    thread = cstore.list_for_finding("enc-1", "f-1")
    assert [c.body for c in thread] == ["First", "Second", "Third"]


def test_list_comments_filters_by_encounter_and_finding(
    store: FeedbackStore, comments_log: Path
) -> None:
    """A comment on a different encounter or finding is not in the thread."""
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="enc1/f1",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-2",
        author_id="biller-A",
        body="enc1/f2",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-2",
        finding_id="f-1",
        author_id="biller-A",
        body="enc2/f1",
        comments_log=comments_log,
    )
    thread = list_comments(store, "enc-1", "f-1", comments_log=comments_log)
    assert [c.body for c in thread] == ["enc1/f1"]


def test_list_comments_empty_for_unknown_finding(
    store: FeedbackStore, comments_log: Path
) -> None:
    """A finding with no comments returns an empty list, not a 500."""
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="hi",
        comments_log=comments_log,
    )
    thread = list_comments(store, "enc-1", "f-UNKNOWN", comments_log=comments_log)
    assert thread == []


def test_list_comments_round_trip_through_store_helper(
    store: FeedbackStore, comments_log: Path
) -> None:
    """End-to-end: add_comment then list_comments via the store helper."""
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="A",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-B",
        body="B",
        comments_log=comments_log,
    )
    thread = list_comments(store, "enc-1", "f-1", comments_log=comments_log)
    assert [c.body for c in thread] == ["A", "B"]


# ---------------------------------------------------------------------------
# 4. Comment writes to feedback log
# ---------------------------------------------------------------------------


def test_feedback_log_grows_by_one_per_comment(
    store: FeedbackStore, comments_log: Path
) -> None:
    """Each add_comment call appends one row to the feedback log."""
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="A",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-2",
        author_id="biller-B",
        body="B",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-2",
        finding_id="f-1",
        author_id="biller-C",
        body="C",
        comments_log=comments_log,
    )
    rows = store.read_all()
    assert len(rows) == 3
    assert all(r.action == "comment" for r in rows)
    # stats() recognises the new action literal.
    s = store.stats()
    assert s["by_action"].get("comment") == 3
    assert s["total"] == 3


def test_comment_feedback_entries_link_into_hash_chain(
    store: FeedbackStore, comments_log: Path
) -> None:
    """Comments written via add_comment are part of the existing
    hash chain — verify_chain passes for a log full of comments."""
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-1",
        author_id="biller-A",
        body="A",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-1",
        finding_id="f-2",
        author_id="biller-B",
        body="B",
        comments_log=comments_log,
    )
    add_comment(
        store,
        encounter_id="enc-2",
        finding_id="f-1",
        author_id="biller-C",
        body="C",
        comments_log=comments_log,
    )
    assert store.verify_chain() is True


def test_feedback_entry_action_literal_includes_comment() -> None:
    """The FeedbackAction Literal explicitly includes 'comment'."""
    # The Literal is captured at runtime as a typing union; a direct
    # ``Action == "comment"`` check after dataclass construction is
    # the spec'd contract the rest of the codebase relies on.
    # ``FeedbackEntry`` is resolved at call time so a
    # ``importlib.reload(fb_mod)`` from a sibling test doesn't leave
    # the test referring to a stale class.
    e = FeedbackEntry()(
        encounter_id="enc-1",
        finding_id="f-1",
        action="comment",  # type: ignore[arg-type]
        severity="",
        rule_id="",
        category="",
    )
    assert e.action == "comment"
    # And an invalid action still raises (the validator wasn't relaxed).
    with pytest.raises(ValueError):
        FeedbackEntry()(
            encounter_id="enc-1",
            finding_id="f-1",
            action="banana",  # type: ignore[arg-type]
            severity="",
            rule_id="",
            category="",
        )


# ---------------------------------------------------------------------------
# 5. HTTP endpoints (api.py)
# ---------------------------------------------------------------------------


def _build_test_client(  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    fb_log: Path,
    comments_log: Path,
):
    """Build a FastAPI TestClient with isolated log paths.

    The bearer middleware reads ``AUDIT_ALLOW_NO_AUTH`` at
    ``create_app()`` time, so we set the env BEFORE calling the
    factory. ``get_default_store()`` is the singleton the API
    uses — we replace it with a fresh ``FeedbackStore`` pointed
    at ``fb_log`` so test feedback rows never touch the prod
    log. The comment helpers pick up ``comments_log`` via the
    explicit ``comments_log=`` argument.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "")
    import ai_billing_audit.feedback as _fb

    store = FeedbackStore(log_path=fb_log)
    monkeypatch.setattr(_fb, "get_default_store", lambda: store)
    # The per-path comment-store cache is keyed on the resolved
    # log path; flush it so any earlier test can't poison ours.
    monkeypatch.setattr(_fb, "_feedback_comment_stores", {})

    from fastapi.testclient import TestClient
    from ai_billing_audit.api import create_app

    return TestClient(create_app())


def test_post_top_level_comment_via_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST /encounter/.../finding/.../comments adds a top-level comment."""
    client = _build_test_client(
        monkeypatch,
        fb_log=tmp_path / "feedback.jsonl",
        comments_log=tmp_path / "finding_comments.jsonl",
    )
    resp = client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={
            "author_id": "biller-A",
            "body": "Why is this flagged?",
        },
    )
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["ok"] is True
    c = body["comment"]
    assert c["comment_id"]
    assert c["encounter_id"] == "enc-1"
    assert c["finding_id"] == "f-1"
    assert c["author_id"] == "biller-A"
    assert c["body"] == "Why is this flagged?"
    assert c["parent_comment_id"] is None
    assert body["feedback_event_id"]


def test_post_reply_via_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """POST with parent_comment_id creates a reply."""
    client = _build_test_client(
        monkeypatch,
        fb_log=tmp_path / "feedback.jsonl",
        comments_log=tmp_path / "finding_comments.jsonl",
    )
    # Top-level first.
    r1 = client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={"author_id": "biller-A", "body": "Why is this flagged?"},
    )
    parent_id = r1.json()["comment"]["comment_id"]
    # Reply.
    r2 = client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={
            "author_id": "auditor-1",
            "body": "Because documentation gaps in HPI.",
            "parent_comment_id": parent_id,
        },
    )
    assert r2.status_code == 200
    reply = r2.json()["comment"]
    assert reply["parent_comment_id"] == parent_id
    assert reply["author_id"] == "auditor-1"


def test_get_thread_via_api_returns_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GET /encounter/.../finding/.../comments returns the thread, oldest first."""
    client = _build_test_client(
        monkeypatch,
        fb_log=tmp_path / "feedback.jsonl",
        comments_log=tmp_path / "finding_comments.jsonl",
    )
    client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={"author_id": "biller-A", "body": "First"},
    )
    client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={"author_id": "biller-B", "body": "Second"},
    )
    resp = client.get("/encounter/enc-1/finding/f-1/comments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [c["body"] for c in body["comments"]] == ["First", "Second"]


def test_post_comment_rejects_empty_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST with an empty body returns 400, not a 500."""
    client = _build_test_client(
        monkeypatch,
        fb_log=tmp_path / "feedback.jsonl",
        comments_log=tmp_path / "finding_comments.jsonl",
    )
    resp = client.post(
        "/encounter/enc-1/finding/f-1/comments",
        json={"author_id": "biller-A", "body": ""},
    )
    assert resp.status_code == 400


def test_get_thread_empty_for_new_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GET on a finding with no comments returns an empty thread, not a 500."""
    client = _build_test_client(
        monkeypatch,
        fb_log=tmp_path / "feedback.jsonl",
        comments_log=tmp_path / "finding_comments.jsonl",
    )
    resp = client.get("/encounter/enc-1/finding/f-1/comments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["comments"] == []
