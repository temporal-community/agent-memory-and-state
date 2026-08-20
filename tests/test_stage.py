import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("rich")

from refund_agent.cli import _parser
from refund_agent.naive_refund import _read_real_stripe_state
from refund_agent.settings import agent_view_path
from refund_agent.stage import (
    _ask_for_refund,
    _closing,
    _drive_naive_loop,
    _drive_naive_replacement,
    _live_model_provider,
    _naive_ledger,
    _roles,
    _Services,
    _start_naive_at_boundary,
    _start_naive_replacement,
    _stop_naive_worker,
    _wait_for_first_effect,
    _wait_for_log_text,
    run,
)


class _FakeProcess:
    pid = 4242
    stdin = None
    stdout = None

    def __init__(self) -> None:
        self.running = True

    def poll(self):
        return None if self.running else 0

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: int) -> int:
        self.running = False
        return 0


class _FakeConsole:
    def clear(self) -> None:
        pass

    def print(self, _renderable) -> None:
        pass


class _FakeWorkflowHandle:
    async def signal(self, *_args) -> None:
        pass


def test_stage_command_defaults_to_offline_deterministic_mode() -> None:
    args = _parser().parse_args(["stage"])

    assert args.command == "stage"
    assert args.real is False
    assert args.real_model is False
    assert args.model_provider is None
    assert args.simulate_stripe_retry is False
    assert args.simulate_stripe_timeout is False


def test_stage_can_enable_the_stripe_retry_simulation() -> None:
    args = _parser().parse_args(["stage", "--real", "--simulate-stripe-retry"])

    assert args.real is True
    assert args.simulate_stripe_retry is True


def test_stage_can_enable_the_stripe_timeout_simulation() -> None:
    args = _parser().parse_args(["stage", "--real", "--simulate-stripe-timeout"])

    assert args.real is True
    assert args.simulate_stripe_timeout is True


def test_stripe_retry_simulations_are_mutually_exclusive() -> None:
    with pytest.raises(RuntimeError, match="mutually exclusive"):
        asyncio.run(
            run(
                workflow_id="test-stage",
                real=False,
                real_model=False,
                amount_cents=8000,
                simulate_stripe_retry=True,
                simulate_stripe_timeout=True,
            )
        )


def test_stage_can_wait_for_the_simulated_timeout_log(tmp_path) -> None:
    path = tmp_path / "worker.log"
    path.write_text("Stripe API is not responding (simulated)\n", encoding="utf-8")

    asyncio.run(
        _wait_for_log_text(
            path,
            "Stripe API is not responding (simulated)",
            timeout=0.1,
        )
    )


def test_real_model_mode_requires_an_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_PROVIDER", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        asyncio.run(
            run(
                workflow_id="test-stage",
                real=False,
                real_model=True,
                amount_cents=8000,
            )
        )


def test_stage_accepts_an_explicit_anthropic_provider(monkeypatch) -> None:
    args = _parser().parse_args(
        ["stage", "--real-model", "--model-provider", "anthropic"]
    )

    assert args.real_model is True
    assert args.model_provider == "anthropic"


