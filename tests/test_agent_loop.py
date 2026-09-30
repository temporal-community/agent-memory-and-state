import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from refund_agent.activities import (
    TOOL_HISTORY,
    TOOL_ORDER,
    TOOL_POLICY,
    _canned_step,
    check_refund_policy,
    lookup_customer_history,
    lookup_order,
)
from refund_agent.models import RefundRequest


def _request(amount_cents: int) -> RefundRequest:
    return RefundRequest(
        request_id="r",
        order_id="o1",
        customer_id="c1",
        payment_intent_id="pi",
        amount_cents=amount_cents,
        reason="x",
        dry_run=True,
    )


def _drive_canned(request: RefundRequest, max_turns: int = 10):
    working_memory: list[dict] = []
    tools_used: list[str] = []
    for _ in range(max_turns):
        step = _canned_step(request, working_memory)
        if step.action == "decide":
            return step.recommendation, tools_used
        if step.action == "ask_customer":
            working_memory.append(
                {
                    "tool": "customer_answer",
                    "result": {
                        "question_id": step.question_id,
                        "answer": step.suggested_answer,
                    },
                }
            )
            continue
        tools_used.append(step.tool)
        if step.tool == TOOL_ORDER:
            result = lookup_order(request.order_id)
        elif step.tool == TOOL_HISTORY:
            result = lookup_customer_history(request.customer_id)
        elif step.tool == TOOL_POLICY:
            result = check_refund_policy(request.order_id)
        else:
            raise AssertionError(f"unknown tool {step.tool}")
        working_memory.append({"tool": step.tool, "result": asdict(result)})
    raise AssertionError("canned policy did not decide within the turn budget")


def test_canned_clean_refund_auto_approves() -> None:
    recommendation, tools = _drive_canned(_request(8000))
    assert recommendation == "approve"
    assert tools == [TOOL_ORDER, TOOL_HISTORY]


def test_interactive_agent_asks_each_question_before_using_tools() -> None:
    request = RefundRequest(**{**asdict(_request(8000)), "interactive_questions": True})
    working_memory: list[dict] = []

    opened = _canned_step(request, working_memory)
    assert opened.action == "ask_customer"
    assert opened.question_id == "item_opened"
    working_memory.append(
        {
            "tool": "customer_answer",
            "result": {"question_id": "item_opened", "answer": "Yes"},
        }
    )

    damage = _canned_step(request, working_memory)
    assert damage.action == "ask_customer"
    assert damage.question_id == "damage"


def test_canned_large_refund_escalates() -> None:
    recommendation, tools = _drive_canned(_request(15000))
    assert recommendation == "escalate"
    assert TOOL_POLICY in tools


def test_stage_refund_policy_is_explicitly_eligible_without_a_return() -> None:
    policy = check_refund_policy("order-1234")

    assert policy.eligible_for_refund is True
    assert policy.return_required is False
    assert "eligible for refund" in policy.note


class _FakeCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.type = "function_call"
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, output: list, usage: object | None = None) -> None:
        self.output = output
        self.usage = usage


class _FakeResponses:
    def __init__(self, output: list, usage: object | None = None) -> None:
        self._output = output
        self._usage = usage

    def create(self, **_kwargs):
        return _FakeResponse(self._output, self._usage)


class _FakeClient:
    def __init__(self, output: list, usage: object | None = None) -> None:
        self.responses = _FakeResponses(output, usage)


def test_openai_step_maps_tool_and_decision(monkeypatch) -> None:
    from refund_agent import activities

    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    request = _request(8000)

    monkeypatch.setattr(
        activities,
        "OpenAI",
        lambda **_kw: _FakeClient([_FakeCall("lookup_order", '{"order_id": "o1"}')]),
    )
    step = activities._openai_step(request, [], "key")
    assert step.action == "use_tool"
    assert step.tool == "lookup_order"

    monkeypatch.setattr(
        activities,
        "OpenAI",
        lambda **_kw: _FakeClient(
            [
                _FakeCall(
                    "submit_decision",
                    '{"recommendation": "approve", "rationale": "clean"}',
                )
            ]
        ),
    )
    step = activities._openai_step(request, [], "key")
    assert step.action == "decide"
    assert step.recommendation == "approve"

    monkeypatch.setattr(
        activities,
        "OpenAI",
        lambda **_kw: _FakeClient(
            [
                _FakeCall(
                    "ask_customer",
                    '{"question_id":"damage","question":"What was damaged?",'
                    '"suggested_answer":"Split seam"}',
                )
            ]
        ),
    )
    step = activities._openai_step(request, [], "key")
    assert step.action == "ask_customer"
    assert step.question_id == "damage"


