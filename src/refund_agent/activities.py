"""Activities contain every non-deterministic or fallible operation.

The agent loop lives in the Workflow. Each turn it calls agent_step (the model),
which either asks for a tool or reaches a decision. The tools (lookup_order,
lookup_customer_history, check_refund_policy) are the retrieval the agent does
live, and issue_refund is the one external effect.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict

import openai
import stripe
from openai import OpenAI
from temporalio import activity
from temporalio.exceptions import ApplicationError

from refund_agent.fake_stripe import create_refund, idempotency_key_for
from refund_agent.models import (
    AgentStep,
    CustomerHistory,
    OrderDetails,
    RefundDecision,
    RefundRequest,
    RefundResult,
    ReturnStatus,
)
from refund_agent.settings import (
    effect_restart_window_seconds,
    state_dir,
    validate_stripe_key,
)

# THE AGENT: these caches deliberately live only in this Worker process, keyed
# by Workflow ID so concurrent runs never clobber one another. Temporal never
# reads them. A restart erases them, which is the whole point on stage.
_agent_views: dict[str, dict[str, object]] = {}


def _view_for(workflow_id: str | None) -> dict[str, object]:
    return _agent_views.setdefault(workflow_id or "unknown", {})


# Tool names, shared between the loop dispatch and the model.
TOOL_ORDER = "lookup_order"
TOOL_HISTORY = "lookup_customer_history"
TOOL_POLICY = "check_refund_policy"

# Refunds at or below this clear on their own; larger ones escalate to a human.
APPROVE_THRESHOLD_CENTS = 10000


def _line(label: str, value: object) -> None:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, indent=2, sort_keys=True)
    print(f"{label} | {rendered}", flush=True)


def show_empty_agent_view() -> None:
    _agent_views.clear()
    # A new Worker process holds no agent memory, so wipe the on-disk mirror the
    # TUI reads. After a restart this is what makes THE AGENT panel
    # read empty while THE SYSTEM OF RECORD panel resumes.
    for path in state_dir().glob("agent-view-*.json"):
        path.unlink(missing_ok=True)
    _line("THE AGENT", "new process, in-process view is empty")


def _mirror_agent_view(workflow_id: str | None, view: dict[str, object]) -> None:
    # Mirror the in-process view to disk so the TUI can render THE AGENT panel.
    # The TUI trusts this file only while the Worker PID is alive, so the view
    # still reads as lost the moment the Worker is killed.
    if not workflow_id:
        return
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"agent-view-{workflow_id}.json"
    path.write_text(json.dumps(view, indent=2, sort_keys=True), encoding="utf-8")


def _agent_summary(view: dict[str, object]) -> str:
    # A concise, stage-legible view of what the agent holds in process.
    parts: list[str] = []
    context = view.get("context")
    if isinstance(context, dict):
        parts.append(f"context({context.get('request_id')})")
    observations = view.get("observations")
    if isinstance(observations, list) and observations:
        tools = ", ".join(str(obs.get("tool")) for obs in observations)
        parts.append(f"memory({tools})")
    decision = view.get("decision")
    if isinstance(decision, dict):
        parts.append(f"decision({decision.get('recommendation')})")
    return " + ".join(parts) if parts else "empty"


# ---------------------------------------------------------------------------
# Retrieval tools. Each returns a small fixture and prints what it pulled.
# ---------------------------------------------------------------------------


@activity.defn
def lookup_order(order_id: str) -> OrderDetails:
    """MEMORY: retrieve the order being refunded."""

    order = OrderDetails(
        order_id=order_id,
        item="trail shoes",
        amount_cents=8000,
        status="delivered",
        purchased_at="2026-06-03",
    )
    _line("MEMORY", {"tool": TOOL_ORDER, "result": asdict(order)})
    return order


@activity.defn
def lookup_customer_history(customer_id: str) -> CustomerHistory:
    """MEMORY: retrieve the customer's tenure, purchases, and prior refunds."""

    history = CustomerHistory(
        customer_id=customer_id,
        account_tenure_days=824,
        purchases=[
            "2026-06-03, trail shoes, 12900 cents",
            "2026-02-14, running jacket, 8900 cents",
            "2025-11-20, water bottle, 2400 cents",
        ],
        prior_refunds=["2025-08-09, socks, 1800 cents, approved"],
    )
    _line("MEMORY", {"tool": TOOL_HISTORY, "result": asdict(history)})
    return history


@activity.defn
def check_refund_policy(order_id: str) -> ReturnStatus:
    """MEMORY: retrieve the return status that governs refund eligibility."""

    status = ReturnStatus(
        order_id=order_id,
        returned=False,
        received_back=False,
        note="no return on file",
    )
    _line("MEMORY", {"tool": TOOL_POLICY, "result": asdict(status)})
    return status


# ---------------------------------------------------------------------------
# The model turn. Dry-run uses a deterministic policy; real uses tool-calling.
# ---------------------------------------------------------------------------


