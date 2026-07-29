import pytest

from refund_agent.settings import validate_stripe_key


def test_test_stripe_key_is_accepted() -> None:
    assert validate_stripe_key("sk_test_example", required=True) == "sk_test_example"


def test_live_stripe_key_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="live Stripe key"):
        validate_stripe_key("sk_live_example", required=True)


def test_missing_key_is_allowed_for_dry_run() -> None:
    assert validate_stripe_key(None, required=False) is None
