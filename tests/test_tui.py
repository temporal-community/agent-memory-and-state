import io

import pytest

pytest.importorskip("rich")

from rich.console import Console

from refund_agent import tui
from refund_agent.naive_refund import _demo_frame


def test_agent_panel_starts_with_same_invitation_as_naive_demo(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 123))

    panel = tui._agent_panel("new-refund")

    assert "How can I help you?" in panel.renderable.plain
    assert "no context assembled; no memory retrieved" in panel.renderable.plain


def test_lost_agent_panel_points_to_durable_owners(monkeypatch) -> None:
    monkeypatch.setattr(tui, "_worker_alive", lambda: (False, 123))

    panel = tui._agent_panel("lost-refund")

    assert "LOST" in panel.renderable.plain
    assert "Temporal still owns execution progress" in panel.renderable.plain
    assert "effect owner still owns the refund outcome" in panel.renderable.plain


def test_stage_agent_returns_without_chat_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 123))

    panel = tui._stage_agent_panel("new-refund")

    assert "How can I help you?" in panel.renderable.plain
    assert "No conversation history" in panel.renderable.plain


def test_reloaded_agent_answers_without_a_new_customer_request(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))

    panel = tui._stage_agent_panel("existing-refund", recovered=True)

    assert panel.title == "RELOADED AGENT"
    assert "NO NEW CUSTOMER REQUEST" in panel.renderable.plain
    assert "existing refund" in panel.renderable.plain
    assert "Your refund is complete" in panel.renderable.plain


def test_stage_system_view_makes_the_payoff_glanceable() -> None:
    panel = tui._stage_system_view(
        status="COMPLETED",
        refund={"calls": 2},
        pending_attempt=None,
        refund_step_completed=True,
    )

    assert "Refund step completed after recovery" in panel.renderable.plain
    assert "2 CALLS  →  1 REFUND" in panel.renderable.plain
    assert "No duplicate" in panel.renderable.plain


def test_naive_restart_returns_to_a_blank_conversation() -> None:
    frame = _demo_frame(
        {"_restarted": True},
        [{"refund_id": "r1", "order": "1234", "amount": 8000}],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "How can I help you?" in text
    assert "REPLACEMENT WORKER" in text
    assert "A new session has started" in text
    assert "previous conversation is gone" in text
    assert "AFTER REPLACEMENT" in text
    assert "WHAT WENT WRONG" not in text
    assert "Type your refund request at the you> prompt" in text


def test_naive_first_refund_holds_on_the_agent_reply() -> None:
    frame = _demo_frame(
        {
            "user_message": "Please refund my plush python",
            "context": {"order": "1234", "amount": 8000, "customer": "42"},
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "_effect_unrecorded": True,
        },
        [{"refund_id": "r1", "order": "1234", "amount": 8000}],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "Please refund my plush python" in text
    assert "Refund issued." in text
    assert "REFUND ISSUED" in text
    assert "Press Enter to replace this Worker" in text
    assert "crash" not in text.lower()