class _FakeAnthropicBlock:
    type = "tool_use"

    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.input = arguments


class _FakeAnthropicResponse:
    def __init__(self, content: list, usage: object | None = None) -> None:
        self.content = content
        self.usage = usage


class _FakeMessages:
    def __init__(self, content: list, usage: object | None = None) -> None:
        self._content = content
        self._usage = usage

    def create(self, **_kwargs):
        return _FakeAnthropicResponse(self._content, self._usage)


class _FakeAnthropicClient:
    def __init__(self, content: list, usage: object | None = None) -> None:
        self.messages = _FakeMessages(content, usage)


def test_anthropic_step_maps_tool_and_decision(monkeypatch) -> None:
    from refund_agent import activities

    monkeypatch.setenv("ANTHROPIC_MODEL", "test-claude")
    request = _request(8000)

    monkeypatch.setattr(
        activities,
        "Anthropic",
        lambda **_kw: _FakeAnthropicClient(
            [_FakeAnthropicBlock("lookup_order", {"order_id": "o1"})]
        ),
    )
    step = activities._anthropic_step(request, [], "key")
    assert step.action == "use_tool"
    assert step.tool == "lookup_order"

    monkeypatch.setattr(
        activities,
        "Anthropic",
        lambda **_kw: _FakeAnthropicClient(
            [
                _FakeAnthropicBlock(
                    "submit_decision",
                    {"recommendation": "approve", "rationale": "clean"},
                )
            ]
        ),
    )
    step = activities._anthropic_step(request, [], "key")
    assert step.action == "decide"
    assert step.recommendation == "approve"

    monkeypatch.setattr(
        activities,
        "Anthropic",
        lambda **_kw: _FakeAnthropicClient(
            [
                _FakeAnthropicBlock(
                    "ask_customer",
                    {
                        "question_id": "damage",
                        "question": "What was damaged?",
                        "suggested_answer": "Split seam",
                    },
                )
            ]
        ),
    )
    step = activities._anthropic_step(request, [], "key")
    assert step.action == "ask_customer"
    assert step.question_id == "damage"


# ---------------------------------------------------------------------------
# COST: opt-in token usage log and its summary.
# ---------------------------------------------------------------------------

_USAGE_KEYS = {
    "timestamp",
    "provider",
    "model",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
}


def _usage_records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_openai_usage_is_logged_as_counts_only(tmp_path, monkeypatch) -> None:
    from refund_agent import activities

    monkeypatch.setenv("LOG_MODEL_USAGE", "1")
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    usage = SimpleNamespace(
        input_tokens=1200,
        input_tokens_details=SimpleNamespace(cached_tokens=200, cache_write_tokens=0),
        output_tokens=360,
        output_tokens_details=SimpleNamespace(reasoning_tokens=300),
    )
    monkeypatch.setattr(
        activities,
        "OpenAI",
        lambda **_kw: _FakeClient(
            [_FakeCall("lookup_order", '{"order_id": "o1"}')], usage
        ),
    )

    activities._openai_step(_request(8000), [], "sk-test-not-logged")

    log = tmp_path / "model-usage.jsonl"
    (record,) = _usage_records(log)
    assert set(record) == _USAGE_KEYS
    assert record["provider"] == "openai"
    assert record["model"] == "test-model"
    assert record["input_tokens"] == 1200
    assert record["cached_input_tokens"] == 200
    assert record["cache_write_tokens"] == 0
    assert record["output_tokens"] == 360
    assert record["reasoning_tokens"] == 300
    # Only counts reach the log: no prompt text and no API key.
    assert "plush" not in log.read_text()
    assert "sk-test-not-logged" not in log.read_text()


