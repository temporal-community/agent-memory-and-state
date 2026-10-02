import asyncio
import io
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("rich")

from rich.console import Console
from temporalio.api.common.v1 import ActivityType, Payloads
from temporalio.api.history.v1 import (
    ActivityTaskCompletedEventAttributes,
    ActivityTaskScheduledEventAttributes,
    History,
    HistoryEvent,
    WorkflowExecutionSignaledEventAttributes,
)
from temporalio.converter import DataConverter

from refund_agent import tui
from refund_agent.models import AgentStep
from refund_agent.naive_refund import _demo_frame, _process_interactive

_CACHED_STEPS = [
    {"kind": "answer", "question_id": "item_opened", "result": "Yes"},
    {"kind": "answer", "question_id": "damage", "result": "Split seam"},
    {"kind": "tool", "label": "Order", "result": "python plushy"},
    {"kind": "tool", "label": "Refund history", "result": "clean"},
    {"kind": "ready", "label": "Next action", "result": "issue refund"},
]


def _payloads(*values) -> Payloads:
    converter = DataConverter.default.payload_converter
    return Payloads(payloads=converter.to_payloads(list(values)))


def _recorded_loop(
    *,
    refund_completed: bool = False,
    recommendation: str | None = "approve",
    approved: bool = False,
) -> History:
    """The canned durable loop as Temporal records it, up to the refund."""

    events: list[HistoryEvent] = []

    def activity(name: str, result) -> None:
        scheduled_id = len(events) + 1
        events.append(
            HistoryEvent(
                event_id=scheduled_id,
                activity_task_scheduled_event_attributes=(
                    ActivityTaskScheduledEventAttributes(
                        activity_type=ActivityType(name=name)
                    )
                ),
            )
        )
        events.append(
            HistoryEvent(
                event_id=scheduled_id + 1,
                activity_task_completed_event_attributes=(
                    ActivityTaskCompletedEventAttributes(
                        scheduled_event_id=scheduled_id,
                        result=_payloads(result),
                    )
                ),
            )
        )

    def answer(question_id: str, value: str) -> None:
        events.append(
            HistoryEvent(
                event_id=len(events) + 1,
                workflow_execution_signaled_event_attributes=(
                    WorkflowExecutionSignaledEventAttributes(
                        signal_name="customer_answer",
                        input=_payloads(question_id, value),
                    )
                ),
            )
        )

    def agent_turn(**step) -> None:
        activity("agent_decide_next_step", AgentStep(**step))

    agent_turn(action="ask_customer", question_id="item_opened")
    answer("item_opened", "Yes")
    agent_turn(action="ask_customer", question_id="damage")
    answer("damage", "Split seam")
    agent_turn(action="use_tool", tool="lookup_order")
    activity("lookup_order", {"item": "python plushy"})
    agent_turn(action="use_tool", tool="lookup_customer_history")
    activity("lookup_customer_history", {"prior_refunds": []})
    agent_turn(action="decide", recommendation=recommendation)
    if approved:
        events.append(
            HistoryEvent(
                event_id=len(events) + 1,
                workflow_execution_signaled_event_attributes=(
                    WorkflowExecutionSignaledEventAttributes(
                        signal_name="approve", input=_payloads("approved")
                    )
                ),
            )
        )
    if refund_completed:
        activity("issue_refund", {"status": "succeeded"})
    return History(events=events)


def _fake_client(fetch_history) -> SimpleNamespace:
    description = SimpleNamespace(
        status=SimpleNamespace(name="RUNNING"),
        raw_description=SimpleNamespace(pending_activities=[]),
    )

    async def describe():
        return description

    handle = SimpleNamespace(describe=describe, fetch_history=fetch_history)
    return SimpleNamespace(
        get_workflow_handle=lambda _workflow_id: handle,
        data_converter=DataConverter.default,
    )


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

    assert panel.title == "NEW TEMPORAL WORKER"
    assert "NO REPEATED QUESTIONS" in panel.renderable.plain
    assert "NO LOOP RESTART" in panel.renderable.plain
    assert "Same loop, rebuilt from Temporal." in panel.renderable.plain
    assert "reconnected" not in panel.renderable.plain
    assert "Your refund is complete" in panel.renderable.plain


def test_stage_system_view_makes_the_payoff_glanceable() -> None:
    panel = tui._stage_system_view(
        status="COMPLETED",
        refund={"calls": 2, "status": "succeeded"},
        pending_attempt=None,
        refund_step_completed=True,
    )

    assert "Finished by the new Worker." in panel.renderable.plain
    assert "recovery" not in panel.renderable.plain
    assert "2 CALLS  →  1 REFUND" in panel.renderable.plain
    assert "No duplicate" in panel.renderable.plain


