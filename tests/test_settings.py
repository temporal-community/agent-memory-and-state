import pytest

from refund_agent.settings import (
    agent_view_path,
    effect_restart_window_seconds,
    model_usage_path,
    validate_stripe_key,
)


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
