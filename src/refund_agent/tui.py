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

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from temporalio.client import Client
from temporalio.service import RPCError

from refund_agent.cli import _event_rows, _phase
from refund_agent.fake_stripe import find_refund
from refund_agent.settings import (
    agent_view_path,
    temporal_address,
    temporal_namespace,
    worker_pid_file,
)


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


def _stage_agent_panel(workflow_id: str, *, recovered: bool = False) -> Panel:
    """Plain-language Worker view for a general-audience talk."""

    alive, _ = _worker_alive()
    body = Text()
    if not alive:
        body.append("WORKER GONE\n\n", style="bold red")
        body.append(
            "Its current conversation and working view disappeared.",
            style="red",
        )
        return Panel(body, title="THIS WORKER", border_style="red")

    if recovered:
        body.append("NO NEW CUSTOMER REQUEST\n\n", style="bold green")
        body.append(
            "Temporal reconnected this agent to the existing refund.\n\n",
            style="green",
        )
        body.append("AGENT\n", style="bold cyan")
        body.append("  Your refund is complete.", style="bold")
        return Panel(body, title="RELOADED AGENT", border_style="green")

    view = _read_agent_view(workflow_id)
    if not view:
        body.append("How can I help you?\n\n", style="bold cyan")
        body.append("No conversation history.", style="dim")
        return Panel(body, title="THIS WORKER", border_style="cyan")

    context = view.get("context") or {}
    observations = view.get("observations") or []
    decision = view.get("decision") or {}
    amount = int(context.get("amount_cents") or 0) / 100
    order_id = str(context.get("order_id") or "")
    display_order_id = order_id.removeprefix("order-")

    body.append("YOU\n", style="bold yellow")
    body.append(f"  {context.get('reason') or 'Please refund this order'}\n\n")
    body.append("THE AGENT FOUND\n", style="bold blue")
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
    return Panel(body, title="THIS WORKER", border_style="cyan")


def _mark(done: bool) -> str:
    return "done" if done else "pending"


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
) -> Panel:
    """Render the durable side without SDK or systems-design vocabulary."""

    body = Text()
    if status is None:
        body.append("No request yet.\n\n", style="bold green")
        body.append("Waiting for you to ask for a refund.", style="dim")
        return Panel(body, title="WHAT SURVIVES", border_style="green")

    if denied:
        body.append("TEMPORAL\n", style="bold green")
        body.append("  This request is complete.\n")
        body.append("  No refund step was started.\n\n")
        body.append("REFUND SYSTEM\n", style="bold green")
        body.append("  No refund was issued.\n", style="dim")
        return Panel(body, title="WHAT SURVIVES", border_style="green")

    body.append("TEMPORAL\n", style="bold green")
    if refund_step_completed:
        body.append("  Refund step completed after recovery.\n")
    elif refund is not None:
        body.append("  Refund step is still open.\n")
        body.append("  The Worker has not reported back.\n")
    else:
        body.append("  Following the refund request.\n")
    if pending_attempt is not None:
        body.append(f"  Current attempt: {pending_attempt}\n")

    body.append("\nREFUND SYSTEM\n", style="bold green")
    if refund is None:
        body.append("  No refund yet.\n", style="dim")
    else:
        calls = int(refund.get("calls", 1))
        body.append("  Refund succeeded.\n")
        if calls > 1:
            body.append(f"\n  {calls} CALLS  →  1 REFUND\n", style="bold green")
            body.append("  Same operation. No duplicate.\n", style="green")
        else:
            body.append("  1 call  →  1 refund\n")
            if not refund_step_completed:
                body.append(
                    "  It succeeded before the Worker reported back.\n",
                    style="yellow",
                )
    return Panel(body, title="WHAT SURVIVES", border_style="green")


async def _stage_system_panel(client: Client, workflow_id: str) -> Panel:
    """Read authoritative records and render the general-audience view."""

    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except RPCError:
        return _stage_system_view(
            status=None,
            refund=None,
            pending_attempt=None,
            refund_step_completed=False,
        )

    status = description.status.name if description.status else "UNKNOWN"
    history = await handle.fetch_history()
    rows, _ = _event_rows(history)
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


def _stage_build(agent: Panel, system: Panel) -> Layout:
    header = Text()
    header.append("Demo 2: The work keeps its place\n", style="bold")
    header.append(
        "The Worker can disappear. The work and refund records survive.",
        style="dim",
    )
    layout = Layout()
    layout.split_column(
        Layout(Panel(header, border_style="white"), size=4, name="head"),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(agent, name="agent"),
        Layout(system, name="system"),
    )
    return layout


async def watch(workflow_id: str) -> None:
    client = await Client.connect(temporal_address(), namespace=temporal_namespace())
    with Live(screen=True, refresh_per_second=8) as live:
        while True:
            agent = _agent_panel(workflow_id)
            system = await _system_panel(client, workflow_id)
            live.update(_build(workflow_id, agent, system))
            await asyncio.sleep(0.5)