def test_anthropic_usage_counts_cache_reads_and_writes_as_input(
    tmp_path, monkeypatch
) -> None:
    from refund_agent import activities

    monkeypatch.setenv("LOG_MODEL_USAGE", "yes")
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-claude")
    # Anthropic reports input_tokens without cache reads or cache writes.
    usage = SimpleNamespace(
        input_tokens=900,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=50,
        output_tokens=120,
        output_tokens_details=None,
    )
    monkeypatch.setattr(
        activities,
        "Anthropic",
        lambda **_kw: _FakeAnthropicClient(
            [_FakeAnthropicBlock("lookup_order", {"order_id": "o1"})], usage
        ),
    )

    activities._anthropic_step(_request(8000), [], "key")

    (record,) = _usage_records(tmp_path / "model-usage.jsonl")
    assert set(record) == _USAGE_KEYS
    assert record["provider"] == "anthropic"
    assert record["input_tokens"] == 1050
    assert record["cached_input_tokens"] == 100
    assert record["cache_write_tokens"] == 50
    assert record["output_tokens"] == 120
    assert record["reasoning_tokens"] == 0


def test_usage_inside_an_activity_names_the_workflow_and_attempt(tmp_path) -> None:
    from temporalio.testing import ActivityEnvironment

    from refund_agent import activities

    log = tmp_path / "model-usage.jsonl"
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)

    ActivityEnvironment().run(
        activities._record_usage, log, "anthropic", "test-claude", usage
    )

    (record,) = _usage_records(log)
    assert record["workflow_id"] == "test"
    assert record["activity_attempt"] == 1


def test_usage_log_is_off_by_default(tmp_path, monkeypatch) -> None:
    from refund_agent import activities

    monkeypatch.delenv("LOG_MODEL_USAGE", raising=False)
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    monkeypatch.setattr(
        activities,
        "OpenAI",
        lambda **_kw: _FakeClient(
            [_FakeCall("lookup_order", '{"order_id": "o1"}')], usage
        ),
    )

    activities._openai_step(_request(8000), [], "key")

    assert not (tmp_path / "model-usage.jsonl").exists()


def test_usage_summary_splits_input_and_prices_each_part() -> None:
    from refund_agent.cli import _LIST_PRICES, _usage_dollars, _usage_totals

    records = [
        {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "input_tokens": 1200,
            "cached_input_tokens": 200,
            "cache_write_tokens": 0,
            "output_tokens": 360,
            "reasoning_tokens": 300,
        },
        {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "input_tokens": 800,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 40,
            "reasoning_tokens": 0,
        },
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "input_tokens": 5000,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 300,
            "reasoning_tokens": 0,
        },
    ]

    totals = _usage_totals(records)

    luna = totals[("openai", "gpt-5.6-luna")]
    assert luna == {
        "calls": 2,
        "uncached_input": 1800,
        "cached_input": 200,
        "cache_write": 0,
        "output": 400,
        "reasoning": 300,
    }
    # 1,800 x $0.20 + 200 x $0.02 + 400 x $1.20, per 1M tokens. Reasoning is
    # already inside output, so it is not charged twice.
    assert _usage_dollars(luna, _LIST_PRICES["gpt-5.6-luna"]) == pytest.approx(0.000844)
    claude = totals[("anthropic", "claude-sonnet-4-6")]
    assert claude["calls"] == 1
    # 5,000 x $3 + 300 x $15, per 1M tokens.
    assert _usage_dollars(claude, _LIST_PRICES["claude-sonnet-4-6"]) == pytest.approx(
        0.0195
    )


def test_usage_command_prints_tokens_and_dollars(tmp_path, capsys) -> None:
    from refund_agent.cli import _parser, _usage

    record = {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "input_tokens": 1200,
        "cached_input_tokens": 200,
        "cache_write_tokens": 0,
        "output_tokens": 360,
        "reasoning_tokens": 300,
    }
    (tmp_path / "model-usage.jsonl").write_text(json.dumps(record) + "\n")

    _usage(_parser().parse_args(["usage", "--state-dir", str(tmp_path)]))
    listed = capsys.readouterr().out

    assert "openai:gpt-5.6-luna" in listed
    assert "1,000 tokens" in listed  # uncached input: 1,200 - 200 cached
    # 1,000 x $0.20 + 200 x $0.02 + 360 x $1.20, per 1M tokens.
    assert "1,560 tokens  $0.000636" in listed
    assert "list prices as of 2026-09-29" in listed

    _usage(
        _parser().parse_args(
            [
                "usage",
                "--state-dir",
                str(tmp_path),
                "--input-price",
                "1",
                "--output-price",
                "10",
            ]
        )
    )
    overridden = capsys.readouterr().out

    # 1,200 input tokens x $1 + 360 output tokens x $10, per 1M tokens.
    assert "$0.004800" in overridden
    assert "your --input-price/--output-price" in overridden
