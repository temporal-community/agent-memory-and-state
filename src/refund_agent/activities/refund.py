"""The one external effect: the issue_refund Activity.

It sends one refund with an idempotency key derived from the Workflow run, to
the offline ledger by default or to Stripe test mode with --real. Stripe's own
retries are off, so every retry is a Temporal Activity attempt.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import asdict
from datetime import timedelta

import stripe
from temporalio import activity
from temporalio.exceptions import ApplicationError

from refund_agent.activities.view import _line, _mirror_agent_view, _view_for
from refund_agent.fake_stripe import create_refund, idempotency_key_for, record_effect
from refund_agent.models import RefundDecision, RefundRequest, RefundResult
from refund_agent.settings import effect_restart_window_seconds, validate_stripe_key

# ---------------------------------------------------------------------------
# The one external effect.
# ---------------------------------------------------------------------------

# Stripe's HTTP client waits up to 80 s by default. The refund call instead
# allows 3 s to connect and 10 s of silence while reading Stripe's response,
# given as (connect, read) seconds the way the requests library takes them.
# Those limits apply per socket operation, so they are not a wall-clock bound;
# issue_refund heartbeats while it waits (_call_with_heartbeats), so a slow but
# live call is not mistaken for a lost Worker. A hung call fails on these
# timeouts, and Temporal retries it with the same idempotency key.
STRIPE_TIMEOUT_SECONDS = (3.0, 10.0)

# Like the Stripe SDK, honor a Retry-After of up to 60 s and ignore longer ones.
_STRIPE_MAX_RETRY_AFTER_SECONDS = 60


def _stripe_error_is_retryable(error: stripe.StripeError) -> bool:
    """Return whether a failed refund call deserves another Temporal attempt.

    With max_network_retries = 0 the SDK never retries, so the Activity retry
    policy decides and every attempt shows in Temporal. Stripe's own signals
    come first, as in the SDK's retry logic: a connection error's should_retry
    (true for a timeout or dropped connection, false for an SSL failure), then a
    Stripe-Should-Retry response header. Otherwise, as with the model calls, 429
    and 5xx are retried, and so is 409, which Stripe returns while an earlier
    call with the same idempotency key is still running. Every attempt reuses
    that key, so a retry cannot create a second refund. Other 4xx errors, such
    as a bad PaymentIntent, fail without a retry.
    """

    if isinstance(error, stripe.APIConnectionError):
        return bool(error.should_retry)
    should_retry = (error.headers or {}).get("stripe-should-retry")
    if should_retry in ("true", "false"):
        return should_retry == "true"
    status = error.http_status or 0
    return status in (409, 429) or status >= 500


def _stripe_retry_delay(error: stripe.StripeError) -> timedelta | None:
    """Return the wait Stripe asked for in Retry-After, if it sent one."""

    try:
        seconds = int((error.headers or {}).get("retry-after", ""))
    except (TypeError, ValueError):
        return None
    if 0 < seconds <= _STRIPE_MAX_RETRY_AFTER_SECONDS:
        return timedelta(seconds=seconds)
    return None


def _call_with_heartbeats(call, *args):
    """Run a blocking call on a helper thread, heartbeating each second.

    The heartbeat then means the Worker is alive, however long the call takes.
    The start-to-close timeout still bounds the attempt.
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(call, *args)
        while True:
            try:
                return future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                activity.heartbeat("waiting on Stripe")


def _real_stripe_refund(
    request: RefundRequest, workflow_id: str, idempotency_key: str
) -> dict[str, object]:
    secret_key = validate_stripe_key(
        os.getenv("STRIPE_API_KEY"),
        required=True,
    )
    stripe.api_key = secret_key
    stripe.max_network_retries = 0
    stripe.default_http_client = stripe.RequestsClient(timeout=STRIPE_TIMEOUT_SECONDS)
    refund = stripe.Refund.create(
        payment_intent=request.payment_intent_id,
        amount=request.amount_cents,
        reason="requested_by_customer",
        metadata={
            "temporal_workflow_id": workflow_id,
            "temporal_idempotency_key": idempotency_key,
        },
        idempotency_key=idempotency_key,
    )
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "amount_cents": refund.amount,
    }


