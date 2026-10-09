"""The agent's three lookup tools, each an Activity.

Each one returns a small fixture record and prints what it pulled. The result
becomes part of the agent's working memory.
"""

from __future__ import annotations

from temporalio import activity

from refund_agent.activities.view import _line
from refund_agent.models import CustomerHistory, OrderDetails, ReturnStatus

# Tool names, shared between the loop dispatch and the model.
TOOL_ORDER = "lookup_order"
TOOL_HISTORY = "lookup_customer_history"
TOOL_POLICY = "check_refund_policy"


# ---------------------------------------------------------------------------
# Retrieval tools. Each returns a small fixture and prints what it pulled.
# ---------------------------------------------------------------------------


@activity.defn
def lookup_order(order_id: str) -> OrderDetails:
    """Retrieve domain state and return a copy for working memory."""

    order = OrderDetails(
        order_id=order_id,
        item="python plushy",
        amount_cents=8000,
        status="delivered",
        purchased_at="2026-06-03",
    )
    _line(
        "MEMORY COPY",
        f"lookup_order: {order.item}, ${order.amount_cents / 100:.2f}, {order.status}",
    )
    return order


@activity.defn
def lookup_customer_history(customer_id: str) -> CustomerHistory:
    """Retrieve domain facts and return a copy for working memory."""

    history = CustomerHistory(
        customer_id=customer_id,
        account_tenure_days=824,
        purchases=[
            "2026-06-03, python plushy, $80.00",
            "2026-02-14, mechanical keyboard, $89.00",
            "2025-11-20, rubber duck, $24.00",
        ],
        prior_refunds=["2025-08-09, laptop stickers, $18.00, approved"],
    )
    _line(
        "MEMORY COPY",
        f"lookup_customer_history: {history.account_tenure_days} days, "
        f"{len(history.prior_refunds)} prior",
    )
    return history


@activity.defn
def check_refund_policy(order_id: str) -> ReturnStatus:
    """Retrieve domain state and return a copy for working memory."""

    status = ReturnStatus(
        order_id=order_id,
        eligible_for_refund=True,
        return_required=False,
        returned=False,
        received_back=False,
        note=(
            "eligible for refund; this low-value damaged item does not need to "
            "be returned"
        ),
    )
    _line("MEMORY COPY", f"check_refund_policy: {status.note}")
    return status