def test_saved_loop_is_rebuilt_from_temporal_history() -> None:
    steps = asyncio.run(
        tui._loop_steps_from_history(_recorded_loop(), DataConverter.default)
    )

    assert [step["kind"] for step in steps] == [
        "answer",
        "answer",
        "tool",
        "tool",
        "ready",
    ]
    assert [step["result"] for step in steps[:2]] == ["Yes", "Split seam"]
    assert steps[-1]["result"] == "issue refund"


def test_history_has_no_next_action_once_the_refund_step_completed() -> None:
    steps = asyncio.run(
        tui._loop_steps_from_history(
            _recorded_loop(refund_completed=True), DataConverter.default
        )
    )

    assert "ready" not in [step["kind"] for step in steps]


@pytest.mark.parametrize(
    ("recommendation", "approved", "ready"),
    [
        ("escalate", False, False),
        ("escalate", True, True),
        # RefundWorkflow.run escalates anything that is not approve or deny.
        ("review", True, True),
        (None, True, True),
        ("deny", True, False),
    ],
)
def test_history_next_action_mirrors_the_workflow_decision(
    recommendation, approved, ready
) -> None:
    steps = asyncio.run(
        tui._loop_steps_from_history(
            _recorded_loop(recommendation=recommendation, approved=approved),
            DataConverter.default,
        )
    )

    assert ("ready" in [step["kind"] for step in steps]) is ready


def test_worker_gone_panel_reads_the_loop_from_history_not_the_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))

    async def fetch_history():
        return _recorded_loop()

    panel = asyncio.run(
        tui._stage_system_panel(
            _fake_client(fetch_history),
            "worker-gone",
            loop_steps=[],
            loop_from_history=True,
        )
    )
    text = panel.renderable.plain

    assert "Read from Temporal just now:" in text
    # One label per list: the history label replaces the pre-kill one.
    assert "Saved so far:" not in text
    assert "Agent loop saved." not in text
    assert "Customer answers: 2" in text
    assert "Completed lookups: 2" in text
    assert "Next action: issue refund" in text
    assert "(demo pauses here, before Stripe)" not in text
    assert "earlier reading" not in text


def test_worker_gone_panel_labels_the_cached_fallback_when_history_hangs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_HISTORY_READ_TIMEOUT_SECONDS", 0.05)

    async def fetch_history():
        await asyncio.sleep(10)

    started = time.monotonic()
    panel = asyncio.run(
        tui._stage_system_panel(
            _fake_client(fetch_history),
            "worker-gone",
            loop_steps=_CACHED_STEPS,
            loop_from_history=True,
        )
    )
    text = panel.renderable.plain

    assert time.monotonic() - started < 2
    assert "Could not re-read Temporal." in text
    assert "Showing the earlier reading:" in text
    assert "just now" not in text
    assert "Saved so far:" not in text
    assert "Customer answers: 2" in text


def test_worker_gone_frame_with_history_label_fits_the_stage_width(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (False, 456))
    labels = {
        "history": "Read from Temporal just now:",
        "cached": "Showing the earlier reading:",
    }
    for source, label in labels.items():
        frame = tui._stage_build(
            tui._stage_agent_panel("worker-gone"),
            tui._stage_system_view(
                status="RUNNING",
                refund=None,
                pending_attempt=None,
                refund_step_completed=False,
                loop_steps=_CACHED_STEPS,
                loop_source=source,
            ),
        )
        output = io.StringIO()
        Console(file=output, width=80, height=40).print(frame)
        lines = output.getvalue().splitlines()

        assert "WORKER GONE" in output.getvalue()
        assert "Its in-memory loop is gone." in output.getvalue()
        assert "Temporal still has the saved loop. →" in output.getvalue()
        assert label in output.getvalue()
        assert "Next action: issue refund" in output.getvalue()
        assert len(lines) <= 21
        assert all(len(line) <= 80 for line in lines)


@pytest.mark.parametrize(
    ("loop_source", "pauses"),
    [(None, True), ("history", False), ("cached", False)],
)
def test_demo_pause_is_labeled_only_on_the_pre_kill_frame(loop_source, pauses) -> None:
    panel = tui._stage_system_view(
        status="RUNNING",
        refund=None,
        pending_attempt=None,
        refund_step_completed=False,
        loop_steps=_CACHED_STEPS,
        loop_source=loop_source,
    )
    text = panel.renderable.plain

    assert ("(demo pauses here, before Stripe)" in text) is pauses
    assert ("Saved so far:" in text) is (loop_source is None)


