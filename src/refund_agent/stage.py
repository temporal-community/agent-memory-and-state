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
_DEFAULT_REFUND_REQUEST = (
    "Please refund order 1234. The plush python arrived with a split seam."
)
_DEFAULT_RETURN_FORM = {
    "item_opened": "Yes",
    "damage": "Split seam",
    "refund_destination": "Original card",
}


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
        "An agent can remember everything the customer said and still lose "
        "the work they submitted.\n\n"
    )
    thesis.append(
        "We will submit the same return form, replace a real Worker before "
        "Stripe receives it, then add a durable owner for that work."
    )
    return Group(
        Panel(thesis, title="Agent memory and state", border_style="cyan"),
        _roles(),
    )


def _closing() -> Group:
    result = Text()
    result.append(
        "Naive: Stripe had no refund, and the customer had to start over.\n",
        style="bold red",
    )
    result.append(
        "Durable: the reloaded agent resumed the submitted form.\n\n",
        style="bold green",
    )
    result.append("No form re-entry.  ", style="bold green")
    result.append("One submitted request, one refund.", style="green")
    return Group(
        Panel(result, title="The difference", border_style="green"),
        Panel(
            "Stripe knows what reached Stripe. Temporal remembers the accepted "
            "application work that still needs to finish.",
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
    def __init__(self, *, base_state: Path, stage_state: Path, task_queue: str) -> None:
        self.base_state = base_state
        self.stage_state = stage_state
        self.task_queue = task_queue
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
        # The guided story now replaces the Worker before Stripe is called. The
        # separate manual demo still covers the uncertain post-effect boundary.
        environment["EFFECT_RESTART_WINDOW_SECONDS"] = "0"
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
    return_form: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    form = return_form or _DEFAULT_RETURN_FORM
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
            "--opened",
            form["item_opened"],
            "--damage",
            form["damage"],
            "--refund-to",
            form["refund_destination"],
            "--hold-before-effect",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_naive_worker(process: subprocess.Popen[str] | None) -> None:
    _stop_process(process, hard=True)
    if process is not None and process.stdout is not None:
        process.stdout.close()


async def _wait_for_naive_request(
    process: subprocess.Popen[str], *, timeout: float = 10
) -> None:
    """Wait until the subprocess has accepted the form into process memory."""

    if process.stdout is None:
        raise RuntimeError("naive Worker output is unavailable")

    async def wait_for_marker() -> None:
        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                output = process.stdout.read()
                raise RuntimeError(
                    "naive Worker exited before accepting the return form:\n" + output
                )
            if line.startswith("REQUEST BUFFER "):
                return

    try:
        await asyncio.wait_for(wait_for_marker(), timeout=timeout)
    except TimeoutError as error:
        raise RuntimeError(
            "timed out waiting for the naive Worker to accept the return form"
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


def _collect_return_form(console: Console, renderable) -> dict[str, str]:
    """Collect three quick, prefilled answers so losing them is concrete."""

    console.clear()
    console.print(renderable)

    def answer(prompt: str, default: str) -> str:
        value = input(f"{prompt} [{default}]  ").strip()
        return value or default

    print("\nRETURN FORM — press Enter to use each prefilled answer")
    return {
        "item_opened": answer("Was it opened?", _DEFAULT_RETURN_FORM["item_opened"]),
        "damage": answer("What is the damage?", _DEFAULT_RETURN_FORM["damage"]),
        "refund_destination": answer(
            "Refund to?", _DEFAULT_RETURN_FORM["refund_destination"]
        ),
    }


async def _wait_for_saved_request(
    handle: WorkflowHandle, *, timeout: float = 10
) -> None:
    """Wait until the Workflow has recorded input and entered its stage pause."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await handle.query(RefundWorkflow.stage_phase) == "request_saved":
                return
        except Exception:
            # The first Workflow task may not have reached this Worker yet.
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError("timed out waiting for Temporal to save the return form")


async def _durable_frame(
    client: Client,
    workflow_id: str,
    *,
    recovered: bool = False,
    form: dict[str, str] | None = None,
    submitted: bool = False,
):
    # The talk path uses plain language. `refund-demo watch` keeps the detailed
    # execution vocabulary for technical exploration.
    from refund_agent import tui

    agent = tui._stage_agent_panel(
        workflow_id,
        recovered=recovered,
        form=form,
        submitted=submitted,
    )
    system = await tui._stage_system_panel(client, workflow_id)
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
        return_form = _collect_return_form(
            console,
            _demo_frame(
                {
                    "context": {
                        "order": "1234",
                        "amount": amount_cents,
                        "customer": "Nyghtowl",
                    },
                    "user_message": naive_request,
                },
                [],
                stage_mode=True,
            ),
        )
        with console.status("The naive Worker is accepting the return form..."):
            naive_worker = _start_naive_at_boundary(
                stage_state,
                amount_cents=amount_cents,
                return_form=return_form,
            )
            await _wait_for_naive_request(naive_worker)
        first_attempt = {
            "context": {
                "order": "1234",
                "amount": amount_cents,
                "customer": "Nyghtowl",
            },
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "user_message": naive_request,
            "return_form": return_form,
            "_form_accepted": True,
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
        status_question = _ask_for_refund(
            console,
            _demo_frame(
                {"_restarted": True},
                [],
                stage_mode=True,
            ),
            "The replacement Worker has no form. Ask what happened",
            default="What happened to my refund?",
        )
        recovered_naive = {
            "context": {
                "order": "1234",
                "amount": amount_cents,
                "customer": "Nyghtowl",
            },
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "_status_checked": True,
            "_refund_missing": True,
            "note": "new process checked Stripe after the customer asked",
            "user_message": status_question,
        }
        _show(
            console,
            _demo_frame(
                recovered_naive,
                [],
                stage_mode=True,
            ),
            "Press Enter to run the same failure with durable execution",
        )

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
            item_opened=return_form["item_opened"],
            damage=return_form["damage"],
            refund_destination=return_form["refund_destination"],
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
        with console.status("Temporal is saving the submitted return form..."):
            await _wait_for_saved_request(handle)
        _show(
            console,
            await _durable_frame(
                client,
                workflow_id,
                form=return_form,
                submitted=True,
            ),
            "Press Enter to replace this Worker before Stripe is called",
        )

        services.kill_worker()
        await asyncio.sleep(0.25)
        _show(
            console,
            await _durable_frame(client, workflow_id),
            "Press Enter to reload the agent with a replacement Worker",
        )

        with console.status(
            "Resuming the saved form; no re-entry or new request needed..."
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
            await _durable_frame(client, workflow_id, recovered=True),
            "Press Enter for the takeaway",
        )
        console.clear()
        console.print(_closing())
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