@activity.defn
def issue_refund(
    request: RefundRequest,
    decision: RefundDecision,
    working_memory: list[dict] | None = None,
) -> RefundResult:
    """EXTERNAL EFFECT: issue one idempotency-keyed refund."""

    info = activity.info()
    workflow_id = info.workflow_id
    if workflow_id is None:
        raise ApplicationError(
            "issue_refund must run inside a Workflow",
            type="MissingWorkflowIdentity",
            non_retryable=True,
        )

    # IDEMPOTENCY KEY: derived from the workflow RUN identity. It stays stable
    # across a restart retry (the same run keeps its run id) but is fresh for a
    # brand new run, so reusing a workflow id never collides with an earlier
    # run's effect.
    run_id = info.workflow_run_id
    idempotency_key = idempotency_key_for(f"{workflow_id}:{run_id}")

    # Rebuild THE AGENT view from the recovered steps, so a Worker resuming this
    # effect after a restart repopulates its in-process panel instead of staying
    # blank. Temporal restored working_memory by replay; this only shows it.
    if working_memory is None:
        working_memory = []
    view = _view_for(workflow_id)
    view["context"] = asdict(request)
    view["observations"] = working_memory
    view["decision"] = {
        "recommendation": decision.recommendation,
        "rationale": decision.rationale,
        "source": decision.source,
    }
    _mirror_agent_view(workflow_id, view)

    _line(
        "EXECUTION STATE",
        f"issuing refund: attempt {info.attempt}, decision "
        f"{decision.recommendation}, idempotency key ...{idempotency_key[-8:]}",
    )

    if request.simulate_stripe_timeout and info.attempt == 1:
        # Failure drill (demo-only, stage --simulate-stripe-timeout). Attempt 1
        # hangs before the effect, like a call to a Stripe API that never
        # answers, so Stripe accepts nothing. The stage kills this Worker; after
        # the heartbeat timeout, Temporal schedules attempt 2, which waits for a
        # new Worker. A real app has no such branch: a real hang fails on
        # STRIPE_TIMEOUT_SECONDS, and Temporal retries it.
        _line(
            "THE SYSTEM",
            "Stripe API is not responding (simulated); no refund accepted",
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        raise ApplicationError(
            "simulated Stripe API timeout",
            type="StripeAPITimeout",
        )

    if request.dry_run:
        # Offline ledger (demo-only): the local Stripe stand-in in fake_stripe.py
        # takes the refund and honors the idempotency key the same way, so the
        # demo runs without a Stripe key. A real app calls Stripe, as below.
        try:
            effect = create_refund(
                workflow_id=workflow_id,
                payment_intent_id=request.payment_intent_id,
                amount_cents=request.amount_cents,
                idempotency_key=idempotency_key,
            )
        except ValueError as error:
            raise ApplicationError(
                str(error),
                type="IdempotencyConflict",
                non_retryable=True,
            ) from error
        mode = "dry-run"
    else:
        try:
            effect = _call_with_heartbeats(
                _real_stripe_refund, request, workflow_id, idempotency_key
            )
        except stripe.StripeError as error:
            message = getattr(error, "user_message", None) or str(error)
            if _stripe_error_is_retryable(error):
                # Fail this attempt only. The retry policy runs the next one
                # with the same idempotency key, after Retry-After if Stripe
                # sent one.
                raise ApplicationError(
                    f"Stripe refund call failed (retryable): {message}",
                    type="StripeRetryableError",
                    next_retry_delay=_stripe_retry_delay(error),
                ) from error
            # A bad PaymentIntent or similar cannot be fixed by retrying, so
            # fail fast with a readable message instead of retrying and then
            # surfacing an opaque "Activity task failed".
            raise ApplicationError(
                f"Stripe rejected the refund: {message}",
                type="StripeRefundError",
                non_retryable=True,
            ) from error
        mode = "stripe-test"
        # Mirror the real refund locally so the panel can show one refund and
        # its call count. Stripe stays the system of record.
        try:
            record_effect(
                workflow_id=workflow_id,
                refund_id=str(effect["refund_id"]),
                status=str(effect["status"]),
                amount_cents=int(effect["amount_cents"]),
                payment_intent_id=request.payment_intent_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as error:
            raise ApplicationError(
                str(error),
                type="IdempotencyConflict",
                non_retryable=True,
            ) from error

    _line(
        "THE SYSTEM",
        f"refund accepted at Stripe: {effect['refund_id']} "
        f"({mode}, attempt {info.attempt})",
    )

    # Demo-only restart window (EFFECT_RESTART_WINDOW_SECONDS, 0 by default). The
    # retry drill (stage --simulate-stripe-retry) and the manual walkthrough in
    # docs/GUIDE.md set it, so a kill can land after Stripe accepts the refund
    # but before Temporal records it. A real Activity returns right away.
    restart_window = effect_restart_window_seconds()
    if info.attempt == 1 and restart_window > 0:
        _line(
            "EXECUTION STATE",
            f"restart window open {restart_window:.0f}s; run: refund-demo kill-worker",
        )
        # This pause is intentionally after the effect and before completion.
        # Heartbeats keep attempt 1 alive until the process is actually killed.
        deadline = time.monotonic() + restart_window
        while time.monotonic() < deadline:
            activity.heartbeat("effect accepted, result not reported")
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    if request.hold_after_effect and info.attempt == 1:
        # Demo-only cue for the manual walkthrough (refund-demo start --hold).
        # This only prints the next steps; the wait itself is in the Workflow,
        # after this result is recorded. Kill and restart the Worker then;
        # replay sees this step already done and does not repeat it. Then
        # send `release`.
        _line(
            "EXECUTION STATE",
            "refund recorded; holding for release. kill-worker now, restart, "
            f"then: refund-demo release {workflow_id}",
        )

    return RefundResult(
        refund_id=str(effect["refund_id"]),
        status=str(effect["status"]),
        amount_cents=int(effect["amount_cents"]),
        idempotency_key=idempotency_key,
        activity_attempt=info.attempt,
        mode=mode,
    )