def _observation(working_memory: list[dict], tool: str) -> dict | None:
    for obs in working_memory:
        if obs.get("tool") == tool:
            result = obs.get("result")
            return result if isinstance(result, dict) else None
    return None


def _canned_step(request: RefundRequest, working_memory: list[dict]) -> AgentStep:
    # A deterministic policy for the offline demo. The path still varies with the
    # request: a clean, low-value refund clears in two lookups; a larger one digs
    # into the refund policy and escalates.
    done = {obs.get("tool") for obs in working_memory}
    if TOOL_ORDER not in done:
        return AgentStep(
            action="use_tool", tool=TOOL_ORDER, tool_args={"order_id": request.order_id}
        )
    if TOOL_HISTORY not in done:
        return AgentStep(
            action="use_tool",
            tool=TOOL_HISTORY,
            tool_args={"customer_id": request.customer_id},
        )
    history = _observation(working_memory, TOOL_HISTORY) or {}
    prior = len(history.get("prior_refunds") or [])
    clean = request.amount_cents <= APPROVE_THRESHOLD_CENTS and prior <= 1
    if clean:
        return AgentStep(
            action="decide",
            recommendation="approve",
            rationale=(
                "Amount is within the auto-approve threshold and the customer "
                "history is clean."
            ),
        )
    if TOOL_POLICY not in done:
        return AgentStep(
            action="use_tool",
            tool=TOOL_POLICY,
            tool_args={"order_id": request.order_id},
        )
    return AgentStep(
        action="decide",
        recommendation="escalate",
        rationale=(
            "Amount is above the auto-approve threshold, so a human should confirm."
        ),
    )


_TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": TOOL_ORDER,
        "description": "Look up the order being refunded.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "type": "function",
        "name": TOOL_HISTORY,
        "description": "Look up the customer's tenure, purchases, and prior refunds.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    },
    {
        "type": "function",
        "name": TOOL_POLICY,
        "description": "Check whether the refund is within policy (the return status).",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "type": "function",
        "name": "submit_decision",
        "description": "Submit the final decision once you have enough information.",
        "parameters": {
            "type": "object",
            "properties": {
                "recommendation": {
                    "type": "string",
                    "enum": ["approve", "escalate", "deny"],
                },
                "rationale": {"type": "string"},
            },
            "required": ["recommendation", "rationale"],
        },
    },
]

_AGENT_INSTRUCTIONS = (
    "You are a refund agent. Decide whether to approve, escalate, or deny a "
    "refund. Use the tools to gather what you need, then call submit_decision. "
    "Approve clear, low-value refunds with a clean customer history. Escalate to "
    "a human when the amount is large or the history looks risky. Deny only when "
    "the request is clearly invalid."
)


def _openai_step(
    request: RefundRequest, working_memory: list[dict], api_key: str
) -> AgentStep:
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise ApplicationError(
            "OPENAI_MODEL is required for a real agent run. Set it to a model "
            "your account can access, or run with --dry-run.",
            type="OpenAIModelMissing",
            non_retryable=True,
        )
    # Client retries are disabled so Temporal owns every retry decision.
    client = OpenAI(api_key=api_key, max_retries=0, timeout=45.0)
    payload = json.dumps(
        {"request": asdict(request), "observations": working_memory}, sort_keys=True
    )
    try:
        response = client.responses.create(
            model=model,
            instructions=_AGENT_INSTRUCTIONS,
            input=payload,
            tools=_TOOL_SCHEMAS,
            tool_choice="required",
            store=False,
        )
    except openai.APIStatusError as error:
        status = error.status_code
        # Transient conditions (rate limit and server errors) are retryable.
        if status == 429 or status >= 500:
            raise
        # Permanent client errors cannot be fixed by retrying.
        raise ApplicationError(
            f"OpenAI returned a permanent error (HTTP {status}): {error}",
            type="OpenAIPermanentError",
            non_retryable=True,
        ) from error
    # Connection and timeout errors are not APIStatusError, so they propagate as
    # ordinary failures that Temporal retries under the RetryPolicy.

    call = None
    for item in response.output:
        if item.type == "function_call":
            call = item
            break
    if call is None:
        raise ApplicationError(
            "OpenAI returned no tool call for this turn",
            type="OpenAIOutputError",
            non_retryable=True,
        )
    args = json.loads(call.arguments) if call.arguments else {}
    source = f"openai:{model}"
    if call.name == "submit_decision":
        return AgentStep(
            action="decide",
            recommendation=str(args.get("recommendation", "escalate")),
            rationale=str(args.get("rationale", "")),
            source=source,
        )
    return AgentStep(
        action="use_tool",
        tool=call.name,
        tool_args={key: str(value) for key, value in args.items()},
        source=source,
    )


