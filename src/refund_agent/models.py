"""Small serializable values that cross Temporal history boundaries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RefundRequest:
    """CONTEXT: the request carried through one agent run."""

    request_id: str
    order_id: str
    customer_id: str
    payment_intent_id: str
    amount_cents: int
    reason: str
    # Offline ledger switch (demo-only). True sends the refund to the local Stripe
    # stand-in in fake_stripe.py, so the demo runs without a Stripe key. With no
    # model key set, it also falls back to the fixed policy. A real app always
    # calls its payment provider.
    dry_run: bool
    # A normal CLI request carries these answers up front. The guided stage
    # leaves item_opened and damage empty and sets interactive_questions, so the
    # agent loop asks for them instead.
    item_opened: str | None = "Yes"
    damage: str | None = "Split seam"
    refund_destination: str = "Original card"
    # Demo-only switches, all off by default. They make the demo repeatable and
    # quick to watch; a real app needs none of them.
    # interactive_questions: ask the two intake questions first, in a fixed
    # order, so both demos ask the same thing and the stage can send Demo 1's
    # answers into Demo 2 as Signals.
    interactive_questions: bool = False
    # hold_before_effect: the pause before the refund. The Workflow waits for
    # the `release` Signal right before issue_refund, so the stage can stop the
    # Worker at the same point every run. A real Workflow goes straight on.
    hold_before_effect: bool = False
    # hold_after_effect: for the manual walkthrough (refund-demo start --hold).
    # The run waits for `release` after the refund is recorded, so a Worker
    # restart shows replay skipping that step instead of repeating it.
    hold_after_effect: bool = False
    # fast_recovery: set only by the stage runner. With a failure drill below,
    # the refund Activity gets a 3 s heartbeat timeout, so attempt 2 shows
    # within seconds. Other runs, including the default stage run, keep 15 s.
    # It also gives every stage run a 6-minute start-to-close timeout instead
    # of 1 minute. See refund_activity_timeouts.
    fast_recovery: bool = False
    # simulate_stripe_timeout: failure drill (stage --simulate-stripe-timeout).
    # Attempt 1 hangs before calling Stripe, like an API that never answers; the
    # stage kills the Worker, and a new Worker runs attempt 2 normally.
    simulate_stripe_timeout: bool = False
    # simulate_stripe_retry: failure drill (stage --simulate-stripe-retry). The
    # stage kills the Worker after Stripe accepts attempt 1 (the Worker's
    # EFFECT_RESTART_WINDOW_SECONDS holds that attempt open). This flag only
    # selects the 3 s heartbeat timeout; issue_refund never reads it.
    simulate_stripe_retry: bool = False
    # use_canned_agent: a fixed policy stands in for the model, so the guided
    # stage plays the same way every run, even when a model key is set.
    # --real-model turns it off. A real app calls its model.
    use_canned_agent: bool = False
    # Not a demo switch. Record the selected live provider in Workflow input so
    # replacement Workers do not switch providers based on whichever keys happen
    # to be present.
    model_provider: str | None = None


@dataclass(frozen=True)
class OrderDetails:
    """Domain facts that are copied into working memory by a tool."""

    order_id: str
    item: str
    amount_cents: int
    status: str
    purchased_at: str


@dataclass(frozen=True)
class CustomerHistory:
    """Domain facts that are copied into working memory by a tool."""

    customer_id: str
    account_tenure_days: int
    purchases: list[str]
    prior_refunds: list[str]


@dataclass(frozen=True)
class ReturnStatus:
    """Domain state that is copied into working memory by a tool."""

    order_id: str
    eligible_for_refund: bool
    return_required: bool
    returned: bool
    received_back: bool
    note: str


@dataclass(frozen=True)
class AgentStep:
    """One turn: ask the customer, use a tool, or decide."""

    action: str  # ask_customer | use_tool | decide
    tool: str | None = None
    tool_args: dict[str, str] | None = None
    question_id: str | None = None
    question: str | None = None
    suggested_answer: str | None = None
    recommendation: str | None = None  # approve | escalate | deny
    rationale: str | None = None
    source: str = "canned"


@dataclass(frozen=True)
class RefundDecision:
    """The decision the agent reached, recorded as an Activity result."""

    recommendation: str
    rationale: str
    source: str


@dataclass(frozen=True)
class RefundResult:
    """The known result after the external effect Activity completes."""

    refund_id: str
    status: str
    amount_cents: int
    idempotency_key: str
    activity_attempt: int
    mode: str
