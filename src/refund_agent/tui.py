"""A stage viewer: THE AGENT beside THE SYSTEM OF RECORD, updating live.

This is a read-only presentation tool. It never changes Workflow behavior.

THE AGENT panel reflects the Worker's in-process view, which the Worker mirrors
to a file. The panel reads as lost the moment the Worker process is gone, so a
restart blanks it on stage. THE SYSTEM OF RECORD panel is read from Temporal and
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
    state_dir,
    temporal_address,
    temporal_namespace,
    worker_pid_file,
)


def _worker_alive() -> tuple[bool, int | None]:
    # THE AGENT view only exists while its Worker process is alive.
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


def _agent_panel(workflow_id: str) -> Panel:
    alive, _ = _worker_alive()
    body = Text()
    if not alive:
        body.append("LOST\n\n", style="bold red")
        body.append(
            "this panel is the Worker's live view.\n"
            "it dies with the Worker. Temporal keeps the\n"
            "recorded steps and replays them, so the run\n"
            "resumes when a Worker returns",
            style="red",
        )
        return Panel(body, title="THE AGENT (in process)", border_style="red")

    path = state_dir() / f"agent-view-{workflow_id}.json"
    view: dict = {}
    if path.exists():
        try:
            view = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            view = {}
    if not view:
        body.append("empty\n\n", style="dim")
        body.append("new process, nothing retrieved yet", style="dim")
        return Panel(body, title="THE AGENT (in process)", border_style="cyan")

    context = view.get("context") or {}
    observations = view.get("observations") or []
    decision = view.get("decision")

    body.append("CONTEXT\n", style="bold cyan")
    body.append(
        f"  request  {context.get('request_id')}\n"
        f"  order    {context.get('order_id')}\n"
        f"  customer {context.get('customer_id')}\n"
        f"  amount   {context.get('amount_cents')} cents\n\n"
    )
    body.append("STEPS RETRIEVED (this run)\n", style="bold cyan")
    if observations:
        for obs in observations:
            body.append(f"  {obs.get('tool')}\n")
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
    return Panel(body, title="THE AGENT (in process)", border_style="cyan")


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
        return Panel(body, title="THE SYSTEM OF RECORD (durable)", border_style="green")

    status = description.status.name if description.status else "UNKNOWN"
    history = await handle.fetch_history()
    rows, _ = _event_rows(history)
    phase = _phase(rows, status)

    completed = {r.get("name") for r in rows if r.get("event") == "completed"}
    signals = {r.get("name") for r in rows if r.get("event") == "signal"}

    body.append(f"status  {status}\n", style="bold green")
    body.append(f"phase   {phase}\n\n")
    tools = [
        name
        for name in ("lookup_order", "lookup_customer_history", "check_refund_policy")
        if name in completed
    ]
    body.append("steps\n", style="bold green")
    body.append(f"  tools used      {', '.join(tools) if tools else '(none yet)'}\n")
    if "approve" in signals:
        approval = "done"
    elif status == "COMPLETED":
        approval = "not needed (auto)"
    else:
        approval = "pending"
    body.append(f"  human approval  {approval}\n")
    body.append(f"  refund issued   {_mark('issue_refund' in completed)}\n\n")

    body.append("pending activity\n", style="bold green")
    pending = list(description.raw_description.pending_activities)
    if pending:
        for item in pending:
            body.append(f"  {item.activity_type.name} attempt {item.attempt}\n")
    else:
        body.append("  none\n")
    body.append("\n")

    body.append("refund (idempotency-keyed)\n", style="bold green")
    refund = find_refund(workflow_id)
    if refund is None:
        body.append("  none yet\n", style="dim")
    else:
        calls = refund.get("calls", 1)
        body.append(
            f"  refund id  {refund.get('refund_id')}\n"
            f"  status     {refund.get('status')}\n"
            f"  calls      {calls}\n"
            "  unique     1 (no duplicate)\n"
        )
        if calls > 1:
            body.append(
                "  same key reused: Stripe returned the same refund\n",
                style="green",
            )
        else:
            body.append(
                "  one call; a restart replays this step, not repeats it\n",
                style="dim",
            )
    return Panel(
        body,
        title="THE SYSTEM OF RECORD (Temporal + Stripe, durable)",
        border_style="green",
    )


def _header(workflow_id: str) -> Panel:
    text = Text()
    text.append("Demo 2: Durable Refund Agent", style="bold")
    text.append(f"    workflow {workflow_id}\n", style="dim")
    text.append(
        "THE AGENT = the Worker's in-process view, dies with the Worker      "
        "THE SYSTEM OF RECORD = Temporal + Stripe, durable",
        style="dim",
    )
    return Panel(text, border_style="white")


def _build(workflow_id: str, agent: Panel, system: Panel) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_header(workflow_id), size=4, name="head"),
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
