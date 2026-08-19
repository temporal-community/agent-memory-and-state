"""A guided, single-terminal version of the complete meetup demo.

The stage runner owns the disposable processes it needs. It uses a private task
queue and state directory, so it can stop and replace its Worker without
touching another Worker the presenter may already have running.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import IO

import stripe
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from temporalio.client import Client, WorkflowHandle

from refund_agent.fake_stripe import find_refund
from refund_agent.models import RefundRequest
from refund_agent.settings import (
    agent_view_path,
    state_dir,
    temporal_address,
    temporal_namespace,
    validate_stripe_key,
    worker_pid_file,
)
from refund_agent.workflow import RefundWorkflow

_SERVER_START_TIMEOUT_SECONDS = 20
_WORKER_START_TIMEOUT_SECONDS = 15
_DEMO_TIMEOUT_SECONDS = 90
_DEFAULT_REFUND_REQUEST = "Please refund order 1234."
_SIMULATED_RETRY_WINDOW_SECONDS = 30
_SIMULATED_RETRY_DETECTION_SECONDS = 4


def _roles() -> Panel:
    body = Text()
    body.append("CONTEXT  ", style="bold yellow")
    body.append("what the agent can see right now\n")
    body.append("MEMORY   ", style="bold blue")
    body.append("what the agent remembers or looks up\n")
    body.append("STATE    ", style="bold green")
    body.append("the records used to act and recover safely")
    return Panel(
        body,
        title="Three things that help an agent act",
        border_style="white",
    )


def _intro() -> Group:
    thesis = Text()
    thesis.append(
        "An agent can know exactly what to do and still lose the work a "
        "customer submitted.\n\n"
    )
    thesis.append(
        "We will interrupt the same observe–reason–act loop before Stripe "
        "receives the refund request, then add a durable owner for its progress."
    )
    return Group(
        Panel(thesis, title="Agent memory and state", border_style="cyan"),
        _roles(),
    )


def _closing(refund_status: str = "succeeded") -> Group:
    result = Text()
    result.append(
        "Naive: Stripe had no refund, and the agent loop started over.\n",
        style="bold red",
    )
    if refund_status.lower() == "succeeded":
        result.append(
            "Durable: the reloaded agent resumed at its next action.",
            style="bold green",
        )
    else:
        result.append(
            "Durable: the reloaded agent resumed the same request.\n",
            style="bold yellow",
        )
        result.append(
            f"Stripe status: {refund_status.upper()} — not reported as complete.",
            style="yellow",
        )
    return Group(
        Panel(result, title="The difference", border_style="green"),
        Panel(
            "Stripe knows what reached Stripe. Temporal remembered that the "
            "refund step was in progress.",
            border_style="white",
        ),
    )


def _tail(path: Path, line_count: int = 12) -> str:
    if not path.exists():
        return "(no log output)"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-line_count:])


def _stop_process(process: subprocess.Popen[str] | None, *, hard: bool = False) -> None:
    if process is None or process.poll() is not None:
        return
    if hard:
        process.kill()
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class _Services:
    def __init__(
        self,
        *,
        base_state: Path,
        stage_state: Path,
        task_queue: str,
        effect_restart_window_seconds: float = 0,
    ) -> None:
        self.base_state = base_state
        self.stage_state = stage_state
        self.task_queue = task_queue
        self.effect_restart_window_seconds = effect_restart_window_seconds
        self.server: subprocess.Popen[str] | None = None
        self.worker: subprocess.Popen[str] | None = None
        self.server_log_path = stage_state / "temporal.log"
        self.worker_log_path = stage_state / "worker.log"
        self._server_log: IO[str] | None = None
        self._worker_log: IO[str] | None = None

    async def connect_or_start_server(self) -> Client:
        try:
            return await asyncio.wait_for(self._connect(), timeout=2)
        except Exception as first_error:
            # Do not silently replace an explicitly configured remote service
            # with localhost. That would make the demo appear to use the wrong
            # system of record.
            address = temporal_address()
            host = address.rsplit(":", 1)[0]
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError(
                    f"could not connect to configured Temporal service {address}"
                ) from first_error

        executable = shutil.which("temporal")
        if executable is None:
            raise RuntimeError(
                "Temporal is not reachable and the `temporal` CLI is not on PATH"
            )
        self.base_state.mkdir(parents=True, exist_ok=True)
        self._server_log = self.server_log_path.open("a", encoding="utf-8")
        self.server = subprocess.Popen(
            [
                executable,
                "server",
                "start-dev",
                "--db-filename",
                str(self.base_state / "temporal.db"),
            ],
            stdout=self._server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + _SERVER_START_TIMEOUT_SECONDS
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise RuntimeError(
                    "Temporal dev server exited while starting:\n"
                    + _tail(self.server_log_path)
                )
            try:
                return await asyncio.wait_for(self._connect(), timeout=1)
            except Exception as error:
                last_error = error
                await asyncio.sleep(0.25)
        raise RuntimeError("Temporal dev server did not become ready") from last_error

    async def _connect(self) -> Client:
        return await Client.connect(
            temporal_address(),
            namespace=temporal_namespace(),
        )

    async def start_worker(self) -> None:
        if self.worker is not None and self.worker.poll() is None:
            return
        if self._worker_log is None:
            self._worker_log = self.worker_log_path.open("a", encoding="utf-8")
        environment = os.environ.copy()
        environment["DEMO_STATE_DIR"] = str(self.stage_state)
        environment["TEMPORAL_TASK_QUEUE"] = self.task_queue
        environment["EFFECT_RESTART_WINDOW_SECONDS"] = str(
            self.effect_restart_window_seconds
        )
        self.worker = subprocess.Popen(
            [sys.executable, "-m", "refund_agent.worker"],
            env=environment,
            stdout=self._worker_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + _WORKER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self.worker.poll() is not None:
                raise RuntimeError(
                    "Worker exited while starting:\n" + _tail(self.worker_log_path)
                )
            path = worker_pid_file()
            if path.exists():
                try:
                    if int(path.read_text(encoding="utf-8").strip()) == self.worker.pid:
                        await asyncio.sleep(0.5)
                        return
                except ValueError:
                    pass
            await asyncio.sleep(0.1)
        raise RuntimeError("Worker did not become ready")

    def kill_worker(self) -> None:
        _stop_process(self.worker, hard=True)

    def close(self) -> None:
        _stop_process(self.worker)
        _stop_process(self.server)
        pid_path = self.stage_state / "worker.pid"
        if self.worker is not None and pid_path.exists():
            try:
                recorded_pid = int(pid_path.read_text(encoding="utf-8").strip())
            except ValueError:
                recorded_pid = None
            if recorded_pid == self.worker.pid:
                pid_path.unlink()
        if self._worker_log is not None:
            self._worker_log.close()
        if self._server_log is not None:
            self._server_log.close()


async def _wait_for_first_effect(
    handle: WorkflowHandle,
    workflow_id: str,
    *,
    timeout: float,
    on_update: Callable[[], Awaitable[None]] | None = None,
) -> str:
    deadline = time.monotonic() + timeout
    approval_sent = False
    while time.monotonic() < deadline:
        refund_exists = find_refund(workflow_id) is not None
        denied = False
        path = agent_view_path(workflow_id)
        if path.exists():
            try:
                view = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                view = {}
            recommendation = (view.get("decision") or {}).get("recommendation")
            if recommendation == "escalate" and not approval_sent:
                await handle.signal(
                    RefundWorkflow.approve,
                    "approved by the guided stage runner",
                )
                approval_sent = True
            elif recommendation == "deny":
                denied = True
        if on_update is not None:
            await on_update()
        if refund_exists:
            return "effect"
        if denied:
            return "denied"
        await asyncio.sleep(0.2)
    raise RuntimeError("timed out waiting for the first refund call")


def _live_model_provider(explicit: str | None) -> str:
    configured = explicit or os.getenv("AGENT_MODEL_PROVIDER")
    if configured:
        provider = configured.strip().lower()
        if provider not in {"anthropic", "openai"}:
            raise RuntimeError("model provider must be 'anthropic' or 'openai'")
    else:
        available = [
            provider
            for provider, key in (
                ("anthropic", os.getenv("ANTHROPIC_API_KEY")),
                ("openai", os.getenv("OPENAI_API_KEY")),
            )
            if key
        ]
        if len(available) > 1:
            raise RuntimeError(
                "both live-model keys are configured; choose --model-provider"
            )
        if not available:
            raise RuntimeError(
                "--real-model requires ANTHROPIC_API_KEY or OPENAI_API_KEY"
            )
        provider = available[0]

    required = {
        "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        "openai": ("OPENAI_API_KEY", "OPENAI_MODEL"),
    }[provider]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"{provider} live model requires {', '.join(missing)}")
    return provider


def _naive_ledger(stage_state: Path) -> list[dict[str, object]]:
    path = stage_state / "naive-ledger.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "refund_id": item["refund_id"],
            "order": item["order_id"],
            "amount": item["amount_cents"],
        }
        for item in raw.get("refunds", [])
    ]


def _start_naive_at_boundary(
    stage_state: Path,
    *,
    amount_cents: int,
) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["DEMO_STATE_DIR"] = str(stage_state)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "refund_agent.naive_refund",
            "refund",
            "--order",
            "1234",
            "--amount-cents",
            str(amount_cents),
            "--interactive-loop",
            "--hold-before-effect",
        ],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _start_naive_replacement(
    stage_state: Path,
    *,
    amount_cents: int,
    payment_intent: str,
    real: bool,
) -> subprocess.Popen[str]:
    """Start a fresh naive-agent process for the post-loss status question."""

    environment = os.environ.copy()
    environment["DEMO_STATE_DIR"] = str(stage_state)
    command = [
        sys.executable,
        "-m",
        "refund_agent.naive_refund",
        "replacement-status",
        "--order",
        "1234",
        "--amount-cents",
        str(amount_cents),
        "--payment-intent",
        payment_intent,
        "--hold-after-status",
    ]
    if real:
        command.append("--real")
    return subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_naive_worker(process: subprocess.Popen[str] | None) -> None:
    _stop_process(process, hard=True)
    if process is not None and process.stdin is not None:
        process.stdin.close()
    if process is not None and process.stdout is not None:
        process.stdout.close()


async def _read_naive_loop_event(
    process: subprocess.Popen[str], *, timeout: float = 10
) -> dict[str, str]:
    if process.stdout is None:
        raise RuntimeError("naive Worker output is unavailable")

    async def read_event() -> dict[str, str]:
        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                raise RuntimeError("naive Worker exited during the agent loop")
            label, separator, payload = line.partition("|")
            if separator and label.strip() == "AGENT STEP":
                return json.loads(payload)

    try:
        return await asyncio.wait_for(read_event(), timeout=timeout)
    except TimeoutError as error:
        raise RuntimeError("timed out waiting for the naive agent loop") from error


async def _drive_naive_replacement(
    process: subprocess.Popen[str],
    *,
    status_question: str,
    timeout: float = 10,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Send one question to the replacement process and read its result."""

    if process.stdin is None or process.stdout is None:
        raise RuntimeError("replacement naive Worker pipes are unavailable")
    process.stdin.write(status_question + "\n")
    process.stdin.flush()

    async def read_result() -> tuple[dict[str, object], list[dict[str, object]]]:
        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                raise RuntimeError("replacement naive Worker exited before answering")
            label, separator, raw_payload = line.partition("|")
            if not separator:
                continue
            label = label.strip()
            if label not in {"AGENT RESULT", "AGENT ERROR"}:
                continue
            payload = json.loads(raw_payload)
            if label == "AGENT ERROR":
                raise RuntimeError(
                    "Stripe could not verify the naive outcome: "
                    f"{payload.get('message', 'unknown error')}"
                )
            return dict(payload["agent"]), list(payload["refunds"])

    try:
        return await asyncio.wait_for(read_result(), timeout=timeout)
    except TimeoutError as error:
        raise RuntimeError(
            "timed out waiting for the replacement naive Worker"
        ) from error


