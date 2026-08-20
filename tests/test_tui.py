import io

import pytest

pytest.importorskip("rich")

from rich.console import Console

from refund_agent import tui
from refund_agent.naive_refund import _demo_frame, _process_interactive


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

    assert "Welcome back, Nyghtowl" in panel.renderable.plain
    assert "How can I help?" in panel.renderable.plain


def test_reloaded_agent_answers_without_a_new_customer_request(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))

    panel = tui._stage_agent_panel(
        "existing-refund",
        recovered=True,
        refund_status="succeeded",
    )

    assert panel.title == "RELOADED AGENT"
    assert "NO REPEATED QUESTIONS" in panel.renderable.plain
    assert "NO LOOP RESTART" in panel.renderable.plain
    assert "Nyghtowl's existing work" in panel.renderable.plain
    assert "Your refund is complete" in panel.renderable.plain


def test_stage_system_view_makes_the_payoff_glanceable() -> None:
    panel = tui._stage_system_view(
        status="COMPLETED",
        refund={"calls": 2, "status": "succeeded"},
        pending_attempt=None,
        refund_step_completed=True,
    )

    assert "Agent loop completed after recovery" in panel.renderable.plain
    assert "2 CALLS  →  1 REFUND" in panel.renderable.plain
    assert "No duplicate" in panel.renderable.plain


def test_reloaded_agent_does_not_call_a_pending_refund_complete(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))

    panel = tui._stage_agent_panel(
        "existing-refund",
        recovered=True,
        refund_status="pending",
    )

    assert "Stripe accepted the refund" in panel.renderable.plain
    assert "status is still pending" in panel.renderable.plain
    assert "refund is complete" not in panel.renderable.plain


def test_stage_system_view_reports_pending_stripe_status() -> None:
    panel = tui._stage_system_view(
        status="COMPLETED",
        refund={"calls": 1, "status": "pending"},
        pending_attempt=None,
        refund_step_completed=True,
    )

    assert "Refund status: PENDING" in panel.renderable.plain
    assert "Stripe has not confirmed completion" in panel.renderable.plain
    assert "Refund succeeded" not in panel.renderable.plain


def test_stage_system_view_explains_a_denied_live_request() -> None:
    panel = tui._stage_system_view(
        status="COMPLETED",
        refund=None,
        pending_attempt=None,
        refund_step_completed=False,
        denied=True,
    )

    assert "This request is complete" in panel.renderable.plain
    assert "No refund step was started" in panel.renderable.plain
    assert "Refund: none" in panel.renderable.plain


def test_naive_restart_returns_to_a_blank_conversation() -> None:
    frame = _demo_frame(
        {"_restarted": True, "_replacement_worker": True},
        [],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "Welcome back, Nyghtowl" in text
    assert "REPLACEMENT WORKER" in text
    assert "A new session has started" in text
    assert "answers and loop position are gone" in text
    assert "AFTER REPLACEMENT" in text
    assert "WHAT WENT WRONG" not in text
    assert "Ask: What happened to my refund?" in text
    assert "Payment: PAID" in text
    assert "Refund: none" in text
    assert "REPLACEMENT WORKER" in text


def test_naive_worker_gone_is_a_visible_stage_beat() -> None:
    frame = _demo_frame({"_worker_gone": True}, [], stage_mode=True)
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "WORKER GONE" in text
    assert "current conversation and working view disappeared" in text
    assert "live copy of the agent loop is gone" in text
    assert "Payment: PAID" in text
    assert "Refund: none" in text
    assert "Press Enter to start a replacement Worker" in text


def test_naive_agent_loop_reaches_the_refund_before_stripe_is_called() -> None:
    frame = _demo_frame(
        {
            "user_message": "Please refund my plush python",
            "context": {"order": "1234", "amount": 8000, "customer": "42"},
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "_loop_steps": [
                {"kind": "answer", "question_id": "item_opened", "result": "Yes"},
                {"kind": "answer", "question_id": "damage", "result": "Split seam"},
                {"kind": "tool", "label": "Looked up order", "result": "PAID"},
                {"kind": "ready", "result": "issue refund"},
            ],
        },
        [],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "Please refund my plush python" in text
    assert "AGENT LOOP" in text
    assert "✓ Damage: Split seam" in text
    assert "→ Next: issue refund" in text
    assert "WORK NOT SAVED" in text
    assert "answers and next action exist only in this Worker" in text
    assert "Press Enter to replace this Worker" in text
    assert "crash" not in text.lower()


def test_naive_status_check_cannot_recover_working_memory_from_stripe() -> None:
    frame = _demo_frame(
        {
            "user_message": "Did I get my refund?",
            "context": {"order": "1234", "amount": 8000, "customer": "42"},
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "_status_checked": True,
            "_refund_missing": True,
            "_replacement_worker": True,
        },
        [],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "Let me check Stripe" in text
    assert "I lost your return answers" in text
    assert "No refund request reached Stripe" in text
    assert "Please start the return again" in text
    assert "THE CUSTOMER RESTARTS THE LOOP" in text
    assert "Worker held the answers" in text
    assert "DUPLICATE REFUND" not in text
    assert "REPLACEMENT WORKER" in text


def test_naive_status_check_does_not_invent_a_refund() -> None:
    agent: dict = {}
    ledger: list = []
    _process_interactive(agent, ledger, "Please refund my plush python")

    replacement_agent: dict = {"_restarted": True}
    _process_interactive(replacement_agent, ledger, "Did I get my refund?")

    assert ledger == []
    assert replacement_agent["_status_checked"] is True
    assert replacement_agent["_refund_missing"] is True


def test_naive_stage_frame_does_not_stretch_to_terminal_height() -> None:
    frame = _demo_frame(
        {"_restarted": True},
        [],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=80, height=40).print(frame)

    assert len(output.getvalue().splitlines()) <= 24


def test_durable_stage_frame_does_not_stretch_to_terminal_height(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))
    frame = tui._stage_build(
        tui._stage_agent_panel(
            "existing-refund",
            recovered=True,
            refund_status="succeeded",
        ),
        tui._stage_system_view(
            status="COMPLETED",
            refund={"calls": 2, "status": "succeeded"},
            pending_attempt=None,
            refund_step_completed=True,
        ),
    )
    output = io.StringIO()
    Console(file=output, width=80, height=40).print(frame)

    assert len(output.getvalue().splitlines()) <= 20
