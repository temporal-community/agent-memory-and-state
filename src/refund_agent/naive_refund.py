"""Demo 1: an autonomous loop without durable execution state.

The agent asks questions, observes answers, performs lookups, and chooses its
next action. Its Worker then disappears before calling the refund system. Its
process-local working memory disappears too. Stripe correctly retains the paid
charge with no refund, but it does not own the interrupted agent loop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import stripe

from refund_agent.settings import load_env_file, validate_stripe_key

# Color only when writing to a real terminal, so piped output stays clean.
_COLOR = sys.stdout.isatty()
_CODES = {"bold": "1", "dim": "2", "system": "32", "danger": "31"}


def paint(text: str, name: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{_CODES[name]}m{text}\033[0m"


def _line(label: str, text: str) -> None:
    print(f"{label:<15}| {text}", flush=True)


def _loop_event(payload: dict[str, str]) -> None:
    """Emit a machine-readable step while keeping the subprocess real."""

    _line("AGENT STEP", json.dumps(payload, sort_keys=True))


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


def _read_real_stripe_state(
    payment_intent_id: str,
) -> tuple[str, list[dict[str, object]]]:
    """Read effect state from Stripe without creating a refund."""

    stripe.api_key = validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=True)
    stripe.max_network_retries = 0
    intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    refunds = stripe.Refund.list(payment_intent=payment_intent_id, limit=10)
    intent_status = str(intent.status).lower()
    payment_status = "PAID" if intent_status == "succeeded" else intent_status.upper()
    ledger = [
        {
            "refund_id": str(refund.id),
            "order": "1234",
            "amount": int(refund.amount),
            "status": str(refund.status).lower(),
        }
        for refund in refunds.data
    ]
    return payment_status, ledger


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


def _run_interactive_agent_loop() -> None:
    """Choose questions and lookups until the next action is the refund."""

    answers: dict[str, str] = {}
    questions = (
        ("item_opened", "Was the package opened?", "Yes"),
        ("damage", "What was damaged?", "Split seam"),
    )
    for question_id, question, suggested_answer in questions:
        if question_id in answers:
            continue
        _loop_event(
            {
                "kind": "question",
                "question_id": question_id,
                "question": question,
                "suggested_answer": suggested_answer,
            }
        )
        answer = sys.stdin.readline()
        if not answer:
            raise RuntimeError("customer input closed during the agent loop")
        answers[question_id] = answer.strip() or suggested_answer
        _loop_event(
            {
                "kind": "answer",
                "question_id": question_id,
                "question": question,
                "result": answers[question_id],
            }
        )

    _loop_event(
        {
            "kind": "tool",
            "tool": "lookup_order",
            "label": "Found order",
            "result": "plush python",
        }
    )
    _loop_event(
        {
            "kind": "tool",
            "tool": "lookup_customer_history",
            "label": "Checked refund history",
            "result": "clean",
        }
    )
    _loop_event(
        {
            "kind": "ready",
            "label": "Next action",
            "result": "issue refund",
        }
    )


def _replacement_status(args: argparse.Namespace) -> None:
    """Run the replacement agent's effect check in a new process."""

    _state_dir().mkdir(parents=True, exist_ok=True)
    question = sys.stdin.readline()
    if not question:
        raise RuntimeError("customer input closed before the replacement status check")

    try:
        if args.real:
            payment_status, refunds = _read_real_stripe_state(args.payment_intent)
        else:
            payment_status = "PAID"
            refunds = [
                {
                    "refund_id": str(refund["refund_id"]),
                    "order": str(refund["order_id"]),
                    "amount": int(refund["amount_cents"]),
                    "status": "succeeded",
                }
                for refund in _read_ledger().get("refunds", [])
            ]
    except stripe.StripeError as error:
        message = getattr(error, "user_message", None) or str(error)
        _line("AGENT ERROR", json.dumps({"message": message}))
        return

    agent = {
        "context": {
            "order": args.order,
            "amount": args.amount_cents,
            "customer": "Nyghtowl",
        },
        "_status_checked": True,
        "_refund_missing": not refunds,
        "_payment_status": payment_status,
        "_replacement_worker": True,
        "_worker_pid": os.getpid(),
        "note": "replacement process checked Stripe after the customer asked",
        "user_message": question.strip(),
    }
    _line(
        "AGENT RESULT",
        json.dumps({"agent": agent, "refunds": refunds}, sort_keys=True),
    )

    if args.hold_after_status:
        while True:
            time.sleep(60)


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

    if args.interactive_loop:
        _run_interactive_agent_loop()
    else:
        _line(
            "RETURN FORM",
            f"opened={args.opened}; damage={args.damage}; refund_to={args.refund_to}",
        )
    if args.hold_before_effect:
        _line(
            "REQUEST BUFFER",
            "next action held by this Worker; Stripe not called",
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
    agent["_loop_steps"] = [
        {
            "kind": "answer",
            "question_id": "item_opened",
            "result": "Yes",
        },
        {"kind": "answer", "question_id": "damage", "result": "Split seam"},
        {
            "kind": "tool",
            "label": "Looked up order",
            "result": "PAID",
        },
        {
            "kind": "tool",
            "label": "Checked refund history",
            "result": "clean",
        },
        {"kind": "ready", "label": "Next action", "result": "issue refund"},
    ]
    agent["note"] = "agent chose the refund; loop position remains in this process"


def _demo_frame(agent: dict, ledger: list, *, stage_mode: bool = False):
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    from refund_agent.tui import _compact_columns

    refund_status = (
        str(ledger[-1].get("status", "succeeded")).lower() if ledger else None
    )

    left = Text()
    if "context" not in agent:
        if agent.get("_worker_gone"):
            left.append("WORKER GONE\n\n", style="bold red")
            left.append(
                "Its current conversation and working view disappeared.\n\n"
                "Its live copy of the agent loop is gone.",
                style="red",
            )
        else:
            left.append("Welcome back, Nyghtowl\n\n", style="bold cyan")
        if agent.get("_restarted"):
            left.append(
                "REPLACEMENT WORKER\n"
                "A new session has started.\n"
                "The answers and loop position are gone.",
                style="yellow",
            )
        elif not agent.get("_worker_gone"):
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
            left.append("  I lost your return answers.\n", style="yellow")
            left.append("  Please start the return again.\n", style="yellow")
        elif refund_status == "succeeded":
            left.append("ANSWER\n", style="bold green")
            left.append(f"  Yes — your ${amount:.2f} refund succeeded.\n", style="bold")
        else:
            left.append("ANSWER\n", style="bold yellow")
            left.append("  Stripe has a refund record.\n", style="bold")
            left.append(f"  Current status: {refund_status.upper()}.\n", style="yellow")
            left.append("  It is not confirmed complete.\n", style="yellow")
    else:
        from refund_agent.tui import _append_loop_steps

        context = agent.get("context") or {}
        amount = (context.get("amount") or 0) / 100
        left.append("YOU\n", style="bold yellow")
        left.append(f"  {agent.get('user_message', 'Please refund order 1234')}\n\n")
        if agent.get("_loop_steps") or agent.get("_pending_question"):
            _append_loop_steps(
                left,
                agent.get("_loop_steps") or [],
                pending_question=agent.get("_pending_question"),
            )
        else:
            left.append(f"  Order {context.get('order')}: ${amount:.2f}\n")

    right = Text()
    right.append("LAST ORDER\n", style="bold")
    right.append("  Plush python · $80.00\n\n")
    right.append("STRIPE\n", style="bold green")
    right.append(f"  Payment: {agent.get('_payment_status', 'PAID')}\n")
    if not ledger:
        right.append("  Refund: none\n", style="dim")
    else:
        right.append(
            f"  Refund: {refund_status.upper()}\n",
            style="green" if refund_status == "succeeded" else "yellow",
        )
    for number, entry in enumerate(ledger, start=1):
        amount = entry["amount"] / 100
        right.append(f"  Refund {number}: order {entry['order']}, ${amount:.2f}\n")
        status = str(entry.get("status", "succeeded")).lower()
        right.append(f"  Status: {status}\n")

    header_text = Text()
    header_text.append("Demo 1: The agent loop starts over\n", style="bold")
    header_text.append(
        "The agent asks, observes, and looks things up before choosing the refund.",
        style="dim",
    )
    header = Panel(header_text, border_style="cyan")
    if agent.get("_worker_gone"):
        explanation = (
            "The process-local answers and next action disappeared.\n"
            "Stripe still correctly says PAID with no refund."
        )
        explanation_title = "WORKER GONE"
    elif agent.get("_status_checked") and not ledger:
        explanation = (
            "Stripe kept the payment record. The Worker held the answers and\n"
            "the loop position. Both disappeared with it."
        )
        explanation_title = "THE CUSTOMER RESTARTS THE LOOP"
    elif any(step.get("kind") == "ready" for step in agent.get("_loop_steps") or []):
        explanation = (
            "The agent chose its next action: issue the refund.\n"
            "Its answers and next action exist only in this Worker."
        )
        explanation_title = "WORK NOT SAVED"
    elif agent.get("_restarted"):
        explanation = (
            "Stripe correctly says PAID with no refund.\n"
            "The answers and agent loop disappeared with the Worker."
        )
        explanation_title = "AFTER REPLACEMENT"
    else:
        explanation = "What happens when an autonomous loop loses its Worker?"
        explanation_title = "THE QUESTION"
    why = Panel(
        explanation,
        title=explanation_title,
        border_style="yellow",
    )
    if stage_mode and agent.get("_pending_question"):
        controls = "Answer the agent's next question"
    elif stage_mode and any(
        step.get("kind") == "ready" for step in agent.get("_loop_steps") or []
    ):
        controls = "Press Enter to replace this Worker"
    elif stage_mode and agent.get("_status_checked"):
        controls = "Press Enter to compare with durable execution"
    elif stage_mode and agent.get("_worker_gone"):
        controls = "Press Enter to start a replacement Worker"
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
    if agent.get("_worker_gone"):
        agent_panel_title = "THIS WORKER"
        agent_border_style = "red"
    elif agent.get("_replacement_worker") or agent.get("_restarted"):
        agent_panel_title = "REPLACEMENT WORKER"
        agent_border_style = "cyan"
    else:
        agent_panel_title = "THIS AGENT SESSION"
        agent_border_style = "cyan"
    panes = _compact_columns(
        Panel(
            left,
            title=agent_panel_title,
            border_style=agent_border_style,
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
    load_env_file()
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
    refund.add_argument(
        "--interactive-loop",
        action="store_true",
        help="let the agent choose and ask each return question",
    )
    boundary = refund.add_mutually_exclusive_group()
    boundary.add_argument(
        "--hold-before-effect",
        action="store_true",
        help="wait after choosing the refund but before calling the refund system",
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

    replacement = commands.add_parser(
        "replacement-status",
        help="check effect state from a new naive-agent process",
    )
    replacement.add_argument("--order", default="1234")
    replacement.add_argument("--amount-cents", type=int, default=8000)
    replacement.add_argument("--payment-intent", default="pi_dry_run_demo")
    replacement.add_argument("--real", action="store_true")
    replacement.add_argument("--hold-after-status", action="store_true")

    args = parser.parse_args()
    if args.command == "refund":
        _refund(args)
    elif args.command == "ledger":
        _ledger(args)
    elif args.command == "reset":
        _reset(args)
    elif args.command == "replacement-status":
        _replacement_status(args)
    else:
        # No subcommand: launch the interactive two-pane demo.
        _run_interactive()


if __name__ == "__main__":
    main()
