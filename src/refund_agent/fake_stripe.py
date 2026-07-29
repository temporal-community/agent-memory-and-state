"""A tiny persistent Stripe stand-in for the offline stage path."""

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from refund_agent.settings import state_dir

_LOCK = threading.Lock()


def idempotency_key_for(workflow_id: str) -> str:
    """Derive a stable Stripe idempotency key from the Workflow ID."""

    digest = hashlib.sha256(workflow_id.encode("utf-8")).hexdigest()
    return f"durable-refund-{digest}"


def ledger_path() -> Path:
    return state_dir() / "dry-run-stripe.json"


def _read_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"refunds": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def create_refund(
    *,
    workflow_id: str,
    payment_intent_id: str,
    amount_cents: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Return the first result for every later call with the same key."""

    path = ledger_path()
    with _LOCK:
        ledger = _read_ledger(path)
        refunds = ledger.setdefault("refunds", {})
        existing = refunds.get(idempotency_key)
        if existing is not None:
            same_parameters = (
                existing["payment_intent_id"] == payment_intent_id
                and existing["amount_cents"] == amount_cents
            )
            if not same_parameters:
                raise ValueError("Idempotency key was reused with different parameters")
            existing["calls"] += 1
            _write_ledger(path, ledger)
            return dict(existing)

        refund_id = f"re_dry_{idempotency_key.rsplit('-', 1)[-1][:16]}"
        refund = {
            "refund_id": refund_id,
            "status": "succeeded",
            "workflow_id": workflow_id,
            "payment_intent_id": payment_intent_id,
            "amount_cents": amount_cents,
            "idempotency_key": idempotency_key,
            "calls": 1,
        }
        refunds[idempotency_key] = refund
        _write_ledger(path, ledger)
        return dict(refund)


def find_refund(workflow_id: str) -> dict[str, Any] | None:
    # Match by the stored workflow_id field rather than re-deriving the key. The
    # idempotency key is derived from the workflow RUN identity, which callers do
    # not hold, so scan the ledger and return the latest run's refund for this
    # Workflow.
    path = ledger_path()
    with _LOCK:
        ledger = _read_ledger(path)
    match = None
    for refund in ledger.get("refunds", {}).values():
        if refund.get("workflow_id") == workflow_id:
            match = refund  # keep the last (most recent) matching run
    return dict(match) if match is not None else None
