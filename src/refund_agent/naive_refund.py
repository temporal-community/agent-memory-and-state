"""Demo 1: a naive refund agent with no coordinated execution.

The agent rebuilds its context and retrieves the same facts on every run. It
calls the effect owner and then writes a separate completion marker. A restart
(a deploy, eviction, OOM, or crash) between those writes leaves the next run
unable to tell that the refund committed. Even if the later marker is durable,
it is not atomic with the effect, so the next run refunds a second time.

This is the same refund task as Demo 2, deliberately built the naive way so the
restart issues a duplicate refund. Demo 2 is the same agent made durable, where
it does not.

Presenter flow:
  naive-refund reset
  naive-refund refund --order 1234 --exit-after-effect   # refunds, then exits
  naive-refund refund --order 1234                         # restart, refunds AGAIN
  naive-refund ledger                                      # two refunds, one order
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
    # A naive refund: append with a fresh id every time, no idempotency key and
    # no dedup. Running twice therefore commits two refunds.
    ledger = _read_ledger()
    refund_id = f"re_naive_{uuid.uuid4().hex[:12]}"
    ledger["refunds"].append(
        {"refund_id": refund_id, "order_id": order, "amount_cents": amount_cents}
    )
    _ledger_path().write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return refund_id


def _refund_count(order: str) -> int:
    return sum(1 for r in _read_ledger()["refunds"] if r["order_id"] == order)


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
    count = _refund_count(order)
    if count > 1:
        _line(
            "WARNING",
            paint(
                f"order {order} now has {count} refunds in the ledger, a duplicate",
                "danger",
            ),
        )


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
    counts: dict[str, int] = {}
    for refund in refunds:
        counts[refund["order_id"]] = counts.get(refund["order_id"], 0) + 1
    for order, count in counts.items():
        if count > 1:
            _line(
                "WARNING",
                paint(f"order {order}: {count} refunds (duplicate refund)", "danger"),
            )


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
    if agent.get("recorded"):
        agent["note"] = "already refunded (it has that recorded), so it skips"
        return
    refund_id = f"re_naive_{uuid.uuid4().hex[:8]}"
    ledger.append({"refund_id": refund_id, "order": order, "amount": amount})
    agent["recorded"] = True
    agent["note"] = f"issued {refund_id}, recorded 'done' in its own process"


def _demo_frame(agent: dict, ledger: list, *, stage_mode: bool = False):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text

    left = Text()
    if "context" not in agent:
        left.append("How can I help you?\n\n", style="bold cyan")
        if agent.get("_restarted"):
            left.append(
                "REPLACEMENT WORKER\n"
                "A new session has started.\n"
                "The previous conversation is gone.\n"
                "Ask for the refund again.",
                style="yellow",
            )
        else:
            left.append(
                "No conversation yet.\nAsk for a refund to begin.",
                style="dim",
            )
    else:
        context = agent.get("context") or {}
        memory = agent.get("memory") or {}
        amount = (context.get("amount") or 0) / 100
        left.append("YOU\n", style="bold yellow")
        left.append(f"  {agent.get('user_message', 'Please refund order 1234')}\n\n")
        if agent.get("_effect_unrecorded"):
            left.append("AGENT  ", style="bold cyan")
            left.append("Refund issued.\n\n", style="bold")
        left.append("THE AGENT REMEMBERS\n", style="bold blue")
        left.append(
            f"  Customer {context.get('customer')}: "
            f"{memory.get('tenure_days')} days, "
            f"{memory.get('prior_refunds')} prior refund\n"
            f"  Order {context.get('order')}: ${amount:.2f}\n\n"
        )
        left.append("DECISION\n", style="bold cyan")
        left.append("  Approve the refund\n")

    right = Text()
    right.append(f"REFUNDS ISSUED: {len(ledger)}\n\n", style="bold")
    for number, entry in enumerate(ledger, start=1):
        amount = entry["amount"] / 100
        right.append(f"  Refund {number}: order {entry['order']}, ${amount:.2f}\n")
    counts: dict[str, int] = {}
    for entry in ledger:
        counts[entry["order"]] = counts.get(entry["order"], 0) + 1
    duplicate = any(count > 1 for count in counts.values())
    if duplicate:
        right.append("\nDUPLICATE REFUND\n", style="bold red")
        right.append("The same order was refunded twice.\n", style="red")

    header_text = Text()
    header_text.append("Demo 1: The agent starts over\n", style="bold")
    header_text.append(
        "The refund survives when the Worker is replaced. Its progress does not.",
        style="dim",
    )
    header = Panel(header_text, border_style="cyan")
    if duplicate:
        explanation = (
            "The same request produced the same decision twice.\n"
            "Nothing tied both attempts to one refund."
        )
        explanation_title = "WHAT WENT WRONG"
    elif agent.get("_effect_unrecorded") and ledger:
        explanation = "The refund is recorded.\nThe completed customer request is not."
        explanation_title = "WHAT IS MISSING"
    elif agent.get("_restarted") and ledger:
        explanation = (
            "A replacement Worker starts with a blank conversation.\n"
            "It cannot see the previous attempt."
        )
        explanation_title = "AFTER REPLACEMENT"
    else:
        explanation = (
            "What happens if the refund succeeds, then this session disappears?"
        )
        explanation_title = "THE QUESTION"
    why = Panel(
        explanation,
        title=explanation_title,
        border_style="yellow",
    )
    if stage_mode and agent.get("_effect_unrecorded"):
        controls = "Press Enter to replace this Worker"
    elif stage_mode:
        controls = "Type your refund request at the you> prompt"
    else:
        controls = "Type a refund request    restart / deploy / OOM    reset    quit"
    footer = Panel(
        controls,
        border_style="dim",
    )
    layout = Layout()
    layout.split_column(
        Layout(header, name="head", size=4),
        Layout(name="body"),
        Layout(why, name="why", size=4),
        Layout(footer, name="foot", size=3),
    )
    layout["body"].split_row(
        Layout(
            Panel(
                left,
                title="THIS AGENT SESSION",
                border_style="cyan",
            ),
            name="agent",
        ),
        Layout(
            Panel(
                right,
                title="REFUND SYSTEM",
                border_style="green",
            ),
            name="world",
        ),
    )
    return layout


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
    boundary = refund.add_mutually_exclusive_group()
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
