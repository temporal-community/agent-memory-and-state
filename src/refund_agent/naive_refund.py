"""Demo 1: a naive refund agent with no durable execution.

Everything lives in the process: context, memory, and the process-local state
(what it has already done). Knowledge is recomputable, so a restart gets context
and memory back for free. Process-local state is not, so a restart (a deploy,
eviction, OOM, or crash) between issuing the refund and recording that it
finished makes the next run refund a second time.

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
    # CONTEXT and MEMORY are recomputable: a restart re-derives them for free.
    _line("CONTEXT", f"order {order}, {_money(amount)}, customer cus_demo_42")
    _line("MEMORY", "cus_demo_42: 824 days tenure, 1 prior refund")

    # PROCESS-LOCAL STATE: the naive agent's only record of what it already did is a
    # local completion marker. A restart before that marker is written erases it.
    if _done_path(order).exists():
        _line("PROCESS-LOCAL STATE", "completion record found; already refunded, done")
        return
    _line(
        "PROCESS-LOCAL STATE",
        "no completion record; no durable proof this order was refunded",
    )

    _line("MODEL REASONING", "approve (amount within policy, clean history)")
    refund_id = _append_refund(order, amount)
    _line("THE SYSTEM", f"issued refund {refund_id} for order {order}")

    if args.exit_after_effect:
        _line(
            "PROCESS-LOCAL STATE",
            paint("process exits before recording completion", "danger"),
        )
        sys.stdout.flush()
        os._exit(1)

    _done_path(order).write_text(
        json.dumps({"order_id": order, "refund_id": refund_id}) + "\n",
        encoding="utf-8",
    )
    _line("PROCESS-LOCAL STATE", "recorded completion")
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


def _process_interactive(agent: dict, ledger: list) -> None:
    # Context and memory are recomputed every run (recomputable): the request and
    # the customer lookup can always be re-fetched. Process-local state (whether
    # this order was already refunded) lives only in this dict, so a restart that
    # clears it makes the agent refund again.
    order, amount, customer = "1234", 8000, "42"
    agent["context"] = {"order": order, "amount": amount, "customer": customer}
    agent["memory"] = {"tenure_days": 824, "prior_refunds": 0}
    if agent.get("recorded"):
        agent["note"] = "already refunded (it has that recorded), so it skips"
        return
    refund_id = f"re_naive_{uuid.uuid4().hex[:8]}"
    ledger.append({"refund_id": refund_id, "order": order, "amount": amount})
    agent["recorded"] = True
    agent["note"] = f"issued {refund_id}, recorded 'done' in its own process"


def _demo_frame(agent: dict, ledger: list):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text

    left = Text()
    if "context" not in agent:
        if agent.get("_restarted"):
            left.append("LOST\n\n", style="bold red")
            left.append(
                "the agent restarted (deploy, eviction, OOM);\n"
                "its in-memory state is gone, including\n"
                "whether it already refunded",
                style="red",
            )
        else:
            left.append("idle\n\n", style="dim")
            left.append(
                "no request yet; type a refund request (or Enter)",
                style="dim",
            )
    else:
        context = agent.get("context") or {}
        memory = agent.get("memory") or {}
        amount = (context.get("amount") or 0) / 100
        left.append("CONTEXT\n", style="bold yellow")
        left.append(
            f"  Customer {context.get('customer')} requested a refund\n"
            f"  for order {context.get('order')}, ${amount:.2f}\n\n"
        )
        left.append("MEMORY\n", style="bold blue")
        left.append(
            f"  looked up customer {context.get('customer')} in the DB:\n"
            f"  {memory.get('tenure_days')} days, "
            f"{memory.get('prior_refunds')} prior refunds\n\n"
        )
        left.append("PROCESS-LOCAL STATE\n", style="bold green")
        if agent.get("recorded"):
            left.append(f"  {agent.get('note')}\n")
        else:
            left.append("  nothing recorded yet\n", style="dim")

    right = Text()
    right.append(f"{len(ledger)} refund(s) committed\n\n", style="bold")
    for entry in ledger:
        amount = entry["amount"] / 100
        right.append(f"  {entry['refund_id']}  order {entry['order']}  ${amount:.2f}\n")
    counts: dict[str, int] = {}
    for entry in ledger:
        counts[entry["order"]] = counts.get(entry["order"], 0) + 1
    if any(count > 1 for count in counts.values()):
        right.append("\nDUPLICATE REFUND\n", style="bold red")

    restarted = "_restarted" in agent and "context" not in agent
    header = Panel(
        "Demo 1: a refund agent with no durable execution", border_style="cyan"
    )
    footer = Panel(
        "Enter or a refund request = process    "
        "agent restart / deploy / OOM    reset    quit",
        border_style="dim",
    )
    layout = Layout()
    layout.split_column(
        Layout(header, name="head", size=3),
        Layout(name="body"),
        Layout(footer, name="foot", size=3),
    )
    layout["body"].split_row(
        Layout(
            Panel(
                left,
                title="THE AGENT (in process)",
                border_style="red" if restarted else "cyan",
            ),
            name="agent",
        ),
        Layout(
            Panel(right, title="THE RECORD (durable ledger)", border_style="green"),
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
            _process_interactive(agent, ledger)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="naive-refund",
        description="A refund agent with no durable execution (Demo 1)",
    )
    commands = parser.add_subparsers(dest="command")

    refund = commands.add_parser("refund", help="process one refund")
    refund.add_argument("--order", default="1234")
    refund.add_argument("--amount-cents", type=int, default=8000)
    refund.add_argument(
        "--exit-after-effect",
        action="store_true",
        help="exit right after refunding, before recording completion",
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
