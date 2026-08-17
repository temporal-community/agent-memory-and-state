"""Stage-oriented commands for starting, approving, restarting, and inspecting."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import uuid
from typing import Any

import stripe
from temporalio.client import Client, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode

from refund_agent.fake_stripe import find_refund
from refund_agent.models import RefundRequest, RefundResult
from refund_agent.settings import (
    load_env_file,
    task_queue,
    temporal_address,
    temporal_namespace,
    validate_stripe_key,
    worker_pid_file,
)
from refund_agent.workflow import RefundWorkflow


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _not_found(error: RPCError) -> bool:
    return error.status == RPCStatusCode.NOT_FOUND


async def _client() -> Client:
    return await Client.connect(
        temporal_address(),
        namespace=temporal_namespace(),
    )


async def _start(args: argparse.Namespace) -> None:
    client = await _client()
    workflow_id = args.workflow_id or f"refund-{uuid.uuid4()}"
    dry_run = args.dry_run
    payment_intent = args.payment_intent
    if args.seed:
        # Seeding a real charge implies a real refund against it, so there is no
        # PaymentIntent id to copy and the payment and refund net to zero.
        dry_run = False
        try:
            intent = _create_test_payment(args.amount_cents)
        except RuntimeError as error:
            print(f"THE SYSTEM | {error}")
            return
        except stripe.StripeError as error:
            print(f"THE SYSTEM | Stripe rejected the request: {error}")
            return
        payment_intent = intent.id
        print(
            f"SETUP | seeded a ${intent.amount / 100:.2f} test charge to refund "
            f"against (PaymentIntent {intent.id})"
        )
        print("SETUP | this charge nets to zero once the refund posts")
    request = RefundRequest(
        request_id=args.request_id or workflow_id,
        order_id=args.order_id,
        customer_id=args.customer_id,
        payment_intent_id=payment_intent,
        amount_cents=args.amount_cents,
        reason=args.reason,
        dry_run=dry_run,
        hold_after_effect=args.hold,
        model_provider=args.model_provider,
    )
    await client.start_workflow(
        RefundWorkflow.run,
        request,
        id=workflow_id,
        task_queue=task_queue(),
    )
    print(f"EXECUTION STATE | started Workflow {workflow_id}")
    print(
        f"CONTEXT | refund {request.request_id}: order {request.order_id}, "
        f"${request.amount_cents / 100:.2f}, customer {request.customer_id}"
    )
    print(f"Approve | refund-demo approve {workflow_id}")
    print(f"Inspect | refund-demo inspect {workflow_id}")


async def _approve(args: argparse.Namespace) -> None:
    client = await _client()
    handle = client.get_workflow_handle_for(RefundWorkflow, args.workflow_id)
    try:
        await handle.signal(RefundWorkflow.approve, args.note)
    except RPCError as error:
        if _not_found(error):
            print(
                f"THE SYSTEM | no Workflow named {args.workflow_id}. Start one "
                f"first: refund-demo start --workflow-id {args.workflow_id}"
            )
            return
        raise
    print(f"EXECUTION STATE | approval Signal recorded for {args.workflow_id}")


async def _release(args: argparse.Namespace) -> None:
    client = await _client()
    handle = client.get_workflow_handle_for(RefundWorkflow, args.workflow_id)
    try:
        await handle.signal(RefundWorkflow.release)
    except RPCError as error:
        if _not_found(error):
            print(f"THE SYSTEM | no Workflow named {args.workflow_id}")
            return
        raise
    print(f"EXECUTION STATE | release Signal recorded for {args.workflow_id}")


async def _stop(args: argparse.Namespace) -> None:
    client = await _client()
    handle = client.get_workflow_handle(args.workflow_id)
    try:
        await handle.terminate(reason=args.reason)
    except RPCError as error:
        if _not_found(error):
            print(f"THE SYSTEM | no running Workflow named {args.workflow_id}")
        else:
            print(f"THE SYSTEM | could not terminate {args.workflow_id}: {error}")
        return
    print(f"EXECUTION STATE | terminated Workflow {args.workflow_id}")
    print("THE SYSTEM | if it seeded a charge, run refund-demo cleanup to reconcile")


async def _result(args: argparse.Namespace) -> None:
    client = await _client()
    handle = client.get_workflow_handle_for(RefundWorkflow, args.workflow_id)
    try:
        result: RefundResult = await handle.result()
    except WorkflowFailureError as error:
        # THE SYSTEM: a terminal failure is still a recorded, knowable state.
        print(f"THE SYSTEM | Workflow did not complete successfully: {error.cause}")
        return
    except RPCError as error:
        if _not_found(error):
            print(f"THE SYSTEM | no Workflow named {args.workflow_id}")
            return
        raise
    print(
        f"THE SYSTEM | result: {result.status}, refund {result.refund_id}, "
        f"{result.mode}, attempt {result.activity_attempt}"
    )


def _event_rows(history: Any) -> tuple[list[dict[str, object]], dict[str, int]]:
    scheduled_names: dict[int, str] = {}
    rows: list[dict[str, object]] = []
    final_attempts: dict[str, int] = {}

    for event in history.events:
        kind = event.WhichOneof("attributes")
        if kind == "activity_task_scheduled_event_attributes":
            attributes = event.activity_task_scheduled_event_attributes
            name = attributes.activity_type.name
            scheduled_names[event.event_id] = name
            rows.append(
                {"event_id": event.event_id, "event": "scheduled", "name": name}
            )
        elif kind == "activity_task_started_event_attributes":
            attributes = event.activity_task_started_event_attributes
            name = scheduled_names.get(attributes.scheduled_event_id, "unknown")
            final_attempts[name] = attributes.attempt
            rows.append(
                {
                    "event_id": event.event_id,
                    "event": "started",
                    "name": name,
                    "attempt": attributes.attempt,
                    "has_prior_failure": attributes.HasField("last_failure"),
                }
            )
        elif kind == "activity_task_completed_event_attributes":
            attributes = event.activity_task_completed_event_attributes
            name = scheduled_names.get(attributes.scheduled_event_id, "unknown")
            rows.append(
                {"event_id": event.event_id, "event": "completed", "name": name}
            )
        elif kind == "workflow_execution_signaled_event_attributes":
            attributes = event.workflow_execution_signaled_event_attributes
            rows.append(
                {
                    "event_id": event.event_id,
                    "event": "signal",
                    "name": attributes.signal_name,
                }
            )
        elif kind == "workflow_execution_completed_event_attributes":
            rows.append({"event_id": event.event_id, "event": "workflow_completed"})
    return rows, final_attempts


def _phase(rows: list[dict[str, object]], status: str) -> str:
    if status == "COMPLETED":
        return "completed"
    scheduled = [row.get("name") for row in rows if row.get("event") == "scheduled"]
    signals = [row.get("name") for row in rows if row.get("event") == "signal"]
    completed = [row.get("name") for row in rows if row.get("event") == "completed"]
    if "issue_refund" in scheduled:
        return "refund effect in flight"
    if "approve" in signals:
        return "approved, issuing refund"
    tools = [
        name
        for name in ("lookup_order", "lookup_customer_history", "check_refund_policy")
        if name in completed
    ]
    if tools:
        return "agent loop, retrieved: " + ", ".join(tools)
    if "agent_step" in scheduled or "agent_step" in completed:
        return "agent loop, reasoning"
    return "starting"


def _print_dry_run_stripe_view(workflow_id: str) -> bool:
    refund = find_refund(workflow_id)
    if refund is None:
        print("THE SYSTEM | dry-run Stripe ledger has no committed refund")
        return False
    print(f"THE SYSTEM | dry-run Stripe ledger\n{_json(refund)}")
    print("THE SYSTEM | unique Stripe refunds for this key: 1")
    return True


def _print_real_stripe_view(workflow_id: str, payment_intent: str | None) -> None:
    secret_key = validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=False)
    if secret_key is None or payment_intent is None:
        print(
            "THE SYSTEM | real Stripe view not queried; provide a test key and "
            "--payment-intent"
        )
        return
    stripe.api_key = secret_key
    stripe.max_network_retries = 0
    try:
        refunds_list = stripe.Refund.list(payment_intent=payment_intent, limit=100).data
    except stripe.StripeError as error:
        print(f"THE SYSTEM | Stripe rejected the request: {error}")
        return
    matches = []
    for refund in refunds_list:
        metadata = refund.metadata or {}
        if metadata.get("temporal_workflow_id") == workflow_id:
            matches.append(
                {
                    "refund_id": refund.id,
                    "status": refund.status,
                    "amount": refund.amount,
                }
            )
    print(f"THE SYSTEM | Stripe test refunds\n{_json(matches)}")
    print(f"THE SYSTEM | unique Stripe refunds for this Workflow: {len(matches)}")


async def _inspect(args: argparse.Namespace) -> None:
    client = await _client()
    handle = client.get_workflow_handle(args.workflow_id)
    try:
        description = await handle.describe()
    except RPCError as error:
        if _not_found(error):
            print(f"THE SYSTEM | no Workflow named {args.workflow_id}")
            return
        raise
    history = await handle.fetch_history()
    rows, final_attempts = _event_rows(history)
    status = description.status.name
    pending = [
        {
            "activity": item.activity_type.name,
            "activity_id": item.activity_id,
            "attempt": item.attempt,
            "state": item.state,
        }
        for item in description.raw_description.pending_activities
    ]

    print(
        "CONTEXT + MEMORY | not available here; that view existed only in the "
        "Worker process"
    )
    print(
        "THE SYSTEM | Temporal\n"
        + _json(
            {
                "workflow_id": args.workflow_id,
                "status": status,
                "phase_from_history": _phase(rows, status),
                "history_events": rows,
                "pending_activities": pending,
                "final_activity_attempts": final_attempts,
            }
        )
    )
    if final_attempts.get("issue_refund", 0) > 1:
        print(
            "THE SYSTEM | Temporal compacted retries; issue_refund completed on "
            f"attempt {final_attempts['issue_refund']}"
        )

    if not _print_dry_run_stripe_view(args.workflow_id):
        _print_real_stripe_view(args.workflow_id, args.payment_intent)


_DEMO_PAYMENT_DESCRIPTION = "plush python (durable refund demo)"
# cleanup also matches charges seeded before the description was renamed, so a
# stale test balance from an earlier rehearsal still reconciles.
_DEMO_PAYMENT_DESCRIPTIONS = (
    _DEMO_PAYMENT_DESCRIPTION,
    "durable refund demo test payment",
)


def _create_test_payment(amount_cents: int, currency: str = "usd") -> Any:
    # Create a succeeded test PaymentIntent so there is something to refund.
    # Raises RuntimeError (missing or invalid key) or stripe.StripeError (API);
    # callers print a clean message.
    stripe.api_key = validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=True)
    stripe.max_network_retries = 0
    return stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=currency,
        payment_method="pm_card_visa",
        payment_method_types=["card"],
        confirm=True,
        description=_DEMO_PAYMENT_DESCRIPTION,
    )


async def _seed_payment(args: argparse.Namespace) -> None:
    try:
        intent = _create_test_payment(args.amount_cents, args.currency)
    except RuntimeError as error:
        print(f"THE SYSTEM | {error}")
        return
    except stripe.StripeError as error:
        print(f"THE SYSTEM | Stripe rejected the request: {error}")
        return
    print(
        f"THE SYSTEM | created test PaymentIntent {intent.id} "
        f"status {intent.status} amount {intent.amount}"
    )
    print(
        "Refund this one: refund-demo start --real "
        f"--payment-intent {intent.id} --amount-cents {args.amount_cents}"
    )
    print("Or seed and refund in one step: refund-demo start --real --seed")


async def _cleanup(args: argparse.Namespace) -> None:
    # Refund any outstanding demo test charges so the Stripe test account resets
    # between rehearsals. Only touches PaymentIntents this demo created.
    try:
        stripe.api_key = validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=True)
    except RuntimeError as error:
        print(f"THE SYSTEM | {error}")
        return
    stripe.max_network_retries = 0
    try:
        intents = stripe.PaymentIntent.list(limit=100).data
    except stripe.StripeError as error:
        print(f"THE SYSTEM | Stripe rejected the request: {error}")
        return
    refunded = 0
    for intent in intents:
        if not intent.status == "succeeded":
            continue
        if (intent.description or "") not in _DEMO_PAYMENT_DESCRIPTIONS:
            continue
        try:
            prior = stripe.Refund.list(payment_intent=intent.id, limit=20).data
            already = sum(
                r.amount for r in prior if r.status in ("succeeded", "pending")
            )
            if already >= intent.amount:
                continue
            refund = stripe.Refund.create(
                payment_intent=intent.id,
                reason="requested_by_customer",
                metadata={"cleanup": "demo"},
            )
        except stripe.StripeError as error:
            print(f"THE SYSTEM | could not refund {intent.id}: {error}")
            continue
        refunded += refund.amount
        print(
            f"THE SYSTEM | refunded {intent.id} to {refund.id} amount {refund.amount}"
        )
    print(f"THE SYSTEM | cleanup done, refunded {refunded} cents of demo charges")


async def _watch(args: argparse.Namespace) -> None:
    # Lazy import so the core CLI never requires the optional rich dependency.
    try:
        from refund_agent import tui
    except ModuleNotFoundError:
        print("The watch view needs rich. Install it with: uv sync --extra tui")
        return
    await tui.watch(args.workflow_id)


async def _stage(args: argparse.Namespace) -> None:
    # Lazy import: the regular CLI still works without the optional Rich extra.
    try:
        from refund_agent.stage import run
    except ModuleNotFoundError:
        print("The stage view needs rich. Install it with: uv sync --extra tui")
        return
    try:
        await run(
            workflow_id=args.workflow_id,
            real=args.real,
            real_model=args.real_model,
            amount_cents=8000,
            model_provider=args.model_provider,
        )
    except RuntimeError as error:
        print(f"STAGE | {error}")


def _kill_worker() -> None:
    path = worker_pid_file()
    if not path.exists():
        raise RuntimeError(f"Worker PID file does not exist at {path}")
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        print("EXECUTION STATE | pid file was not a number (cleared)", flush=True)
        return
    if pid == os.getpid():
        raise RuntimeError("Refusing to kill the current process")
    try:
        # Signal 0 checks liveness without sending a real signal.
        os.kill(pid, 0)
    except ProcessLookupError:
        # A prior SIGKILL bypasses the Worker's own pid-file cleanup, so a stale
        # pid can linger. Clear it instead of killing an unrelated process id.
        path.unlink(missing_ok=True)
        print(
            f"EXECUTION STATE | no live Worker recorded (stale pid {pid} cleared)",
            flush=True,
        )
        return
    except PermissionError:
        print(
            f"EXECUTION STATE | pid {pid} is owned by another user; not killing it",
            flush=True,
        )
        return
    print(f"EXECUTION STATE | sending SIGKILL to Worker PID {pid}", flush=True)
    os.kill(pid, signal.SIGKILL)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refund-demo",
        description="Drive the durable human-in-the-loop refund demo",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start a refund Workflow")
    start.add_argument("--workflow-id")
    start.add_argument("--request-id")
    start.add_argument("--order-id", default="order-1234")
    start.add_argument("--customer-id", default="cus_demo_42")
    start.add_argument("--payment-intent", default="pi_dry_run_demo")
    start.add_argument("--amount-cents", type=int, default=8000)
    start.add_argument(
        "--reason",
        default="The plush python arrived with a split seam",
    )
    mode = start.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", dest="dry_run")
    mode.add_argument("--real", action="store_false", dest="dry_run")
    start.set_defaults(dry_run=True)
    start.add_argument(
        "--seed",
        action="store_true",
        help="seed a Stripe test PaymentIntent and refund it (implies --real)",
    )
    start.add_argument(
        "--hold",
        action="store_true",
        help="after the refund, hold the run open so a restart shows replay "
        "skipping the recorded step (finish with: refund-demo release ID)",
    )
    start.add_argument(
        "--model-provider",
        choices=("anthropic", "openai"),
        help="record which configured live-model provider this Workflow uses",
    )

    approve = commands.add_parser("approve", help="send the approval Signal")
    approve.add_argument("workflow_id")
    approve.add_argument("note", nargs="?", default="")

    release = commands.add_parser(
        "release", help="release a run held open after its refund (start --hold)"
    )
    release.add_argument("workflow_id")

    stop = commands.add_parser("stop", help="terminate a running Workflow")
    stop.add_argument("workflow_id")
    stop.add_argument("--reason", default="stopped from refund-demo")

    result = commands.add_parser("result", help="wait for and print the result")
    result.add_argument("workflow_id")

    inspect = commands.add_parser("inspect", help="print agent and system views")
    inspect.add_argument("workflow_id")
    inspect.add_argument("--payment-intent")

    commands.add_parser("kill-worker", help="hard kill the recorded Worker PID")

    watch = commands.add_parser(
        "watch", help="live view of context and memory beside authoritative state"
    )
    watch.add_argument("workflow_id")

    stage = commands.add_parser(
        "stage",
        help="run both demos in one guided terminal (starts and restarts its Worker)",
    )
    stage.add_argument("--workflow-id")
    stage.add_argument(
        "--real",
        action="store_true",
        help="use a seeded Stripe test payment instead of the offline ledger",
    )
    stage.add_argument(
        "--real-model",
        action="store_true",
        help="use a configured Anthropic or OpenAI model instead of canned policy",
    )
    stage.add_argument(
        "--model-provider",
        choices=("anthropic", "openai"),
        help="live provider; inferred only when exactly one provider key is set",
    )

    seed = commands.add_parser(
        "seed-payment",
        help="create a succeeded Stripe test PaymentIntent to refund against",
    )
    seed.add_argument("--amount-cents", type=int, default=8000)
    seed.add_argument("--currency", default="usd")

    commands.add_parser(
        "cleanup", help="refund leftover demo test charges in Stripe test mode"
    )
    return parser


async def _async_main(args: argparse.Namespace) -> None:
    if args.command == "start":
        await _start(args)
    elif args.command == "approve":
        await _approve(args)
    elif args.command == "release":
        await _release(args)
    elif args.command == "stop":
        await _stop(args)
    elif args.command == "result":
        await _result(args)
    elif args.command == "inspect":
        await _inspect(args)
    elif args.command == "watch":
        await _watch(args)
    elif args.command == "stage":
        await _stage(args)
    elif args.command == "seed-payment":
        await _seed_payment(args)
    elif args.command == "cleanup":
        await _cleanup(args)


def main() -> None:
    load_env_file()
    args = _parser().parse_args()
    if args.command == "kill-worker":
        _kill_worker()
        return
    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        # Ctrl+C is the normal way to leave the live watch view.
        pass


if __name__ == "__main__":
    main()
