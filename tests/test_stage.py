import asyncio
import json

import pytest

pytest.importorskip("rich")

from refund_agent.cli import _parser
from refund_agent.stage import (
    _ask_for_refund,
    _closing,
    _naive_ledger,
    _roles,
    _Services,
    _start_naive_at_boundary,
    _stop_naive_worker,
    _wait_for_naive_effect,
    run,
)


class _FakeProcess:
    pid = 4242

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


def test_stage_command_defaults_to_offline_deterministic_mode() -> None:
    args = _parser().parse_args(["stage"])

    assert args.command == "stage"
    assert args.real is False
    assert args.real_model is False


def test_real_model_mode_requires_an_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        asyncio.run(
            run(
                workflow_id="test-stage",
                real=False,
                real_model=True,
                amount_cents=8000,
            )
        )


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

    assert "customer had to ask again" in panels[0].renderable.plain
    assert "reloaded agent resumed" in panels[0].renderable.plain
    assert "No second request" in panels[0].renderable.plain
    assert "Two calls, one refund" in panels[0].renderable.plain


def test_stage_accepts_a_spoken_refund_request(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "refund my plush python")

    request = _ask_for_refund(_FakeConsole(), object(), "Ask for a refund")

    assert request == "refund my plush python"


def test_stage_keeps_enter_as_a_refund_shortcut(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    request = _ask_for_refund(_FakeConsole(), object(), "Ask for a refund")

    assert "refund order 1234" in request


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


def test_naive_worker_waits_for_replacement_at_the_uncertain_boundary(
    tmp_path,
) -> None:
    process = _start_naive_at_boundary(tmp_path, amount_cents=8000)
    try:
        asyncio.run(_wait_for_naive_effect(process, tmp_path))

        assert process.poll() is None
        assert len(_naive_ledger(tmp_path)) == 1
        assert not (tmp_path / "naive-done-1234.json").exists()
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