def _seed_test_payment(amount_cents: int) -> str:
    stripe.api_key = validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=True)
    stripe.max_network_retries = 0
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        payment_method="pm_card_visa",
        payment_method_types=["card"],
        confirm=True,
        description="plush python (durable refund demo)",
    )
    return str(intent.id)


def _show(console: Console, renderable, cue: str) -> str:
    console.clear()
    console.print(renderable)
    return input(f"\n{cue}  ")


def _ask_for_refund(
    console: Console,
    renderable,
    cue: str,
    *,
    default: str = _DEFAULT_REFUND_REQUEST,
) -> str:
    console.clear()
    console.print(renderable)
    request = input(f"\n{cue}\nyou> ").strip()
    return request or default


async def _drive_naive_loop(
    console: Console,
    process: subprocess.Popen[str],
    *,
    request_text: str,
    amount_cents: int,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Let the real naive subprocess choose and ask each visible question."""

    from refund_agent.naive_refund import _demo_frame

    if process.stdin is None:
        raise RuntimeError("naive Worker input is unavailable")
    steps: list[dict[str, str]] = []
    answers: dict[str, str] = {}
    base = {
        "context": {
            "order": "1234",
            "amount": amount_cents,
            "customer": "Nyghtowl",
        },
        "user_message": request_text,
    }
    while True:
        event = await _read_naive_loop_event(process)
        kind = event.get("kind")
        if kind == "question":
            console.clear()
            console.print(
                _demo_frame(
                    {**base, "_loop_steps": steps, "_pending_question": event},
                    [],
                    stage_mode=True,
                )
            )
            default = event.get("suggested_answer") or ""
            answer = input(f"\nagent> {event.get('question')} [{default}]  ").strip()
            answer = answer or default
            process.stdin.write(answer + "\n")
            process.stdin.flush()
        elif kind in {"answer", "tool"}:
            steps.append(event)
            if kind == "answer":
                answers[event["question_id"]] = event["result"]
        elif kind == "ready":
            steps.append(event)
            return steps, answers


def _loop_steps_from_progress(progress: dict) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for observation in progress.get("working_memory") or []:
        tool = observation.get("tool")
        result = observation.get("result") or {}
        if tool == "customer_answer":
            question_id = str(result.get("question_id") or "")
            steps.append(
                {
                    "kind": "answer",
                    "question_id": question_id,
                    "result": str(result.get("answer") or ""),
                }
            )
        elif tool == "lookup_order":
            steps.append(
                {
                    "kind": "tool",
                    "tool": tool,
                    "label": "Found order",
                    "result": str(result.get("item") or "plush python"),
                }
            )
        elif tool == "lookup_customer_history":
            steps.append(
                {
                    "kind": "tool",
                    "tool": tool,
                    "label": "Checked refund history",
                    "result": "clean",
                }
            )
        elif tool == "check_refund_policy":
            steps.append(
                {
                    "kind": "tool",
                    "tool": tool,
                    "label": "Checked refund policy",
                    "result": "eligible"
                    if result.get("eligible_for_refund")
                    else "not eligible",
                }
            )
    if progress.get("phase") == "ready_to_refund":
        steps.append(
            {"kind": "ready", "label": "Next action", "result": "issue refund"}
        )
    return steps


async def _drive_temporal_loop(
    handle: WorkflowHandle,
    answers: dict[str, str],
    *,
    timeout: float = _DEMO_TIMEOUT_SECONDS,
) -> tuple[str, list[dict[str, str]]]:
    """Fast-forward the same questions and wait for the durable next action."""

    deadline = time.monotonic() + timeout
    approval_sent = False
    sent_questions: set[str] = set()
    last_progress: dict = {}
    while time.monotonic() < deadline:
        try:
            last_progress = await handle.query(RefundWorkflow.stage_progress)
        except Exception:
            await asyncio.sleep(0.1)
            continue
        phase = last_progress.get("phase")
        pending = last_progress.get("pending_question") or {}
        if pending:
            question_id = str(pending.get("question_id") or "")
            if question_id not in sent_questions:
                answer = answers.get(
                    question_id,
                    str(pending.get("suggested_answer") or ""),
                )
                await handle.signal(
                    RefundWorkflow.answer_question,
                    args=[question_id, answer],
                )
                sent_questions.add(question_id)
        elif phase == "waiting_for_approval" and not approval_sent:
            await handle.signal(
                RefundWorkflow.approve,
                "approved by the guided stage runner",
            )
            approval_sent = True
        elif phase == "ready_to_refund":
            return "ready", _loop_steps_from_progress(last_progress)
        elif phase == "denied":
            return "denied", _loop_steps_from_progress(last_progress)
        await asyncio.sleep(0.1)
    raise RuntimeError("timed out waiting for the durable agent loop")


async def _durable_frame(
    client: Client,
    workflow_id: str,
    *,
    recovered: bool = False,
    refund_status: str | None = None,
    loop_steps: list[dict[str, str]] | None = None,
    pending_question: dict[str, str] | None = None,
):
    # The talk path uses plain language. `refund-demo watch` keeps the detailed
    # execution vocabulary for technical exploration.
    from refund_agent import tui

    agent = tui._stage_agent_panel(
        workflow_id,
        recovered=recovered,
        refund_status=refund_status,
        loop_steps=loop_steps,
        pending_question=pending_question,
    )
    system = await tui._stage_system_panel(
        client,
        workflow_id,
        loop_steps=loop_steps,
    )
    return tui._stage_build(agent, system)


async def _denied_frame(client: Client, workflow_id: str):
    from refund_agent import tui

    agent = tui._stage_agent_panel(workflow_id)
    system = tui._stage_system_view(
        status="COMPLETED",
        refund=None,
        pending_attempt=None,
        refund_step_completed=False,
        denied=True,
    )
    return tui._stage_build(agent, system)


async def run(
    *,
    workflow_id: str | None,
    real: bool,
    real_model: bool,
    amount_cents: int,
    model_provider: str | None = None,
    simulate_stripe_retry: bool = False,
) -> None:
    """Run both demos from one guided terminal."""

    from refund_agent.naive_refund import _demo_frame

    console = Console()
    if model_provider and not real_model:
        raise RuntimeError("--model-provider requires --real-model")
    selected_provider = _live_model_provider(model_provider) if real_model else None
    run_token = uuid.uuid4().hex[:8]
    workflow_id = workflow_id or f"talk-refund-{run_token}"
    base_state = state_dir().resolve()
    stage_state = base_state / f"stage-{run_token}"
    stage_state.mkdir(parents=True, exist_ok=True)
    queue = f"refund-stage-{run_token}"
    services = _Services(
        base_state=base_state,
        stage_state=stage_state,
        task_queue=queue,
        effect_restart_window_seconds=(
            _SIMULATED_RETRY_WINDOW_SECONDS if simulate_stripe_retry else 0
        ),
    )
    previous_state_dir = os.environ.get("DEMO_STATE_DIR")
    os.environ["DEMO_STATE_DIR"] = str(stage_state)
    client: Client | None = None
    handle: WorkflowHandle | None = None
    naive_worker: subprocess.Popen[str] | None = None
    completed = False

    try:
        _show(console, _intro(), "Press Enter to begin with the naive agent")

        payment_intent = "pi_dry_run_demo"
        if real:
            with console.status("Creating Nyghtowl's paid Stripe test order..."):
                try:
                    payment_intent = await asyncio.to_thread(
                        _seed_test_payment, amount_cents
                    )
                except stripe.StripeError as error:
                    raise RuntimeError(
                        f"Stripe could not create the test payment: {error}"
                    ) from error

        naive_request = _ask_for_refund(
            console,
            _demo_frame({}, [], stage_mode=True),
            "Ask the agent for a refund",
        )
        naive_worker = _start_naive_at_boundary(
            stage_state,
            amount_cents=amount_cents,
        )
        naive_steps, customer_answers = await _drive_naive_loop(
            console,
            naive_worker,
            request_text=naive_request,
            amount_cents=amount_cents,
        )
        first_attempt = {
            "context": {
                "order": "1234",
                "amount": amount_cents,
                "customer": "Nyghtowl",
            },
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "user_message": naive_request,
            "_loop_steps": naive_steps,
        }
        _show(
            console,
            _demo_frame(
                first_attempt,
                [],
                stage_mode=True,
            ),
            "Press Enter to replace this Worker and reload the agent",
        )
        _stop_naive_worker(naive_worker)
        naive_worker = None
        _show(
            console,
            _demo_frame(
                {"_worker_gone": True},
                [],
                stage_mode=True,
            ),
            "Press Enter to start a replacement Worker",
        )
        naive_worker = _start_naive_replacement(
            stage_state,
            amount_cents=amount_cents,
            payment_intent=payment_intent,
            real=real,
        )
        status_question = _ask_for_refund(
            console,
            _demo_frame(
                {"_restarted": True, "_replacement_worker": True},
                [],
                stage_mode=True,
            ),
            "The replacement Worker has no active loop. Ask what happened",
            default="What happened to my refund?",
        )
        with console.status("Replacement Worker checking the effect owner..."):
            recovered_naive, naive_refunds = await _drive_naive_replacement(
                naive_worker,
                status_question=status_question,
            )
        _show(
            console,
            _demo_frame(
                recovered_naive,
                naive_refunds,
                stage_mode=True,
            ),
            "Press Enter to run the same failure with durable execution",
        )
        _stop_naive_worker(naive_worker)
        naive_worker = None

        with console.status("Preparing Temporal and a private demo Worker..."):
            client = await services.connect_or_start_server()
            await services.start_worker()
        durable_request = _ask_for_refund(
            console,
            await _durable_frame(client, workflow_id),
            "Ask for a refund for order 1234 (the plush python)",
        )
        request = RefundRequest(
            request_id=workflow_id,
            order_id="order-1234",
            customer_id="cus_demo_42",
            payment_intent_id=payment_intent,
            amount_cents=amount_cents,
            reason=durable_request,
            dry_run=not real,
            item_opened=None,
            damage=None,
            refund_destination="Original card",
            interactive_questions=True,
            hold_before_effect=True,
            fast_recovery=True,
            use_canned_agent=not real_model,
            model_provider=selected_provider,
        )
        handle = await client.start_workflow(
            RefundWorkflow.run,
            request,
            id=workflow_id,
            task_queue=queue,
        )
        with console.status(
            "Fast-forwarding the same questions through the durable agent loop..."
        ):
            outcome, durable_steps = await _drive_temporal_loop(
                handle,
                customer_answers,
            )
        if outcome == "denied":
            await handle.result()
            completed = True
            _show(
                console,
                await _denied_frame(client, workflow_id),
                "The model denied this request. Press Enter to exit",
            )
            if real:
                console.print(
                    "A Stripe test payment was created but not refunded. "
                    "Reconcile it with: uv run refund-demo cleanup",
                    style="bold yellow",
                )
            return
        _show(
            console,
            await _durable_frame(
                client,
                workflow_id,
                loop_steps=durable_steps,
            ),
            "Press Enter to replace this Worker after it chooses the refund",
        )

        services.kill_worker()
        await asyncio.sleep(0.25)
        _show(
            console,
            await _durable_frame(
                client,
                workflow_id,
                loop_steps=durable_steps,
            ),
            "Press Enter to reload the agent with a replacement Worker",
        )

        if simulate_stripe_retry:
            with console.status(
                "Calling Stripe, then interrupting before Temporal records it..."
            ):
                await services.start_worker()
                await handle.signal(RefundWorkflow.release)
                effect_outcome = await _wait_for_first_effect(
                    handle,
                    workflow_id,
                    timeout=_DEMO_TIMEOUT_SECONDS,
                )
                if effect_outcome != "effect":
                    raise RuntimeError(
                        "the retry simulation ended before Stripe accepted the refund"
                    )
                services.kill_worker()
                await asyncio.sleep(_SIMULATED_RETRY_DETECTION_SECONDS)
            _show(
                console,
                await _durable_frame(
                    client,
                    workflow_id,
                    loop_steps=durable_steps,
                ),
                "Stripe accepted attempt 1, but the Worker disappeared before "
                "reporting it. Press Enter to start a replacement Worker",
            )
            with console.status(
                "Replacement Worker running Temporal's retry with the same key..."
            ):
                await services.start_worker()
                result = await asyncio.wait_for(
                    handle.result(), timeout=_DEMO_TIMEOUT_SECONDS
                )
        else:
            with console.status(
                "Resuming at the saved next action; no repeated questions..."
            ):
                await services.start_worker()
                await handle.signal(RefundWorkflow.release)
                result = await asyncio.wait_for(
                    handle.result(), timeout=_DEMO_TIMEOUT_SECONDS
                )
        if result.status == "denied":
            completed = True
            _show(
                console,
                await _denied_frame(client, workflow_id),
                "The model denied this request. Press Enter to exit",
            )
            if real:
                console.print(
                    "A Stripe test payment was created but not refunded. "
                    "Reconcile it with: uv run refund-demo cleanup",
                    style="bold yellow",
                )
            return
        completed = True
        _show(
            console,
            await _durable_frame(
                client,
                workflow_id,
                recovered=True,
                refund_status=result.status,
                loop_steps=durable_steps,
            ),
            "Press Enter for the takeaway",
        )
        console.clear()
        console.print(_closing(result.status))
        console.print(f"\nStage logs: {stage_state}", style="dim")
    finally:
        _stop_naive_worker(naive_worker)
        if handle is not None and not completed:
            try:
                await handle.terminate(reason="single-window stage runner closed")
            except Exception:
                pass
        services.close()
        if previous_state_dir is None:
            os.environ.pop("DEMO_STATE_DIR", None)
        else:
            os.environ["DEMO_STATE_DIR"] = previous_state_dir