def test_saved_frame_labels_the_pause_and_fits_the_stage_width(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))
    frame = tui._stage_build(
        tui._stage_agent_panel("saved", loop_steps=_CACHED_STEPS),
        tui._stage_system_view(
            status="RUNNING",
            refund=None,
            pending_attempt=None,
            refund_step_completed=False,
            loop_steps=_CACHED_STEPS,
        ),
    )
    output = io.StringIO()
    Console(file=output, width=80, height=40).print(frame)
    text = output.getvalue()
    lines = text.splitlines()

    assert "TEMPORAL WORKER" in text
    assert "✓ Package opened: Yes" in text
    assert "Saved so far:" in text
    assert "(demo pauses here, before Stripe)" in text
    assert len(lines) <= 20
    assert all(len(line) <= 80 for line in lines)


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

    assert "Refund: PENDING" in panel.renderable.plain
    assert "Stripe has not confirmed it yet." in panel.renderable.plain
    assert "SUCCEEDED" not in panel.renderable.plain


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
    assert "NEW AGENT PROCESS" in text
    assert "No answers. No next step." in text
    assert "FRESH START" in text
    assert "It can still read Stripe." in text
    assert "It cannot see the old answers." in text
    assert "WHAT WENT WRONG" not in text
    # The cue moved to the stage's input prompt.
    assert "What happened to my refund?" not in text
    assert "Payment: PAID" in text
    assert "Refund: none" in text


def test_naive_worker_gone_is_a_visible_stage_beat() -> None:
    frame = _demo_frame({"_worker_gone": True}, [], stage_mode=True)
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "PROCESS GONE" in text
    assert "WORKER GONE" not in text
    assert "It held the answers and next step." in text
    assert "They are gone with it." in text
    assert "WHAT'S LEFT" in text
    assert "Only Stripe's record: PAID, no refund." in text
    assert "That is correct. Stripe was never called." in text
    assert "Payment: PAID" in text
    assert "Refund: none" in text
    assert "Press Enter" not in text


def test_naive_agent_loop_reaches_the_refund_before_stripe_is_called() -> None:
    frame = _demo_frame(
        {
            "user_message": "Please refund my python plushy",
            "context": {"order": "1234", "amount": 8000, "customer": "42"},
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "_loop_steps": [
                {"kind": "answer", "question_id": "item_opened", "result": "Yes"},
                {"kind": "answer", "question_id": "damage", "result": "Split seam"},
                {"kind": "tool", "label": "Order", "result": "python plushy"},
                {"kind": "ready", "result": "issue refund"},
            ],
        },
        [],
        stage_mode=True,
    )
    output = io.StringIO()
    Console(file=output, width=128).print(frame)
    text = output.getvalue()

    assert "Please refund my python plushy" in text
    assert "AGENT LOOP" in text
    assert "✓ Damage: Split seam" in text
    assert "✓ Order: python plushy (memory)" in text
    assert "→ Next: issue refund" in text
    assert "WORK NOT SAVED" in text
    assert "Next step: submit the refund." in text
    assert "The answers and next step exist only inside this process." in text
    assert "Press Enter" not in text
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
    assert "THE CUSTOMER STARTS OVER" in text
    assert "Stripe's record is right: paid, no refund." in text
    assert "But Stripe never had the answers or the next step." in text
    # The reply belongs to the one AGENT speaker; no second heading.
    assert "ANSWER" not in text
    assert "DUPLICATE REFUND" not in text
    assert "NEW AGENT PROCESS" in text


def test_naive_status_check_does_not_invent_a_refund() -> None:
    agent: dict = {}
    ledger: list = []
    _process_interactive(agent, ledger, "Please refund my python plushy")

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


@pytest.mark.parametrize("width", [80, 100, 128])
def test_recovered_frame_keeps_the_rebuilt_line_whole_at_stage_width(
    tmp_path, monkeypatch, width
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
            refund={"calls": 1, "status": "succeeded"},
            pending_attempt=None,
            refund_step_completed=True,
        ),
    )
    output = io.StringIO()
    Console(file=output, width=width, height=40).print(frame)
    text = output.getvalue()

    # 100 columns is the recording width; 80 is the smallest stage terminal.
    assert "Same loop, rebuilt from Temporal." in text
    assert "NEW TEMPORAL WORKER" in text
    assert "Refund: SUCCEEDED" in text
    # Call counts appear only when a retry made more than one call.
    assert "1 call" not in text
    assert "It succeeded before the Worker reported back." not in text
    assert all(len(line) <= width for line in text.splitlines())


