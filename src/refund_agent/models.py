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
    dry_run: bool
    # Return details are application input, not facts Stripe can reconstruct
    # from a paid charge. The guided stage stores them in Workflow input so a
    # replacement Worker can continue without asking the customer again.
    item_opened: str = "Yes"
    damage: str = "Split seam"
    refund_destination: str = "Original card"
    # The stage runner pauses after Workflow input is recorded but before the
    # agent loop or refund effect begins. This makes loss of an accepted request
    # visible without pretending Stripe received a call that it did not.
    hold_before_effect: bool = False
    # When set, hold the run open after the refund is issued (a durable wait) so
    # a Worker can be killed and restarted to show replay skipping a step that is
    # already recorded, rather than repeating it.
    hold_after_effect: bool = False
    # The single-window stage runner uses a short Activity heartbeat timeout so
    # recovery is visible without making an audience wait. Normal and real
    # Stripe runs keep the more conservative production-shaped timeout.
    fast_recovery: bool = False
    # The guided talk path is deterministic by default, even when an OpenAI key
    # or Anthropic key is present. Passing --real-model opts back into live
    # model reasoning.
    use_canned_agent: bool = False
    # Record the selected live provider in Workflow input so replacement Workers
    # do not switch providers based on whichever keys happen to be present.
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
    """One turn of the loop: either use a tool or decide."""

    action: str  # use_tool | decide
    tool: str | None = None
    tool_args: dict[str, str] | None = None
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
