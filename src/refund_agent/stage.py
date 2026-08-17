"""A guided, single-terminal version of the complete meetup demo.

The stage runner owns the disposable processes it needs. It uses a private task
queue and state directory, so it can start, hard-kill, and replace its Worker
without touching another Worker the presenter may already have running.
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
    thesis.append("An agent can remember the conversation and forget the work.\n\n")
    thesis.append(
        "We will send the same request, lose a real process at the same failure "
        "boundary, then add a durable progress owner and stable effect identity."
    )
    return Group(
        Panel(thesis, title="Agent memory and state", border_style="cyan"),
        _roles(),
    )


def _closing() -> Group:
    result = Text()
    result.append("The agent could rebuild the request and decide again.\n")
    result.append("Only durable records could recover the work safely.\n\n")
    result.append("Naive: two committed refunds.  ", style="bold red")
    result.append("Durable: two calls, one refund.", style="bold green")
    return Group(
        Panel(result, title="The difference", border_style="green"),
        Panel(
            "The agent's view can disappear. The records needed for safe "
            "recovery cannot.",
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
        # Five minutes lets the presenter explain the uncertain boundary before
        # pressing Enter. The stage Workflow gives this Activity a matching
        # six-minute start-to-close budget, then detects the killed Worker in
        # roughly three seconds via its heartbeat timeout.
        environment["EFFECT_RESTART_WINDOW_SECONDS"] = "300"
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
    handle: WorkflowHandle, workflow_id: str, *, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    approval_sent = False
    while time.monotonic() < deadline:
        if find_refund(workflow_id) is not None:
            return
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
                raise RuntimeError("the live model denied the stage refund")
        await asyncio.sleep(0.2)
    raise RuntimeError("timed out waiting for the first refund call")


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


async def _run_naive(
    stage_state: Path, *, crash_after_effect: bool, amount_cents: int
) -> None:
    command = [
        sys.executable,
        "-m",
        "refund_agent.naive_refund",
        "refund",
        "--order",
        "1234",
        "--amount-cents",
        str(amount_cents),
    ]
    if crash_after_effect:
        command.append("--exit-after-effect")
    environment = os.environ.copy()
    environment["DEMO_STATE_DIR"] = str(stage_state)
    result = await asyncio.to_thread(
        subprocess.run,
        command,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    expected = 1 if crash_after_effect else 0
    if result.returncode != expected:
        raise RuntimeError(
            "naive demo process did not exit as expected:\n"
            + (result.stderr or result.stdout)
        )


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


def _ask_for_refund(console: Console, renderable, cue: str) -> str:
    console.clear()
    console.print(renderable)
    request = input(f"\n{cue}\nyou> ").strip()
    return request or _DEFAULT_REFUND_REQUEST


async def _durable_frame(client: Client, workflow_id: str):
    # The talk path uses plain language. `refund-demo watch` keeps the detailed
    # execution vocabulary for technical exploration.
    from refund_agent import tui

    agent = tui._stage_agent_panel(workflow_id)
    system = await tui._stage_system_panel(client, workflow_id)
    return tui._stage_build(agent, system)


async def run(
    *,
    workflow_id: str | None,
    real: bool,
    real_model: bool,
    amount_cents: int,
) -> None:
    """Run both demos from one guided terminal."""

    from refund_agent.naive_refund import _demo_frame

    console = Console()
    if real_model and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("--real-model requires OPENAI_API_KEY")
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
    completed = False

    try:
        _show(console, _intro(), "Press Enter to begin with the naive agent")

        _ask_for_refund(
            console,
            _demo_frame({}, [], stage_mode=True),
            "Ask the agent for a refund",
        )
        with console.status(
            "The naive process is issuing the refund, then crashing..."
        ):
            await _run_naive(
                stage_state,
                crash_after_effect=True,
                amount_cents=amount_cents,
            )
        repeated_request = _ask_for_refund(
            console,
            _demo_frame(
                {"_restarted": True},
                _naive_ledger(stage_state),
                stage_mode=True,
            ),
            "The new session has no history. Ask for the refund again",
        )
        with console.status("A new process is rebuilding context and memory..."):
            await _run_naive(
                stage_state,
                crash_after_effect=False,
                amount_cents=amount_cents,
            )
        recovered_naive = {
            "context": {
                "order": "1234",
                "amount": amount_cents,
                "customer": "42",
            },
            "memory": {"tenure_days": 824, "prior_refunds": 1},
            "recorded": True,
            "note": "new process retrieved the same knowledge and acted again",
            "user_message": repeated_request,
        }
        _show(
            console,
            _demo_frame(
                recovered_naive,
                _naive_ledger(stage_state),
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
            "Ask the Temporal-backed agent for the refund",
        )

        payment_intent = "pi_dry_run_demo"
        if real:
            with console.status("Creating a Stripe test payment to refund..."):
                try:
                    payment_intent = await asyncio.to_thread(
                        _seed_test_payment, amount_cents
                    )
                except stripe.StripeError as error:
                    raise RuntimeError(
                        f"Stripe could not create the test payment: {error}"
                    ) from error
        request = RefundRequest(
            request_id=workflow_id,
            order_id="order-1234",
            customer_id="cus_demo_42",
            payment_intent_id=payment_intent,
            amount_cents=amount_cents,
            reason=durable_request,
            dry_run=not real,
            fast_recovery=True,
            use_canned_agent=not real_model,
        )
        handle = await client.start_workflow(
            RefundWorkflow.run,
            request,
            id=workflow_id,
            task_queue=queue,
        )
        with console.status("The agent is retrieving memory and issuing the refund..."):
            await _wait_for_first_effect(
                handle,
                workflow_id,
                timeout=_DEMO_TIMEOUT_SECONDS,
            )
        _show(
            console,
            await _durable_frame(client, workflow_id),
            "Press Enter to hard-kill the Worker before it reports completion",
        )

        services.kill_worker()
        await asyncio.sleep(0.25)
        _show(
            console,
            await _durable_frame(client, workflow_id),
            "Press Enter to start a fresh Worker",
        )

        with console.status(
            "Replaying recorded state and retrying with the same effect identity..."
        ):
            await services.start_worker()
            await asyncio.wait_for(handle.result(), timeout=_DEMO_TIMEOUT_SECONDS)
        completed = True
        _show(
            console,
            await _durable_frame(client, workflow_id),
            "Press Enter for the takeaway",
        )
        console.clear()
        console.print(_closing())
        console.print(f"\nStage logs: {stage_state}", style="dim")
    finally:
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