def test_anthropic_provider_requires_its_key_and_model(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")

    assert _live_model_provider("anthropic") == "anthropic"


def test_live_model_denial_is_a_renderable_outcome(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    path = agent_view_path("denied-workflow")
    path.write_text(
        json.dumps({"decision": {"recommendation": "deny"}}),
        encoding="utf-8",
    )

    outcome = asyncio.run(
        _wait_for_first_effect(
            _FakeWorkflowHandle(),
            "denied-workflow",
            timeout=0.2,
        )
    )

    assert outcome == "denied"


def test_stage_role_copy_separates_context_memory_and_state() -> None:
    text = _roles().renderable.plain

    assert "CONTEXT" in text
    assert "what the agent can see" in text
    assert "MEMORY" in text
    assert "remembers or looks up" in text
    assert "STATE" in text
    assert "act and recover safely" in text


def test_stage_closing_states_the_observable_outcome() -> None:
    panels = list(_closing().renderables)

    assert "agent loop started over" in panels[0].renderable.plain
    assert "reloaded agent resumed at its next action" in panels[0].renderable.plain
    assert "No repeated questions" not in panels[0].renderable.plain
    assert "One submitted request, one refund" not in panels[0].renderable.plain
    assert "Stripe knows what reached Stripe" in panels[1].renderable
    assert (
        "Temporal remembered that the refund step was in progress"
        in panels[1].renderable
    )


def test_stage_accepts_a_spoken_refund_request(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "refund my plush python")

    request = _ask_for_refund(_FakeConsole(), object(), "Ask for a refund")

    assert request == "refund my plush python"


def test_stage_keeps_enter_as_a_refund_shortcut(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    request = _ask_for_refund(_FakeConsole(), object(), "Ask for a refund")

    assert "refund order 1234" in request


def test_stage_can_default_to_the_recovery_question(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    request = _ask_for_refund(
        _FakeConsole(),
        object(),
        "Ask about the refund",
        default="What happened to my refund?",
    )

    assert request == "What happened to my refund?"


def test_stage_reads_scripted_naive_ledger(tmp_path) -> None:
    (tmp_path / "naive-ledger.json").write_text(
        json.dumps(
            {
                "refunds": [
                    {
                        "refund_id": "re_naive_1",
                        "order_id": "1234",
                        "amount_cents": 8000,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _naive_ledger(tmp_path) == [
        {"refund_id": "re_naive_1", "order": "1234", "amount": 8000}
    ]


def test_real_naive_check_reads_stripe_without_creating_a_refund(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    class FakePaymentIntent:
        @staticmethod
        def retrieve(payment_intent_id: str):
            calls["retrieve"] = payment_intent_id
            return SimpleNamespace(status="succeeded")

    class FakeRefund:
        @staticmethod
        def list(**kwargs):
            calls["list"] = kwargs
            return SimpleNamespace(data=[])

        @staticmethod
        def create(**_kwargs):
            raise AssertionError("the naive status check must not submit a refund")

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_demo")
    monkeypatch.setattr(
        "refund_agent.naive_refund.stripe.PaymentIntent", FakePaymentIntent
    )
    monkeypatch.setattr("refund_agent.naive_refund.stripe.Refund", FakeRefund)

    payment_status, refunds = _read_real_stripe_state("pi_demo")

    assert payment_status == "PAID"
    assert refunds == []
    assert calls == {
        "retrieve": "pi_demo",
        "list": {"payment_intent": "pi_demo", "limit": 10},
    }


def test_stage_closing_does_not_call_a_pending_refund_complete() -> None:
    panels = list(_closing("pending").renderables)
    text = panels[0].renderable.plain

    assert "Stripe status: PENDING" in text
    assert "One submitted request, one refund" not in text


def test_naive_worker_runs_questions_and_waits_before_refund(
    tmp_path, monkeypatch
) -> None:
    answers = iter(["", "torn wing"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    process = _start_naive_at_boundary(tmp_path, amount_cents=8000)
    try:
        steps, customer_answers = asyncio.run(
            _drive_naive_loop(
                _FakeConsole(),
                process,
                request_text="refund my plush python",
                amount_cents=8000,
            )
        )

        assert process.poll() is None
        assert customer_answers == {"item_opened": "Yes", "damage": "torn wing"}
        assert [step["kind"] for step in steps] == [
            "answer",
            "answer",
            "tool",
            "tool",
            "ready",
        ]
        assert steps[-1]["result"] == "issue refund"
        assert _naive_ledger(tmp_path) == []
        assert not (tmp_path / "naive-done-1234.json").exists()
    finally:
        _stop_naive_worker(process)

    assert process.poll() is not None


def test_replacement_naive_worker_checks_status_in_its_own_process(tmp_path) -> None:
    process = _start_naive_replacement(
        tmp_path,
        amount_cents=8000,
        payment_intent="pi_dry_run_demo",
        real=False,
    )
    try:
        agent, refunds = asyncio.run(
            _drive_naive_replacement(
                process,
                status_question="What happened to my refund?",
            )
        )

        assert process.poll() is None
        assert agent["_replacement_worker"] is True
        assert agent["_worker_pid"] == process.pid
        assert agent["_status_checked"] is True
        assert agent["_refund_missing"] is True
        assert agent["user_message"] == "What happened to my refund?"
        assert refunds == []
    finally:
        _stop_naive_worker(process)

    assert process.poll() is not None


def test_stage_cleanup_removes_only_its_worker_pid(tmp_path) -> None:
    stage_state = tmp_path / "stage"
    stage_state.mkdir()
    pid_path = stage_state / "worker.pid"
    pid_path.write_text("4242\n", encoding="utf-8")
    services = _Services(
        base_state=tmp_path,
        stage_state=stage_state,
        task_queue="test-stage",
    )
    services.worker = _FakeProcess()

    services.close()

    assert not pid_path.exists()


def test_stage_worker_restart_window_is_opt_in(tmp_path) -> None:
    normal = _Services(
        base_state=tmp_path,
        stage_state=tmp_path / "normal",
        task_queue="normal",
    )
    retry_demo = _Services(
        base_state=tmp_path,
        stage_state=tmp_path / "retry",
        task_queue="retry",
        effect_restart_window_seconds=30,
    )

    assert normal.effect_restart_window_seconds == 0
    assert retry_demo.effect_restart_window_seconds == 30


def test_stage_cleanup_preserves_a_different_worker_pid(tmp_path) -> None:
    stage_state = tmp_path / "stage"
    stage_state.mkdir()
    pid_path = stage_state / "worker.pid"
    pid_path.write_text("9999\n", encoding="utf-8")
    services = _Services(
        base_state=tmp_path,
        stage_state=stage_state,
        task_queue="test-stage",
    )
    services.worker = _FakeProcess()

    services.close()

    assert pid_path.read_text(encoding="utf-8") == "9999\n"
