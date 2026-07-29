from dataclasses import asdict

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


def _drive_canned(request: RefundRequest, max_turns: int = 6):
    working_memory: list[dict] = []
    tools_used: list[str] = []
    for _ in range(max_turns):
        step = _canned_step(request, working_memory)
        if step.action == "decide":
            return step.recommendation, tools_used
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


def test_canned_large_refund_escalates() -> None:
    recommendation, tools = _drive_canned(_request(15000))
    assert recommendation == "escalate"
    assert TOOL_POLICY in tools


class _FakeCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.type = "function_call"
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, output: list) -> None:
        self.output = output


class _FakeResponses:
    def __init__(self, output: list) -> None:
        self._output = output

    def create(self, **_kwargs):
        return _FakeResponse(self._output)


class _FakeClient:
    def __init__(self, output: list) -> None:
        self.responses = _FakeResponses(output)


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
