import pytest

from refund_agent.fake_stripe import (
    create_refund,
    find_refund,
    idempotency_key_for,
    record_effect,
)


def test_idempotency_key_is_stable_and_workflow_scoped() -> None:
    first = idempotency_key_for("refund-one")
    again = idempotency_key_for("refund-one")
    second = idempotency_key_for("refund-two")

    assert first == again
    assert not first == second
    assert first.startswith("durable-refund-")


def test_dry_run_refund_is_deduplicated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    key = idempotency_key_for("refund-test")
    arguments = {
        "workflow_id": "refund-test",
        "payment_intent_id": "pi_test",
        "amount_cents": 4200,
        "idempotency_key": key,
    }

    first = create_refund(**arguments)
    second = create_refund(**arguments)

    assert first["refund_id"] == second["refund_id"]
    assert first["calls"] == 1
    assert second["calls"] == 2


def test_find_refund_matches_by_workflow_id(tmp_path, monkeypatch) -> None:
    # issue_refund stores under a RUN-scoped key; find_refund only has the
    # workflow id, so it must match on the stored workflow_id field.
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    run_key = idempotency_key_for("wf-1:run-abc")
    create_refund(
        workflow_id="wf-1",
        payment_intent_id="pi_test",
        amount_cents=8000,
        idempotency_key=run_key,
    )

    found = find_refund("wf-1")

    assert found is not None
    assert found["workflow_id"] == "wf-1"
    assert found["idempotency_key"] == run_key
    assert find_refund("wf-missing") is None


def test_real_effect_mirror_rejects_conflicting_idempotency_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path))
    arguments = {
        "workflow_id": "wf-1",
        "refund_id": "re_1",
        "status": "pending",
        "amount_cents": 8000,
        "payment_intent_id": "pi_1",
        "idempotency_key": "stable-key",
    }

    first = record_effect(**arguments)
    second = record_effect(**{**arguments, "status": "succeeded"})

    assert first["calls"] == 1
    assert second["calls"] == 2
    assert second["status"] == "succeeded"
    with pytest.raises(ValueError, match="different parameters"):
        record_effect(**{**arguments, "amount_cents": 9000})
