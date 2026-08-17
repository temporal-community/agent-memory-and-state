"""Deterministic orchestration for the refund agent loop.

The loop is the agent: each turn the model (agent_step) looks at what it knows,
plans, and either calls a tool or decides. Tool results update its view, and it
repeats until it reaches a decision or runs out of turns. All non-deterministic
work is in Activities, so the loop itself replays exactly after a restart.
"""

from dataclasses import asdict
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from refund_agent.activities import (
        agent_step,
        check_refund_policy,
        issue_refund,
        lookup_customer_history,
        lookup_order,
    )
    from refund_agent.models import RefundDecision, RefundRequest, RefundResult

# The loop is bounded so a model that never decides fails loudly instead of
# looping forever.
MAX_TURNS = 6

_MODEL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=5,
)


@workflow.defn(name="RefundApprovalAgent")
class RefundWorkflow:
    """A plain agent loop expressed as durable orchestration.

    The workflow Type shown in the Temporal UI is RefundApprovalAgent; the Python
    class keeps its name so the rest of the code is unchanged.
    """

    def __init__(self) -> None:
        # EXECUTION STATE: Temporal restores all of this by replay after a restart.
        self.approved = False
        self.approval_note = ""
        self.released = False
        self.working_memory: list[dict] = []
        self.stage_phase_value = "starting"

    @workflow.run
    async def run(self, request: RefundRequest) -> RefundResult:
        if request.hold_before_effect:
            # The request and form are already part of Workflow input. This
            # stage-only wait proves that accepted application input survives a
            # Worker replacement before any model or Stripe call begins.
            self.stage_phase_value = "request_saved"
            workflow.logger.info("EXECUTION STATE | phase=request_saved | DURABLE WAIT")
            await workflow.wait_condition(lambda: self.released)
            self.stage_phase_value = "working"
            workflow.logger.info("EXECUTION STATE | phase=request_resumed")

        workflow.logger.info("EXECUTION STATE | phase=agent_loop_start")

        # OBSERVE, REASON, ACT: the loop runs until the agent decides.
        decision: RefundDecision | None = None
        for _turn in range(MAX_TURNS):
            step = await workflow.execute_activity(
                agent_step,
                args=[request, self.working_memory],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_MODEL_RETRY,
            )
            if step.action == "decide":
                decision = RefundDecision(
                    recommendation=step.recommendation or "escalate",
                    rationale=step.rationale or "",
                    source=step.source,
                )
                break
            # A tool the agent chose. Results become part of what it knows.
            result = await self._run_tool(step.tool, request)
            self.working_memory.append({"tool": step.tool, "result": result})
            workflow.logger.info(f"EXECUTION STATE | phase=observed tool={step.tool}")

        if decision is None:
            raise ApplicationError(
                "agent did not reach a decision within the turn budget",
                type="AgentLoopExhausted",
                non_retryable=True,
            )

        workflow.logger.info(
            f"EXECUTION STATE | phase=decided recommendation={decision.recommendation}"
        )

        if decision.recommendation == "deny":
            return RefundResult(
                refund_id="none",
                status="denied",
                amount_cents=request.amount_cents,
                idempotency_key="none",
                activity_attempt=0,
                mode="denied",
            )

        if not decision.recommendation == "approve":
            # Escalate. Treat anything that is not an explicit approve as needing
            # a human, so the irreversible effect never fires without a gate.
            workflow.logger.info(
                "EXECUTION STATE | phase=waiting_for_approval | DURABLE WAIT"
            )
            # DURABLE WAIT: no Worker process has to remain alive here.
            await workflow.wait_condition(lambda: self.approved)
            workflow.logger.info(
                f"EXECUTION STATE | phase=approved note={self.approval_note}"
            )

        # EXTERNAL EFFECT: retries reuse one Stripe idempotency key.
        heartbeat_timeout = timedelta(seconds=3 if request.fast_recovery else 15)
        start_to_close_timeout = timedelta(minutes=6 if request.fast_recovery else 1)
        result = await workflow.execute_activity(
            issue_refund,
            args=[request, decision, self.working_memory],
            start_to_close_timeout=start_to_close_timeout,
            # Schedule-to-close is the total recovery window: how long the Worker
            # may be gone before Temporal gives up on the effect and fails the
            # run. Kept generous so a slow restart on stage still resumes to one
            # refund instead of failing.
            schedule_to_close_timeout=timedelta(minutes=10),
            # Heartbeat timeout is the worker-loss detection window. It must exceed
            # the real Stripe call latency so a slow network call is not mistaken
            # for a dead Worker, while staying short enough to detect a real loss.
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=3),
                maximum_attempts=10,
            ),
        )

        if request.hold_after_effect:
            # DURABLE WAIT after the effect: the refund is already recorded, so a
            # restart here replays that completed step instead of repeating it.
            workflow.logger.info(
                "EXECUTION STATE | phase=holding_after_effect | DURABLE WAIT"
            )
            await workflow.wait_condition(lambda: self.released)

        return result

    async def _run_tool(self, tool: str | None, request: RefundRequest) -> dict:
        # Dispatch is deterministic: the tool name came from a recorded result,
        # and the arguments come from the request, not from the model.
        if tool == "lookup_order":
            result = await workflow.execute_activity(
                lookup_order,
                request.order_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
        elif tool == "lookup_customer_history":
            result = await workflow.execute_activity(
                lookup_customer_history,
                request.customer_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
        elif tool == "check_refund_policy":
            result = await workflow.execute_activity(
                check_refund_policy,
                request.order_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
        else:
            raise ApplicationError(
                f"agent asked for an unknown tool: {tool}",
                type="UnknownTool",
                non_retryable=True,
            )
        return asdict(result)

    @workflow.signal
    def approve(self, note: str = "") -> None:
        # EXECUTION STATE: the approval Signal is persisted in Event History.
        self.approval_note = note
        self.approved = True

    @workflow.signal
    def release(self) -> None:
        # EXECUTION STATE: lets a held run finish once the restart has been shown.
        self.released = True

    @workflow.query
    def stage_phase(self) -> str:
        """Expose the deterministic stage pause without inspecting log timing."""

        return self.stage_phase_value