@activity.defn
def agent_step(request: RefundRequest, working_memory: list[dict]) -> AgentStep:
    """MODEL REASONING: one turn of the agent loop."""

    workflow_id = activity.info().workflow_id
    view = _view_for(workflow_id)
    if not working_memory:
        # Turn one: reset this run's in-process view and show the context.
        view.clear()
        view["context"] = asdict(request)
        print("=" * 64, flush=True)
        _line("CONTEXT", asdict(request))

    # The model is real whenever a key is present, independent of the Stripe
    # mode. This lets the loop run with a real model in dry-run (no Stripe key
    # needed). Only a real Stripe run with no key fails loudly.
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        step = _openai_step(request, working_memory, api_key)
    elif request.dry_run:
        step = _canned_step(request, working_memory)
    else:
        raise ApplicationError(
            "OPENAI_API_KEY is required for a real run. Set it, or use --dry-run "
            "for the offline policy.",
            type="OpenAIKeyMissing",
            non_retryable=True,
        )

    view["observations"] = working_memory
    turn = len(working_memory) + 1
    if step.action == "decide":
        view["decision"] = {
            "recommendation": step.recommendation,
            "rationale": step.rationale,
            "source": step.source,
        }
        _line(
            "MODEL REASONING",
            f"turn {turn}: decide -> {step.recommendation} ({step.rationale})",
        )
    else:
        _line("MODEL REASONING", f"turn {turn}: plan -> call {step.tool}")
    _mirror_agent_view(workflow_id, view)
    _line("THE AGENT", f"in process, lost on restart: {_agent_summary(view)}")
    return step


# ---------------------------------------------------------------------------
# The one external effect.
# ---------------------------------------------------------------------------


def _real_stripe_refund(
    request: RefundRequest, workflow_id: str, idempotency_key: str
) -> dict[str, object]:
    secret_key = validate_stripe_key(
        os.getenv("STRIPE_API_KEY"),
        required=True,
    )
    stripe.api_key = secret_key
    stripe.max_network_retries = 0
    refund = stripe.Refund.create(
        payment_intent=request.payment_intent_id,
        amount=request.amount_cents,
        reason="requested_by_customer",
        metadata={
            "temporal_workflow_id": workflow_id,
            "temporal_idempotency_key": idempotency_key,
        },
        idempotency_key=idempotency_key,
    )
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "amount_cents": refund.amount,
    }


@activity.defn
def issue_refund(request: RefundRequest, decision: RefundDecision) -> RefundResult:
    """EXTERNAL EFFECT: issue one idempotency-keyed refund."""

    info = activity.info()
    workflow_id = info.workflow_id
    if workflow_id is None:
        raise ApplicationError(
            "issue_refund must run inside a Workflow",
            type="MissingWorkflowIdentity",
            non_retryable=True,
        )

    # IDEMPOTENCY KEY: derived from the workflow RUN identity. It stays stable
    # across a restart retry (the same run keeps its run id) but is fresh for a
    # brand new run, so reusing a workflow id never collides with an earlier
    # run's effect.
    run_id = info.workflow_run_id
    idempotency_key = idempotency_key_for(f"{workflow_id}:{run_id}")
    _line(
        "EXECUTION STATE",
        {
            "phase": "issuing_refund",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "activity_id": info.activity_id,
            "activity_attempt": info.attempt,
            "decision": asdict(decision),
            "idempotency_key": idempotency_key,
        },
    )

    if request.dry_run:
        try:
            effect = create_refund(
                workflow_id=workflow_id,
                payment_intent_id=request.payment_intent_id,
                amount_cents=request.amount_cents,
                idempotency_key=idempotency_key,
            )
        except ValueError as error:
            raise ApplicationError(
                str(error),
                type="IdempotencyConflict",
                non_retryable=True,
            ) from error
        mode = "dry-run"
    else:
        try:
            effect = _real_stripe_refund(request, workflow_id, idempotency_key)
        except stripe.StripeError as error:
            # A bad PaymentIntent or similar cannot be fixed by retrying, so
            # fail fast with a readable message instead of retrying and then
            # surfacing an opaque "Activity task failed".
            message = getattr(error, "user_message", None) or str(error)
            raise ApplicationError(
                f"Stripe rejected the refund: {message}",
                type="StripeRefundError",
                non_retryable=True,
            ) from error
        mode = "stripe-test"

    _line(
        "THE SYSTEM",
        {
            "stripe_accepted": True,
            "refund_id": effect["refund_id"],
            "status": effect["status"],
            "idempotency_key": idempotency_key,
            "activity_attempt": info.attempt,
            "mode": mode,
        },
    )

    restart_window = effect_restart_window_seconds()
    if info.attempt == 1 and restart_window > 0:
        _line(
            "EXECUTION STATE",
            {
                "restart_window": "open",
                "seconds": restart_window,
                "instruction": "run refund-demo kill-worker now",
            },
        )
        # This pause is intentionally after the effect and before completion.
        # Heartbeats keep attempt 1 alive until the process is actually killed.
        deadline = time.monotonic() + restart_window
        while time.monotonic() < deadline:
            activity.heartbeat("effect accepted, result not reported")
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    return RefundResult(
        refund_id=str(effect["refund_id"]),
        status=str(effect["status"]),
        amount_cents=int(effect["amount_cents"]),
        idempotency_key=idempotency_key,
        activity_attempt=info.attempt,
        mode=mode,
    )
