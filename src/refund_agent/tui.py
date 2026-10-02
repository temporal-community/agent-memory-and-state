"""A stage viewer: decision inputs beside authoritative state, updating live.

This is a read-only presentation tool. It never changes Workflow behavior.

The left panel reflects the Worker's in-process view, which the Worker mirrors
to a file. The panel reads as lost the moment the Worker process is gone, so a
restart blanks it on stage. The state panel is read from Temporal and
the refund ledger, which survive a restart. That contrast is the point.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from temporalio.client import Client
from temporalio.converter import DataConverter
from temporalio.service import RPCError

from refund_agent.cli import _event_rows, _phase
from refund_agent.fake_stripe import find_refund
from refund_agent.settings import (
    agent_view_path,
    temporal_address,
    temporal_identity,
    temporal_namespace,
    worker_pid_file,
)

# Bounds the Worker-gone history read so a stuck call cannot hang a stage cue.
_HISTORY_READ_TIMEOUT_SECONDS = 3

_LOOKUP_LABELS = {
    "lookup_order": "Order",
    "lookup_customer_history": "Refund history",
    "check_refund_policy": "Refund policy",
}


@dataclass(frozen=True)
class DemoSetup:
    """What this stage run really uses, so every frame can say so on screen."""

    real_stripe: bool = False
    model_provider: str | None = None

    @property
    def effect_heading(self) -> str:
        # Never label the offline ledger as plain "Stripe".
        if self.real_stripe:
            return "STRIPE (test mode)"
        return "OFFLINE LEDGER (Stripe stand-in)"

    @property
    def _effect_note(self) -> str:
        return "Stripe test mode" if self.real_stripe else "offline ledger (no Stripe)"

    @property
    def naive_line(self) -> str:
        return f"Scripted steps · {self._effect_note}"

    @property
    def durable_line(self) -> str:
        if self.model_provider:
            policy = f"Live model ({self.model_provider})"
        else:
            policy = "Fixed policy (no LLM)"
        return f"{policy} · sample lookups · {self._effect_note}"


OFFLINE_SETUP = DemoSetup()


def _demo_header(title: str, subtitle: str, setup_line: str) -> Text:
    """Title, one-line subtitle, and the dim disclosure of what is scripted."""

    header = Text()
    header.append(f"{title}\n", style="bold")
    header.append(f"{subtitle}\n", style="dim")
    header.append(setup_line, style="dim italic")
    return header


def _worker_alive() -> tuple[bool, int | None]:
    # The decision view only exists while its Worker process is alive.
    path = worker_pid_file()
    if not path.exists():
        return False, None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False, None
    try:
        os.kill(pid, 0)  # signal 0 checks liveness without sending a signal
    except ProcessLookupError:
        return False, pid
    except PermissionError:
        return True, pid
    return True, pid


def _read_agent_view(workflow_id: str) -> dict:
    path = agent_view_path(workflow_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _agent_panel(workflow_id: str) -> Panel:
    alive, _ = _worker_alive()
    body = Text()
    if not alive:
        body.append("LOST\n\n", style="bold red")
        body.append(
            "context and retrieved memory were this\n"
            "Worker's live view. They can be rebuilt.\n\n"
            "Temporal still owns execution progress;\n"
            "the effect owner still owns the refund outcome.",
            style="red",
        )
        return Panel(
            body,
            title="CONTEXT + MEMORY (Worker process)",
            border_style="red",
        )

    view = _read_agent_view(workflow_id)
    if not view:
        body.append("How can I help you?\n\n", style="bold cyan")
        body.append(
            "waiting for a refund request\nno context assembled; no memory retrieved",
            style="dim",
        )
        return Panel(
            body,
            title="CONTEXT + MEMORY (Worker process)",
            border_style="cyan",
        )

    context = view.get("context") or {}
    observations = view.get("observations") or []
    decision = view.get("decision")

    body.append("CONTEXT (model input now)\n", style="bold yellow")
    body.append(
        f"  request  {context.get('request_id')}\n"
        f"  order    {context.get('order_id')}\n"
        f"  customer {context.get('customer_id')}\n"
        f"  amount   {context.get('amount_cents')} cents\n\n"
    )
    body.append("MEMORY (retrieved copies for the decision)\n", style="bold blue")
    if observations:
        for obs in observations:
            body.append(f"  {obs.get('tool')}\n")
        body.append("  source records remain domain state\n", style="dim")
    else:
        body.append("  nothing retrieved yet\n", style="dim")
    body.append("\n")
    body.append("DECISION\n", style="bold cyan")
    if decision:
        body.append(
            f"  {decision.get('recommendation')} (source {decision.get('source')})\n"
        )
    else:
        body.append("  not decided yet\n", style="dim")
    return Panel(
        body,
        title="CONTEXT + MEMORY (Worker process)",
        border_style="cyan",
    )


def _stage_agent_panel(
    workflow_id: str,
    *,
    recovered: bool = False,
    refund_status: str | None = None,
    loop_steps: list[dict[str, str]] | None = None,
    pending_question: dict[str, str] | None = None,
    stopped_before_refund: bool = False,
) -> Panel:
    """Plain-language Worker view for a general-audience talk."""

    alive, _ = _worker_alive()
    body = Text()
    if not alive:
        body.append("WORKER GONE\n\n", style="bold red")
        body.append("Its in-memory loop is gone.\n\n", style="red")
        if stopped_before_refund:
            # The presenter's cue says "submit", so the screen says who stopped
            # it. Only the main path stops the Worker before Stripe is called.
            body.append(
                "The demo stops the Worker here,\n"
                "before the refund reaches Stripe.\n\n",
                style="dim",
            )
        # The arrow sends the eye to the right pane, where the proof is.
        body.append("Temporal still has the saved loop. →", style="red")
        return Panel(body, title="TEMPORAL WORKER", border_style="red")

    if recovered:
        body.append("NO REPEATED QUESTIONS\nNO LOOP RESTART\n\n", style="bold green")
        body.append("Same loop, rebuilt from Temporal.\n\n", style="green")
        body.append("AGENT\n", style="bold cyan")
        normalized_status = (refund_status or "unknown").lower()
        if normalized_status == "succeeded":
            body.append("  Your refund is complete.", style="bold")
            border_style = "green"
        elif normalized_status == "pending":
            body.append("  Stripe accepted the refund.\n", style="bold yellow")
            body.append("  Its status is still pending.", style="yellow")
            border_style = "yellow"
        else:
            body.append(
                "  I cannot confirm that the refund completed.\n",
                style="bold red",
            )
            body.append(f"  Stripe status: {normalized_status.upper()}.", style="red")
            border_style = "red"
        return Panel(body, title="NEW TEMPORAL WORKER", border_style=border_style)

    if loop_steps or pending_question:
        _append_loop_steps(body, loop_steps or [], pending_question=pending_question)
        return Panel(body, title="TEMPORAL WORKER", border_style="cyan")

    view = _read_agent_view(workflow_id)
    if not view:
        body.append("Welcome back, Nyghtowl\n\n", style="bold cyan")
        body.append("How can I help?", style="dim")
        return Panel(body, title="TEMPORAL WORKER", border_style="cyan")

    context = view.get("context") or {}
    observations = view.get("observations") or []
    decision = view.get("decision") or {}
    amount = int(context.get("amount_cents") or 0) / 100
    order_id = str(context.get("order_id") or "")
    display_order_id = order_id.removeprefix("order-")

    body.append("YOU\n", style="bold yellow")
    body.append(f"  {context.get('reason') or 'Please refund this order'}\n\n")
    body.append("THE AGENT LOOKED UP\n", style="bold blue")
    friendly_tools = {
        "lookup_order": "Order details",
        "lookup_customer_history": "Customer history",
        "check_refund_policy": "Refund policy",
    }
    if observations:
        for observation in observations:
            tool = str(observation.get("tool"))
            body.append(f"  {friendly_tools.get(tool, 'Requested information')}\n")
    else:
        body.append("  Nothing yet\n", style="dim")
    body.append(f"  Order {display_order_id}: ${amount:.2f}\n\n")

    recommendations = {
        "approve": "Approve the refund",
        "escalate": "Ask a person to approve",
        "deny": "Do not issue the refund",
    }
    recommendation = str(decision.get("recommendation") or "")
    body.append("DECISION\n", style="bold cyan")
    body.append(f"  {recommendations.get(recommendation, 'Still deciding')}\n")
    if recommendation == "deny" and decision.get("rationale"):
        rationale = " ".join(str(decision["rationale"]).split())
        if len(rationale) > 180:
            rationale = rationale[:177].rstrip() + "..."
        body.append("\nWHY\n", style="bold yellow")
        body.append(f"  {rationale}\n", style="yellow")
    return Panel(body, title="TEMPORAL WORKER", border_style="cyan")


def _mark(done: bool) -> str:
    return "done" if done else "pending"


def _append_loop_steps(
    body: Text,
    steps: list[dict[str, str]],
    *,
    pending_question: dict[str, str] | None = None,
) -> None:
    """Render the same compact observe-reason-act loop in both demos."""

    body.append("AGENT LOOP\n", style="bold cyan")
    for step in steps:
        kind = step.get("kind")
        if kind == "answer":
            label = {
                "item_opened": "Package opened",
                "damage": "Damage",
            }.get(step.get("question_id"), "Answer")
            body.append(f"  ✓ {label}: {step.get('result')}\n", style="green")
        elif kind == "tool":
            # A lookup is what the agent looks up: the intro frame's MEMORY.
            body.append(f"  ✓ {step.get('label')}: {step.get('result')}", style="green")
            body.append(" (memory)\n", style="dim")
        elif kind == "ready":
            body.append(f"  → Next: {step.get('result')}\n", style="bold yellow")
    if pending_question:
        body.append(
            f"  → Ask: {pending_question.get('question')}\n",
            style="bold yellow",
        )


async def _system_panel(client: Client, workflow_id: str) -> Panel:
    handle = client.get_workflow_handle(workflow_id)
    body = Text()
    try:
        description = await handle.describe()
    except RPCError:
        body.append("waiting for workflow\n\n", style="dim")
        body.append(f"no execution named {workflow_id} yet", style="dim")
        return Panel(body, title="STATE (durable owners)", border_style="green")

    status = description.status.name if description.status else "UNKNOWN"
    history = await handle.fetch_history()
    rows, _ = _event_rows(history)
    phase = _phase(rows, status)

    completed = {r.get("name") for r in rows if r.get("event") == "completed"}
    scheduled = {r.get("name") for r in rows if r.get("event") == "scheduled"}
    signals = {r.get("name") for r in rows if r.get("event") == "signal"}

    body.append("EXECUTION STATE — owner: Temporal\n", style="bold green")
    body.append(f"  status  {status}\n")
    body.append(f"  phase   {phase}\n\n")
    tools = [
        name
        for name in ("lookup_order", "lookup_customer_history", "check_refund_policy")
        if name in completed
    ]
    body.append("  recorded progress\n", style="bold green")
    body.append(f"  agent tools     {len(tools)} recorded\n")
    if "approve" in signals:
        approval = "done"
    elif "issue_refund" in scheduled or status == "COMPLETED":
        approval = "not needed (auto)"
    else:
        approval = "pending"
    body.append(f"  human approval  {approval}\n")
    body.append(f"  refund issued   {_mark('issue_refund' in completed)}\n\n")

    body.append("  pending activity\n", style="bold green")
    pending = list(description.raw_description.pending_activities)
    if pending:
        for item in pending:
            body.append(f"  {item.activity_type.name} attempt {item.attempt}\n")
    else:
        body.append("  none\n")
    body.append("\n")

    refund = find_refund(workflow_id)
    original_refund_id = str(refund.get("refund_id")) if refund else ""
    effect_owner = (
        "demo ledger" if original_refund_id.startswith("re_dry_") else "Stripe"
    )
    body.append(f"EFFECT STATE — owner: {effect_owner}\n", style="bold green")
    if refund is None:
        body.append("  none yet\n", style="dim")
    else:
        calls = refund.get("calls", 1)
        refund_id = original_refund_id
        if len(refund_id) > 20:
            refund_id = "..." + refund_id[-16:]
        body.append(
            f"  refund id  {refund_id}\n"
            f"  status     {refund.get('status')}\n"
            f"  calls {calls}  |  unique refunds 1\n"
        )
        if calls > 1:
            body.append(
                "  same key reused; same refund returned\n",
                style="green",
            )
        elif "issue_refund" in completed:
            body.append("  completion recorded; replay skips it\n", style="dim")
        else:
            body.append(
                "  effect accepted; completion unrecorded\n",
                style="dim",
            )
    return Panel(
        body,
        title="STATE (durable systems of record)",
        border_style="green",
    )


def _stage_system_view(
    *,
    status: str | None,
    refund: dict | None,
    pending_attempt: int | None,
    refund_step_completed: bool,
    denied: bool = False,
    loop_steps: list[dict[str, str]] | None = None,
    loop_source: str | None = None,
    setup: DemoSetup = OFFLINE_SETUP,
) -> Panel:
    """Render the durable side without SDK or systems-design vocabulary.

    `loop_source` labels where the loop counts came from: "history" means they
    were read from Temporal for this frame, and "cached" means that read failed
    and the counts are the earlier reading taken while the Worker was running.
    `None` is the frame before the kill, while the demo holds the loop before
    Stripe.
    """

    body = Text()
    effect_heading = setup.effect_heading
    if status is None:
        body.append("TEMPORAL\n", style="bold green")
        body.append("  No refund request yet.\n\n", style="dim")
        body.append(f"{effect_heading}\n", style="bold green")
        body.append("  Payment: PAID\n")
        body.append("  Refund: none\n", style="dim")
        return Panel(body, title="WHAT SURVIVES", border_style="green")

    if denied:
        body.append("TEMPORAL\n", style="bold green")
        body.append("  This request is complete.\n")
        body.append("  No refund step was started.\n\n")
        body.append(f"{effect_heading}\n", style="bold green")
        body.append("  Payment: PAID\n")
        body.append("  Refund: none\n", style="dim")
        return Panel(body, title="WHAT SURVIVES", border_style="green")

    body.append("TEMPORAL\n", style="bold green")
    refund_status = (
        str(refund.get("status") or "unknown").lower() if refund is not None else None
    )
    if refund_step_completed and refund_status == "succeeded":
        body.append("  Finished by the new Worker.\n")
    elif refund_step_completed:
        body.append("  Stripe's reply recorded by the new Worker.\n")
    elif refund is not None:
        body.append("  Refund step is still open.\n")
        body.append("  The Worker has not reported back.\n")
    else:
        answers = sum(1 for step in loop_steps or [] if step.get("kind") == "answer")
        lookups = sum(1 for step in loop_steps or [] if step.get("kind") == "tool")
        # One label per list. "Read from Temporal just now" is honest only
        # because the Worker-gone frame reads Event History, not a cached Query.
        if loop_source == "history":
            body.append("  Read from Temporal just now:\n", style="green")
        elif loop_source == "cached":
            body.append("  Could not re-read Temporal.\n", style="yellow")
            body.append("  Showing the earlier reading:\n", style="yellow")
        else:
            body.append("  Saved so far:\n")
        body.append(f"  Customer answers: {answers}\n")
        body.append(f"  Completed lookups: {lookups}\n")
        ready = next(
            (step for step in loop_steps or [] if step.get("kind") == "ready"),
            None,
        )
        if ready:
            body.append(f"  Next action: {ready.get('result')}\n", style="bold green")
            if loop_source is None:
                # The demo-only release Signal wait (RefundWorkflow.run).
                body.append("  (demo pauses here, before Stripe)\n", style="dim")
    if pending_attempt is not None:
        body.append(f"  Current attempt: {pending_attempt}\n")

    body.append(f"\n{effect_heading}\n", style="bold green")
    body.append("  Payment: PAID\n")
    if refund is None:
        body.append("  Refund: none\n", style="dim")
    elif refund_status == "succeeded":
        calls = int(refund.get("calls", 1))
        body.append("  Refund: SUCCEEDED\n")
        # Show call counts only when a retry made more than one call.
        if calls > 1:
            body.append(f"\n  {calls} CALLS  →  1 REFUND\n", style="bold green")
            body.append("  Same operation. No duplicate.\n", style="green")
        elif not refund_step_completed:
            body.append(
                "  It succeeded before the Worker reported back.\n",
                style="yellow",
            )
    else:
        body.append(f"  Refund: {refund_status.upper()}\n", style="yellow")
        body.append("  Stripe has not confirmed it yet.\n", style="yellow")
    return Panel(body, title="WHAT SURVIVES", border_style="green")


async def _loop_steps_from_history(
    history, converter: DataConverter
) -> list[dict[str, str]]:
    """Rebuild the stage loop summary from Temporal's recorded events.

    The Temporal service serves this history with no Worker running. Customer
    answers are Signals, lookups are completed Activities, and the next action
    follows from the agent's recorded decision, as in RefundWorkflow.run.
    """

    activity_names: dict[int, str] = {}
    answered: set[str] = set()
    steps: list[dict[str, str]] = []
    recommendation: str | None = None
    approved = refund_completed = False
    for event in history.events:
        kind = event.WhichOneof("attributes")
        if kind == "workflow_execution_signaled_event_attributes":
            attributes = event.workflow_execution_signaled_event_attributes
            if attributes.signal_name == "approve":
                approved = True
            elif attributes.signal_name == "customer_answer":
                question_id, answer = await converter.decode(attributes.input.payloads)
                if question_id not in answered:
                    answered.add(question_id)
                    steps.append(
                        {
                            "kind": "answer",
                            "question_id": str(question_id),
                            "result": str(answer),
                        }
                    )
        elif kind == "activity_task_scheduled_event_attributes":
            attributes = event.activity_task_scheduled_event_attributes
            activity_names[event.event_id] = attributes.activity_type.name
        elif kind == "activity_task_completed_event_attributes":
            attributes = event.activity_task_completed_event_attributes
            name = activity_names.get(attributes.scheduled_event_id, "")
            if name in _LOOKUP_LABELS:
                steps.append(
                    {
                        "kind": "tool",
                        "tool": name,
                        "label": _LOOKUP_LABELS[name],
                        "result": "done",
                    }
                )
            elif name == "agent_decide_next_step":
                [step] = await converter.decode(attributes.result.payloads)
                if step.get("action") == "decide":
                    recommendation = str(step.get("recommendation") or "escalate")
            elif name == "issue_refund":
                refund_completed = True
    # Mirror RefundWorkflow.run: deny ends the run, approve goes straight to the
    # refund, and anything else is an escalation that waits for the approve Signal.
    if (
        recommendation not in (None, "deny")
        and not refund_completed
        and (recommendation == "approve" or approved)
    ):
        steps.append(
            {"kind": "ready", "label": "Next action", "result": "issue refund"}
        )
    return steps


async def _stage_system_panel(
    client: Client,
    workflow_id: str,
    *,
    loop_steps: list[dict[str, str]] | None = None,
    loop_from_history: bool = False,
    setup: DemoSetup = OFFLINE_SETUP,
) -> Panel:
    """Read authoritative records and render the general-audience view.

    With `loop_from_history`, the loop counts come from Temporal's history for
    this frame instead of `loop_steps`, which were cached by an earlier Query.
    A Query needs a running Worker; reading history does not.
    """

    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except RPCError:
        return _stage_system_view(
            status=None,
            refund=None,
            pending_attempt=None,
            refund_step_completed=False,
            setup=setup,
        )

    status = description.status.name if description.status else "UNKNOWN"
    loop_source = None
    if loop_from_history:
        try:
            history = await asyncio.wait_for(
                handle.fetch_history(), timeout=_HISTORY_READ_TIMEOUT_SECONDS
            )
            loop_steps = await _loop_steps_from_history(history, client.data_converter)
            loop_source = "history"
        except Exception:
            # Keep the frame up, but label the counts as the earlier reading.
            history = None
            loop_source = "cached"
    else:
        history = await handle.fetch_history()
    rows, _ = _event_rows(history) if history is not None else ([], {})
    refund_step_completed = any(
        row.get("event") == "completed" and row.get("name") == "issue_refund"
        for row in rows
    )
    pending = list(description.raw_description.pending_activities)
    pending_attempt = int(pending[0].attempt) if pending else None
    return _stage_system_view(
        status=status,
        refund=find_refund(workflow_id),
        pending_attempt=pending_attempt,
        refund_step_completed=refund_step_completed,
        loop_steps=loop_steps,
        loop_source=loop_source,
        setup=setup,
    )


def _header(workflow_id: str) -> Panel:
    text = Text()
    text.append("Demo 2: Durable Refund Agent", style="bold")
    text.append(f"    workflow {workflow_id}\n", style="dim")
    text.append(
        "CONTEXT + MEMORY help decide.  STATE records what must not be guessed.\n"
        "Crash question: did the refund commit, and where should execution resume?",
        style="dim",
    )
    return Panel(text, border_style="white")


def _build(workflow_id: str, agent: Panel, system: Panel) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_header(workflow_id), size=5, name="head"),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(agent, name="agent"),
        Layout(system, name="system"),
    )
    return layout


def _compact_columns(left: Panel, right: Panel) -> Table:
    """Keep two stage panes aligned without stretching them to screen height."""

    def heading_style(panel: Panel) -> Style:
        border_style = panel.border_style
        color = (
            Style.parse(border_style) if isinstance(border_style, str) else border_style
        )
        return Style.combine([color or Style(), Style(bold=True)])

    columns = Table(
        box=box.ROUNDED,
        border_style="dim",
        expand=True,
        padding=(0, 1),
    )
    columns.add_column(
        Text(str(left.title), justify="center"),
        ratio=1,
        header_style=heading_style(left),
    )
    columns.add_column(
        Text(str(right.title), justify="center"),
        ratio=1,
        header_style=heading_style(right),
    )
    columns.add_row(left.renderable, right.renderable)
    return columns


def _stage_build(
    agent: Panel, system: Panel, *, setup: DemoSetup = OFFLINE_SETUP
) -> Group:
    header = _demo_header(
        "Demo 2: With Temporal, the agent keeps its place",
        "Temporal keeps each answer, lookup and next step outside the Worker.",
        setup.durable_line,
    )
    return Group(
        Panel(header, border_style="white"),
        _compact_columns(agent, system),
    )


async def watch(workflow_id: str) -> None:
    client = await Client.connect(
        temporal_address(),
        namespace=temporal_namespace(),
        identity=temporal_identity(),
    )
    with Live(screen=True, refresh_per_second=8) as live:
        while True:
            agent = _agent_panel(workflow_id)
            system = await _system_panel(client, workflow_id)
            live.update(_build(workflow_id, agent, system))
            await asyncio.sleep(0.5)
