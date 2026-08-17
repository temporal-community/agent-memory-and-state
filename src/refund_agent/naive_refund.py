"""Demo 1: accepted application input without durable execution state.

The Worker accepts a completed return form, then disappears before calling the
refund system. Stripe correctly retains the paid charge and no refund. It cannot
reconstruct form answers it never received. A replacement agent can check
Stripe, but the customer must enter the return details again.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Color only when writing to a real terminal, so piped output stays clean.
_COLOR = sys.stdout.isatty()
_CODES = {"bold": "1", "dim": "2", "system": "32", "danger": "31"}


def paint(text: str, name: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{_CODES[name]}m{text}\033[0m"


def _line(label: str, text: str) -> None:
    print(f"{label:<15}| {text}", flush=True)


def _money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _state_dir() -> Path:
    return Path(os.getenv("DEMO_STATE_DIR", ".demo-state"))


def _ledger_path() -> Path:
    return _state_dir() / "naive-ledger.json"


def _done_path(order: str) -> Path:
    return _state_dir() / f"naive-done-{order}.json"


def _read_ledger() -> dict:
    path = _ledger_path()
    if not path.exists():
        return {"refunds": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _append_refund(order: str, amount_cents: int) -> str:
    # The effect owner accepts a new refund call. The caller checks existing
    # effect state before reaching this function, but that check is still manual
    # reconciliation rather than resumed execution.
    ledger = _read_ledger()
    refund_id = f"re_naive_{uuid.uuid4().hex[:12]}"
    ledger["refunds"].append(
        {"refund_id": refund_id, "order_id": order, "amount_cents": amount_cents}
    )
    _ledger_path().write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return refund_id


def _existing_refund(order: str) -> dict | None:
    return next(
        (refund for refund in _read_ledger()["refunds"] if refund["order_id"] == order),
        None,
    )


def _refund(args: argparse.Namespace) -> None:
    order = args.order
    amount = args.amount_cents
    _state_dir().mkdir(parents=True, exist_ok=True)

    print(paint("=" * 64, "dim"))
    # Domain facts are retrieved into MEMORY on every new run. The source record
    # remains domain state; this is the copy the agent reasons with.
    _line("CONTEXT", f"order {order}, {_money(amount)}, customer cus_demo_42")
    _line("MEMORY COPY", "cus_demo_42: 824 days tenure, 1 prior refund")

    # The completion marker is separate from the effect. It can be durable after
    # it is written and still cannot close the crash gap before that write.
    if _done_path(order).exists():
        _line("PROGRESS RECORD", "completion marker found; already refunded, done")
        return
    _line(
        "PROGRESS RECORD",
        "no marker; cannot infer whether the external effect committed",
    )

    existing = _existing_refund(order)
    if existing is not None:
        _line(
            "EFFECT CHECK",
            f"refund system confirms {existing['refund_id']} already succeeded",
        )
        _line(
            "RECOVERY",
            "result reconstructed because this new process checked",
        )
        return

    _line(
        "RETURN FORM",
        f"opened={args.opened}; damage={args.damage}; refund_to={args.refund_to}",
    )
    if args.hold_before_effect:
        _line(
            "REQUEST BUFFER",
            "accepted by this Worker; not durably saved; Stripe not called",
        )
        sys.stdout.flush()
        while True:
            time.sleep(60)

    _line("MODEL REASONING", "approve (amount within policy, clean history)")
    refund_id = _append_refund(order, amount)
    _line("THE SYSTEM", f"issued refund {refund_id} for order {order}")

    if args.hold_after_effect:
        _line(
            "PROGRESS RECORD",
            "refund succeeded; waiting before recording completion",
        )
        sys.stdout.flush()
        while True:
            time.sleep(60)

    if args.exit_after_effect:
        _line(
            "PROGRESS RECORD",
            paint("process exits before recording completion", "danger"),
        )
        sys.stdout.flush()
        os._exit(1)

    _done_path(order).write_text(
        json.dumps({"order_id": order, "refund_id": refund_id}) + "\n",
        encoding="utf-8",
    )
    _line("PROGRESS RECORD", "recorded completion in a separate write")


def _ledger(args: argparse.Namespace) -> None:
    ledger = _read_ledger()
    refunds = [
        r for r in ledger["refunds"] if not args.order or r["order_id"] == args.order
    ]
    print(paint(f"naive ledger: {len(refunds)} refund(s)", "bold"))
    for refund in refunds:
        detail = (
            f"{refund['refund_id']}  order {refund['order_id']}  "
            f"{_money(refund['amount_cents'])}"
        )
        _line("THE SYSTEM", detail)


def _reset(_args: argparse.Namespace) -> None:
    _ledger_path().unlink(missing_ok=True)
    for path in _state_dir().glob("naive-done-*.json"):
        path.unlink(missing_ok=True)
    print(paint("naive ledger and completion records cleared", "dim"))


def _process_interactive(
    agent: dict, ledger: list, user_message: str = "Please refund order 1234"
) -> None:
    # This interactive fixture keeps progress in process to make the loss
    # visible. The scripted path above demonstrates the broader crash gap between
    # an effect and a separate completion write.
    order, amount, customer = "1234", 8000, "42"
    agent["user_message"] = user_message
    agent["context"] = {"order": order, "amount": amount, "customer": customer}
    agent["memory"] = {"tenure_days": 824, "prior_refunds": 1}
    normalized = user_message.lower()
    if any(word in normalized for word in ("did i", "what happened", "status")):
        agent["_status_checked"] = True
        agent["_refund_missing"] = not any(item["order"] == order for item in ledger)
        agent["note"] = "checked Stripe after a new customer message"
        return
    agent["_form_accepted"] = True
    agent["return_form"] = {
        "item_opened": "Yes",
        "damage": "Split seam",
        "refund_destination": "Original card",
    }
    agent["note"] = "accepted the form in this process; Stripe not called"


def _demo_frame(agent: dict, ledger: list, *, stage_mode: bool = False):
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    from refund_agent.tui import _compact_columns

    left = Text()
    if "context" not in agent:
        left.append("Welcome back, Nyghtowl\n\n", style="bold cyan")
        if agent.get("_restarted"):
            left.append(
                "REPLACEMENT WORKER\n"
                "A new session has started.\n"
                "The submitted return form is gone.",
                style="yellow",
            )
        else:
            left.append("How can I help?", style="dim")
    elif agent.get("_status_checked"):
        context = agent.get("context") or {}
        amount = (context.get("amount") or 0) / 100
        left.append("YOU\n", style="bold yellow")
        left.append(f"  {agent.get('user_message', 'What happened to my refund?')}\n\n")
        left.append("AGENT\n", style="bold cyan")
        left.append("  Let me check Stripe.\n\n")
        if agent.get("_refund_missing", not ledger):
            left.append("ANSWER\n", style="bold yellow")
            left.append("  No refund request reached Stripe.\n", style="bold")
            left.append("  Please enter the return details again.\n", style="yellow")
        else:
            left.append("ANSWER\n", style="bold green")
            left.append(f"  Yes — your ${amount:.2f} refund succeeded.\n", style="bold")
    else:
        context = agent.get("context") or {}
        amount = (context.get("amount") or 0) / 100
        left.append("YOU\n", style="bold yellow")
        left.append(f"  {agent.get('user_message', 'Please refund order 1234')}\n\n")
        form = agent.get("return_form") or {}
        if agent.get("_form_accepted"):
            left.append("RETURN FORM — SUBMITTED\n", style="bold cyan")
            left.append(f"  Opened: {form.get('item_opened', 'Yes')}\n")
            left.append(f"  Damage: {form.get('damage', 'Split seam')}\n")
            left.append(
                f"  Refund to: {form.get('refund_destination', 'Original card')}\n\n"
            )
            left.append("AGENT\n", style="bold cyan")
            left.append("  I have your return details.\n")
            left.append("  Starting the refund...\n", style="yellow")
        else:
            left.append(f"  Order {context.get('order')}: ${amount:.2f}\n")

    right = Text()
    right.append("LAST ORDER\n", style="bold")
    right.append("  Plush python · $80.00\n\n")
    right.append("STRIPE\n", style="bold green")
    right.append("  Payment: PAID\n")
    right.append(
        "  Refund: none\n" if not ledger else "  Refund: SUCCEEDED\n",
        style="dim" if not ledger else "green",
    )
    for number, entry in enumerate(ledger, start=1):
        amount = entry["amount"] / 100
        right.append(f"  Refund {number}: order {entry['order']}, ${amount:.2f}\n")
        right.append("  Status: succeeded\n")

    header_text = Text()
    header_text.append("Demo 1: The agent starts over\n", style="bold")
    header_text.append(
        "The Worker accepts a return form, then disappears before Stripe is called.",
        style="dim",
    )
    header = Panel(header_text, border_style="cyan")
    if agent.get("_status_checked") and not ledger:
        explanation = (
            "Stripe can prove that no refund exists.\n"
            "It cannot recover return details it never received."
        )
        explanation_title = "THE CUSTOMER MUST START OVER"
    elif agent.get("_form_accepted"):
        explanation = (
            "The form exists only in this Worker.\n"
            "Stripe still has a paid order and no refund request."
        )
        explanation_title = "ACCEPTED, BUT NOT SAVED"
    elif agent.get("_restarted"):
        explanation = (
            "Stripe correctly says PAID with no refund.\n"
            "The return form disappeared with the Worker."
        )
        explanation_title = "AFTER REPLACEMENT"
    else:
        explanation = (
            "What happens after the form is submitted but before Stripe is called?"
        )
        explanation_title = "THE QUESTION"
    why = Panel(
        explanation,
        title=explanation_title,
        border_style="yellow",
    )
    if stage_mode and agent.get("_form_accepted"):
        controls = "Press Enter to replace this Worker"
    elif stage_mode and agent.get("_status_checked"):
        controls = "Press Enter to compare with durable execution"
    elif stage_mode and agent.get("_restarted"):
        controls = "Ask: What happened to my refund?"
    elif stage_mode:
        controls = "Type your refund request at the you> prompt"
    else:
        controls = "Type a refund request    restart / deploy / OOM    reset    quit"
    footer = Panel(
        controls,
        border_style="dim",
    )
    panes = _compact_columns(
        Panel(
            left,
            title="THIS AGENT SESSION",
            border_style="cyan",
        ),
        Panel(
            right,
            title="ORDER + STRIPE",
            border_style="green",
        ),
    )
    return Group(header, panes, why, footer)


def _run_interactive() -> None:
    try:
        from rich.console import Console
    except ModuleNotFoundError:
        print("The interactive view needs rich. Install it with: uv sync --extra tui")
        return
    console = Console()
    agent: dict = {}
    ledger: list = []
    while True:
        console.clear()
        console.print(_demo_frame(agent, ledger))
        try:
            command = input("you>  ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if command in ("quit", "q", "exit"):
            break
        if command in (
            "agent restart",
            "agent deploy",
            "agent oom",
            "restart",
            "deploy",
            "oom",
            "crash",
        ):
            # The agent process goes away: a restart, a deploy, an eviction, an
            # OOM kill. Its in-memory state is gone, including whether it already
            # refunded. A crash is just the blunt version.
            agent.clear()
            agent["_restarted"] = True
        elif command == "reset":
            agent.clear()
            ledger.clear()
        elif command in ("", "go") or "refund" in command:
            _process_interactive(agent, ledger, command or "Please refund order 1234")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="naive-refund",
        description="A refund agent with no durable execution (Demo 1)",
    )
    commands = parser.add_subparsers(dest="command")

    refund = commands.add_parser("refund", help="process one refund")
    refund.add_argument("--order", default="1234")
    refund.add_argument("--amount-cents", type=int, default=8000)
    refund.add_argument("--opened", default="Yes")
    refund.add_argument("--damage", default="Split seam")
    refund.add_argument("--refund-to", default="Original card")
    boundary = refund.add_mutually_exclusive_group()
    boundary.add_argument(
        "--hold-before-effect",
        action="store_true",
        help="wait after accepting the form but before calling the refund system",
    )
    boundary.add_argument(
        "--exit-after-effect",
        action="store_true",
        help="exit right after refunding, before recording completion",
    )
    boundary.add_argument(
        "--hold-after-effect",
        action="store_true",
        help="wait after refunding so the process can be replaced at the boundary",
    )

    ledger = commands.add_parser("ledger", help="show the naive ledger")
    ledger.add_argument("--order")

    commands.add_parser("reset", help="clear the ledger and completion records")

    args = parser.parse_args()
    if args.command == "refund":
        _refund(args)
    elif args.command == "ledger":
        _ledger(args)
    elif args.command == "reset":
        _reset(args)
    else:
        # No subcommand: launch the interactive two-pane demo.
        _run_interactive()


if __name__ == "__main__":
    main()
