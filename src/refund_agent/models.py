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


@dataclass(frozen=True)
class OrderDetails:
    """MEMORY: order facts the agent retrieves with a tool."""

    order_id: str
    item: str
    amount_cents: int
    status: str
    purchased_at: str


@dataclass(frozen=True)
class CustomerHistory:
    """MEMORY: retrieved facts, separate from the incoming context."""

    customer_id: str
    account_tenure_days: int
    purchases: list[str]
    prior_refunds: list[str]


@dataclass(frozen=True)
class ReturnStatus:
    """MEMORY: whether the item came back, retrieved with a tool."""

    order_id: str
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
