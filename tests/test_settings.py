import ast
import os
import socket
from pathlib import Path

import pytest

from refund_agent.settings import (
    agent_view_path,
    effect_restart_window_seconds,
    model_usage_path,
    temporal_identity,
    validate_stripe_key,
)

_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "refund_agent"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_temporal_identity_keeps_the_pid_and_drops_the_hostname(
    value, monkeypatch
) -> None:
    if value is None:
        monkeypatch.delenv("TEMPORAL_IDENTITY", raising=False)
    else:
        monkeypatch.setenv("TEMPORAL_IDENTITY", value)

    identity = temporal_identity()

    assert identity == f"{os.getpid()}@refund-demo"
    assert socket.gethostname() not in identity


def test_temporal_identity_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("TEMPORAL_IDENTITY", "take-01@studio")

    assert temporal_identity() == "take-01@studio"


def test_every_temporal_client_sets_an_identity() -> None:
    # A Client.connect without identity= falls back to the SDK's
    # "<pid>@<hostname>" and puts the machine name in Temporal Web.
    missing: list[str] = []
    calls = 0
    for path in sorted(_PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "Client"
            ):
                calls += 1
                if "identity" not in {keyword.arg for keyword in node.keywords}:
                    missing.append(f"{path.name}:{node.lineno}")

    assert calls >= 4
    assert missing == []


def test_test_stripe_key_is_accepted() -> None:
    assert validate_stripe_key("sk_test_example", required=True) == "sk_test_example"


def test_live_stripe_key_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="live Stripe key"):
        validate_stripe_key("sk_live_example", required=True)


def test_missing_key_is_allowed_for_dry_run() -> None:
    assert validate_stripe_key(None, required=False) is None


def test_agent_view_path_stays_inside_state_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))

    path = agent_view_path("../../another/workflow")

    assert path.parent == tmp_path
    assert path.name.startswith("agent-view-")
    assert "/" not in path.name


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "not-a-number"])
def test_effect_restart_window_rejects_invalid_values(value, monkeypatch) -> None:
    monkeypatch.setenv("EFFECT_RESTART_WINDOW_SECONDS", value)

    with pytest.raises(RuntimeError, match="finite number"):
        effect_restart_window_seconds()


@pytest.mark.parametrize("value", [None, "", "0", "false", "No"])
def test_model_usage_log_is_off_unless_enabled(value, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    if value is None:
        monkeypatch.delenv("LOG_MODEL_USAGE", raising=False)
    else:
        monkeypatch.setenv("LOG_MODEL_USAGE", value)

    assert model_usage_path() is None


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_model_usage_log_lands_in_state_directory(value, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_MODEL_USAGE", value)

    assert model_usage_path() == tmp_path / "model-usage.jsonl"


def test_model_usage_log_rejects_unclear_values(monkeypatch) -> None:
    monkeypatch.setenv("LOG_MODEL_USAGE", "maybe")

    with pytest.raises(RuntimeError, match="LOG_MODEL_USAGE"):
        model_usage_path()
