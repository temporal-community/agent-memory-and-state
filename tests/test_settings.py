import pytest

from refund_agent.settings import (
    agent_view_path,
    effect_restart_window_seconds,
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