_NAIVE_STAGE_AGENTS = {
    "start": {},
    "question": {
        "context": {"order": "1234", "amount": 8000, "customer": "Nyghtowl"},
        "user_message": "Please refund order 1234.",
        "_loop_steps": _CACHED_STEPS[:1],
        "_pending_question": {"question": "What was damaged?"},
    },
    "ready": {
        "context": {"order": "1234", "amount": 8000, "customer": "Nyghtowl"},
        "user_message": "Please refund order 1234.",
        "_loop_steps": _CACHED_STEPS,
    },
    "gone": {"_worker_gone": True},
    "new process": {"_restarted": True, "_replacement_worker": True},
    "starts over": {
        "context": {"order": "1234", "amount": 8000, "customer": "Nyghtowl"},
        "user_message": "What happened to my refund?",
        "_status_checked": True,
        "_refund_missing": True,
        "_replacement_worker": True,
    },
}


@pytest.mark.parametrize("name", list(_NAIVE_STAGE_AGENTS))
def test_naive_stage_frames_never_call_the_agent_process_a_worker(name) -> None:
    frame = _demo_frame(_NAIVE_STAGE_AGENTS[name], [], stage_mode=True)
    output = io.StringIO()
    Console(file=output, width=80, height=40).print(frame)
    text = output.getvalue()
    lines = text.splitlines()

    assert "worker" not in text.lower()
    assert "WHAT SURVIVES" in text
    assert "ORDER + STRIPE" not in text
    assert len(lines) <= 24
    assert all(len(line) <= 80 for line in lines)


def test_naive_stage_frame_has_no_footer_cue() -> None:
    staged = _demo_frame({}, [], stage_mode=True)
    standalone = _demo_frame({}, [])

    # Header, panes, and explanation. The stage's input prompt is the only cue.
    assert len(staged.renderables) == 3
    assert len(standalone.renderables) == 4
    assert "restart / deploy / OOM" in str(standalone.renderables[-1].renderable)


@pytest.mark.parametrize(
    ("setup", "naive_line", "durable_line", "heading"),
    [
        (
            tui.DemoSetup(),
            "Scripted steps · offline ledger (no Stripe)",
            "Fixed policy (no LLM) · sample lookups · offline ledger (no Stripe)",
            "OFFLINE LEDGER (Stripe stand-in)",
        ),
        (
            tui.DemoSetup(real_stripe=True),
            "Scripted steps · Stripe test mode",
            "Fixed policy (no LLM) · sample lookups · Stripe test mode",
            "STRIPE (test mode)",
        ),
        (
            tui.DemoSetup(real_stripe=True, model_provider="anthropic"),
            "Live model (anthropic) · sample lookups · Stripe test mode",
            "Live model (anthropic) · sample lookups · Stripe test mode",
            "STRIPE (test mode)",
        ),
        (
            tui.DemoSetup(model_provider="openai"),
            "Live model (openai) · sample lookups · offline ledger (no Stripe)",
            "Live model (openai) · sample lookups · offline ledger (no Stripe)",
            "OFFLINE LEDGER (Stripe stand-in)",
        ),
    ],
)
def test_stage_headers_disclose_what_is_scripted(
    tmp_path, monkeypatch, setup, naive_line, durable_line, heading
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tui, "_worker_alive", lambda: (True, 456))
    naive = io.StringIO()
    Console(file=naive, width=80, height=40).print(
        _demo_frame({}, [], stage_mode=True, setup=setup)
    )
    durable = io.StringIO()
    Console(file=durable, width=80, height=40).print(
        tui._stage_build(
            tui._stage_agent_panel("setup"),
            tui._stage_system_view(
                status=None,
                refund=None,
                pending_attempt=None,
                refund_step_completed=False,
                setup=setup,
            ),
            setup=setup,
        )
    )

    assert "Demo 1: Without Temporal, the agent loses its place" in naive.getvalue()
    assert naive_line in naive.getvalue()
    assert heading in naive.getvalue()
    assert "Demo 2: With Temporal, the agent keeps its place" in durable.getvalue()
    assert durable_line in durable.getvalue()
    assert heading in durable.getvalue()
    # The offline ledger is never labeled as plain Stripe.
    if not setup.real_stripe:
        assert "STRIPE" not in naive.getvalue() + durable.getvalue()
    for output in (naive, durable):
        assert all(len(line) <= 80 for line in output.getvalue().splitlines())
