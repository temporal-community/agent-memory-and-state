"""Activities contain every non-deterministic or fallible operation.

The agent loop lives in the Workflow. Each turn it calls agent_decide_next_step
(the model), which either asks for a tool or reaches a decision. The tools
(lookup_order, lookup_customer_history, check_refund_policy) retrieve domain
records whose results become the agent's working memory, and issue_refund is
the one external effect.

The code is split by role:

- tools.py: the three lookup Activities.
- model.py: agent_decide_next_step, the fixed policy, the live model calls,
  and usage logging.
- refund.py: issue_refund, the Stripe call, and the idempotency key.
- view.py: display helpers that print each step and mirror the agent's
  in-process view for the stage screen. They are not part of Event History.

Every Activity keeps its name, and the names below are re-exported here, so
`from refund_agent.activities import ...` keeps working.
"""

from refund_agent.activities.model import (
    USAGE_AGENT_NAIVE,
    _canned_step,
    _selected_model_provider,
    agent_decide_next_step,
    decide_next_step,
)
from refund_agent.activities.refund import STRIPE_TIMEOUT_SECONDS, issue_refund
from refund_agent.activities.tools import (
    TOOL_HISTORY,
    TOOL_ORDER,
    TOOL_POLICY,
    check_refund_policy,
    lookup_customer_history,
    lookup_order,
)
from refund_agent.activities.view import show_empty_agent_view

__all__ = [
    "STRIPE_TIMEOUT_SECONDS",
    "TOOL_HISTORY",
    "TOOL_ORDER",
    "TOOL_POLICY",
    "USAGE_AGENT_NAIVE",
    "_canned_step",
    "_selected_model_provider",
    "agent_decide_next_step",
    "check_refund_policy",
    "decide_next_step",
    "issue_refund",
    "lookup_customer_history",
    "lookup_order",
    "show_empty_agent_view",
]
