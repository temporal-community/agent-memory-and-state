"""The model turn: the agent_decide_next_step Activity and the decision behind it.

decide_next_step picks one turn's next step for both demos: the demo's intake
questions, the fixed policy, or a live OpenAI or Anthropic model with tool
calling. Usage logging for `refund-demo usage` lives here too.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import anthropic
import openai
from anthropic import Anthropic
from anthropic.types import ToolParam
from openai import OpenAI
from openai.types.responses import FunctionToolParam
from temporalio import activity
from temporalio.exceptions import ApplicationError

from refund_agent.activities.tools import TOOL_HISTORY, TOOL_ORDER, TOOL_POLICY
from refund_agent.activities.view import (
    _agent_summary,
    _line,
    _mirror_agent_view,
    _view_for,
)
from refund_agent.models import AgentStep, RefundRequest
from refund_agent.settings import model_usage_path

# Refunds at or below this clear on their own; larger ones escalate to a human.
APPROVE_THRESHOLD_CENTS = 10000


# ---------------------------------------------------------------------------
# The model turn. Dry-run uses a deterministic policy; real uses tool-calling.
# ---------------------------------------------------------------------------


def _observation(working_memory: list[dict], tool: str) -> dict | None:
    for obs in working_memory:
        if obs.get("tool") == tool:
            result = obs.get("result")
            return result if isinstance(result, dict) else None
    return None


def _customer_answer(working_memory: list[dict], question_id: str) -> str | None:
    for observation in working_memory:
        if observation.get("tool") != "customer_answer":
            continue
        result = observation.get("result") or {}
        if result.get("question_id") == question_id:
            return str(result.get("answer") or "")
    return None


def _missing_question_step(working_memory: list[dict]) -> AgentStep | None:
    if _customer_answer(working_memory, "item_opened") is None:
        return AgentStep(
            action="ask_customer",
            question_id="item_opened",
            question="Was the package opened?",
            suggested_answer="Yes",
        )
    if _customer_answer(working_memory, "damage") is None:
        return AgentStep(
            action="ask_customer",
            question_id="damage",
            question="What was damaged?",
            suggested_answer="Split seam",
        )
    return None


def _canned_step(request: RefundRequest, working_memory: list[dict]) -> AgentStep:
    # A deterministic policy for the offline demo. The path still varies with the
    # request: a clean, low-value refund clears in two lookups; a larger one digs
    # into the refund policy and escalates.
    if request.interactive_questions:
        question = _missing_question_step(working_memory)
        if question is not None:
            return question

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


_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "ask_customer",
        "description": "Ask for one missing return detail before deciding.",
        "parameters": {
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "enum": ["item_opened", "damage"],
                },
                "question": {"type": "string"},
                "suggested_answer": {"type": "string"},
            },
            "required": ["question_id", "question", "suggested_answer"],
        },
    },
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
        "description": (
            "Check authoritative refund eligibility and whether a return is required."
        ),
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
    "refund. When interactive_questions is true, use ask_customer to collect "
    "item_opened and damage one at a time unless customer_answer observations "
    "already contain them. Use the other tools to gather what you need, then "
    "call submit_decision. "
    "Treat tool results as authoritative. Approve clear, low-value refunds with "
    "a clean customer history. When the policy tool says eligible, approve; do "
    "not require a physical return when return_required is false. Escalate to a "
    "human when the amount is large or the history looks risky. Deny only when "
    "the request clearly conflicts with the order or policy says it is ineligible."
)

_MODEL_PROVIDERS = {"anthropic", "openai"}


def _selected_model_provider(request: RefundRequest) -> str | None:
    configured = request.model_provider or os.getenv("AGENT_MODEL_PROVIDER")
    if configured:
        provider = configured.strip().lower()
        if provider not in _MODEL_PROVIDERS:
            raise ApplicationError(
                "AGENT_MODEL_PROVIDER must be 'anthropic' or 'openai'",
                type="ModelProviderInvalid",
                non_retryable=True,
            )
        return provider
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _model_view(value: object) -> object:
    """Copy a request or observation for the model, with money in dollars.

    Every amount_cents field becomes amount, rendered as "$80.00", so the model
    never reasons about cents. The stored request and working memory keep cents.
    """

    if isinstance(value, dict):
        view: dict[str, object] = {}
        for key, item in value.items():
            if key == "amount_cents" and isinstance(item, int):
                view["amount"] = _dollars(item)
            else:
                view[key] = _model_view(item)
        return view
    if isinstance(value, list):
        return [_model_view(item) for item in value]
    return value


def _model_payload(request: RefundRequest, working_memory: list[dict]) -> str:
    """The prompt body both providers get: the request and every observation."""

    return json.dumps(
        {
            "request": _model_view(asdict(request)),
            "observations": _model_view(working_memory),
        },
        sort_keys=True,
    )


# COST: which agent made a logged model call, so `refund-demo usage` can report
# Demo 1 (the naive agent process) and Demo 2 (the Temporal Workflow) apart.
USAGE_AGENT_TEMPORAL = "temporal"
USAGE_AGENT_NAIVE = "naive"


def _usage_count(source: object, name: str) -> int:
    return int(getattr(source, name, None) or 0)


def _record_usage(
    path: Path | None,
    provider: str,
    model: str,
    usage: object | None,
    *,
    agent: str = USAGE_AGENT_TEMPORAL,
) -> None:
    """COST: append one model call's token counts when LOG_MODEL_USAGE is on.

    Only counts are written, never prompt text or keys. input_tokens counts every
    prompt token, cached or not. output_tokens already includes reasoning.
    """

    if path is None or usage is None:
        return
    if provider == "openai":
        # OpenAI input_tokens already includes cached and cache-write tokens.
        input_details = getattr(usage, "input_tokens_details", None)
        cached = _usage_count(input_details, "cached_tokens")
        cache_write = _usage_count(input_details, "cache_write_tokens")
        input_tokens = _usage_count(usage, "input_tokens")
        output_details = getattr(usage, "output_tokens_details", None)
        reasoning = _usage_count(output_details, "reasoning_tokens")
    else:
        # Anthropic input_tokens excludes cache reads and writes, so add them.
        cached = _usage_count(usage, "cache_read_input_tokens")
        cache_write = _usage_count(usage, "cache_creation_input_tokens")
        input_tokens = _usage_count(usage, "input_tokens") + cached + cache_write
        output_details = getattr(usage, "output_tokens_details", None)
        reasoning = _usage_count(output_details, "thinking_tokens")
    output_tokens = _usage_count(usage, "output_tokens")
    record: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "agent": agent,
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
    }
    if activity.in_activity():
        info = activity.info()
        record["workflow_id"] = info.workflow_id
        record["activity_attempt"] = info.attempt
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as error:
        # The call is already billed; a failed log write must not retry it.
        _line("MODEL USAGE", f"could not write {path}: {error}")
        return
    _line(
        "MODEL USAGE",
        f"{provider}:{model} input {input_tokens}, output {output_tokens}",
    )


def _openai_step(
    request: RefundRequest,
    working_memory: list[dict],
    api_key: str,
    *,
    agent: str = USAGE_AGENT_TEMPORAL,
) -> AgentStep:
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise ApplicationError(
            "OPENAI_MODEL is required for a real agent run. Set it to a model "
            "your account can access, or run with --dry-run.",
            type="OpenAIModelMissing",
            non_retryable=True,
        )
    # Read before the paid call, so an invalid LOG_MODEL_USAGE fails first.
    usage_path = model_usage_path()
    # Client retries are disabled so Temporal owns every retry decision.
    client = OpenAI(api_key=api_key, max_retries=0, timeout=45.0)
    payload = _model_payload(request, working_memory)
    try:
        response = client.responses.create(
            model=model,
            instructions=_AGENT_INSTRUCTIONS,
            input=payload,
            # The SDK type requires a "strict" key. The schemas leave it out so
            # the API default applies; the cast changes nothing at runtime.
            tools=cast(list[FunctionToolParam], _TOOL_SCHEMAS),
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
    # Log before parsing, so a billed response that fails to parse still counts.
    _record_usage(
        usage_path, "openai", model, getattr(response, "usage", None), agent=agent
    )

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
    if call.name == "ask_customer":
        return AgentStep(
            action="ask_customer",
            question_id=str(args.get("question_id", "")),
            question=str(args.get("question", "")),
            suggested_answer=str(args.get("suggested_answer", "")),
            source=source,
        )
    return AgentStep(
        action="use_tool",
        tool=call.name,
        tool_args={key: str(value) for key, value in args.items()},
        source=source,
    )


def _anthropic_step(
    request: RefundRequest,
    working_memory: list[dict],
    api_key: str,
    *,
    agent: str = USAGE_AGENT_TEMPORAL,
) -> AgentStep:
    model = os.getenv("ANTHROPIC_MODEL")
    if not model:
        raise ApplicationError(
            "ANTHROPIC_MODEL is required for a Claude agent run.",
            type="AnthropicModelMissing",
            non_retryable=True,
        )
    # Read before the paid call, so an invalid LOG_MODEL_USAGE fails first.
    usage_path = model_usage_path()
    tools: list[ToolParam] = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }
        for tool in _TOOL_SCHEMAS
    ]
    payload = _model_payload(request, working_memory)
    # Client retries are disabled so Temporal owns every retry decision.
    client = Anthropic(api_key=api_key, max_retries=0, timeout=45.0)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_AGENT_INSTRUCTIONS,
            messages=[{"role": "user", "content": payload}],
            tools=tools,
            tool_choice={"type": "any", "disable_parallel_tool_use": True},
        )
    except anthropic.APIStatusError as error:
        status = error.status_code
        if status == 429 or status >= 500:
            raise
        raise ApplicationError(
            f"Anthropic returned a permanent error (HTTP {status}): {error}",
            type="AnthropicPermanentError",
            non_retryable=True,
        ) from error
    # Log before parsing, so a billed response that fails to parse still counts.
    _record_usage(
        usage_path, "anthropic", model, getattr(response, "usage", None), agent=agent
    )

    call = next(
        (block for block in response.content if block.type == "tool_use"),
        None,
    )
    if call is None:
        raise ApplicationError(
            "Anthropic returned no tool call for this turn",
            type="AnthropicOutputError",
            non_retryable=True,
        )
    args = dict(call.input)
    source = f"anthropic:{model}"
    if call.name == "submit_decision":
        return AgentStep(
            action="decide",
            recommendation=str(args.get("recommendation", "escalate")),
            rationale=str(args.get("rationale", "")),
            source=source,
        )
    if call.name == "ask_customer":
        return AgentStep(
            action="ask_customer",
            question_id=str(args.get("question_id", "")),
            question=str(args.get("question", "")),
            suggested_answer=str(args.get("suggested_answer", "")),
            source=source,
        )
    return AgentStep(
        action="use_tool",
        tool=call.name,
        tool_args={key: str(value) for key, value in args.items()},
        source=source,
    )


def decide_next_step(
    request: RefundRequest,
    working_memory: list[dict],
    *,
    agent: str = USAGE_AGENT_TEMPORAL,
) -> AgentStep:
    """Choose one turn's next step: the decision both demos' agents share.

    The agent_decide_next_step Activity calls this for Demo 2. Demo 1's naive
    agent process calls it directly, with no Temporal, so both demos run the
    same intake questions, fixed policy, or live model. `agent` only tags the
    usage log.
    """

    required_question = (
        _missing_question_step(working_memory)
        if request.interactive_questions
        else None
    )
    if required_question is not None:
        # Demo-only intake (interactive_questions): the same two questions, in a
        # fixed order, whichever model provider runs. Once the answers exist,
        # the selected model autonomously chooses lookups and the final action.
        return required_question
    if request.use_canned_agent:
        # Demo-only: the fixed policy stands in for the model, so the stage plays
        # the same way every run and makes no model calls. A real app calls its
        # model here.
        return _canned_step(request, working_memory)
    provider = _selected_model_provider(request)
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ApplicationError(
                "OPENAI_API_KEY is required for the OpenAI provider.",
                type="OpenAIKeyMissing",
                non_retryable=True,
            )
        return _openai_step(request, working_memory, api_key, agent=agent)
    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ApplicationError(
                "ANTHROPIC_API_KEY is required for the Anthropic provider.",
                type="AnthropicKeyMissing",
                non_retryable=True,
            )
        return _anthropic_step(request, working_memory, api_key, agent=agent)
    if request.dry_run:
        # Offline runs with no model configured fall back to the fixed policy.
        return _canned_step(request, working_memory)
    raise ApplicationError(
        "A live model key is required for a real run. Configure "
        "Anthropic or OpenAI, or use --dry-run for the offline policy.",
        type="ModelKeyMissing",
        non_retryable=True,
    )


@activity.defn
def agent_decide_next_step(
    request: RefundRequest, working_memory: list[dict]
) -> AgentStep:
    """MODEL REASONING: one turn of the agent loop."""

    workflow_id = activity.info().workflow_id
    view = _view_for(workflow_id)
    if not working_memory:
        # Turn one: reset this run's in-process view and show the context.
        view.clear()
        view["context"] = asdict(request)
        print("=" * 64, flush=True)
        _line(
            "CONTEXT",
            f"refund request {request.request_id}: order {request.order_id}, "
            f"${request.amount_cents / 100:.2f}, customer {request.customer_id}",
        )

    step = decide_next_step(request, working_memory)

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
    elif step.action == "ask_customer":
        _line(
            "MODEL REASONING",
            f"turn {turn}: next action -> ask {step.question_id}",
        )
    else:
        _line("MODEL REASONING", f"turn {turn}: plan -> call {step.tool}")
    _mirror_agent_view(workflow_id, view)
    _line("THE AGENT", f"in process: {_agent_summary(view)}")
    return step
