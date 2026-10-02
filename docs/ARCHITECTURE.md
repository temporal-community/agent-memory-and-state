# Architecture and code tour

Back to the [README](../README.md). This page holds the long description of
the diagram in [How it works](../README.md#how-it-works), the full loop sketch,
every command entry point, the repository map, and the test commands.

## How the stage is wired

`uv run refund-demo stage`
([`src/refund_agent/stage.py`](../src/refund_agent/stage.py)) is the only command
you run.

For Demo 1, it launches a naive agent subprocess
([`naive_refund.py`](../src/refund_agent/naive_refund.py)) and talks to it over
stdin and stdout. The subprocess runs scripted steps and keeps the customer's
answers in a local dictionary. After it is killed, a new subprocess only reads
the effect owner. Offline, that is its own `naive-ledger.json`; with `--real`,
it retrieves the PaymentIntent and its refund list from Stripe test mode.

For Demo 2, the stage connects to a Temporal dev server at `localhost:7233`, or
starts one. It starts the `RefundApprovalAgent` Workflow, sends
`customer_answer` and `release` Signals, and polls the `stage_progress` Query
while a Worker runs. It also reads Event History for each durable frame; the
`WORKER GONE` frame takes its counts from that history, because no Worker is
running to answer a Query.

A separate Worker subprocess ([`worker.py`](../src/refund_agent/worker.py)) polls
a private task queue, `refund-stage-<token>`. It runs the Workflow loop
([`workflow.py`](../src/refund_agent/workflow.py)) and its Activities:

- `agent_decide_next_step`: a deterministic policy by default, or Claude or
  OpenAI with `--real-model`. Each call carries the summary
  `Agent turn N: decide the next step`, shown in Event History
- three fixture lookups: `lookup_order`, `lookup_customer_history`, and
  `check_refund_policy`
- `issue_refund`, which writes one refund keyed by
  `durable-refund-<sha256 of workflow_id:run_id>`. Offline, it writes to
  `effect-ledger.json`, a different file from the naive ledger; with `--real`,
  it calls Stripe test mode.

The stage SIGKILLs that Worker while the Workflow waits at `ready_to_refund`,
then starts a replacement. The replacement rebuilds the loop by replaying Event
History.

## The agent loop is ordinary Python

The production Workflow lives in
[`src/refund_agent/workflow.py`](../src/refund_agent/workflow.py). This condensed
sketch shows the loop:

```python
decision: RefundDecision | None = None

for turn in range(MAX_TURNS):  # MAX_TURNS = 10
    step = await workflow.execute_activity(
        agent_decide_next_step,
        args=[request, self.working_memory],
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=_MODEL_RETRY,  # up to 5 attempts per model turn
        summary=f"Agent turn {turn + 1}: decide the next step",
    )

    if step.action == "decide":
        decision = RefundDecision(
            recommendation=step.recommendation or "escalate",
            rationale=step.rationale or "",
            source=step.source,
        )
        break

    if step.action == "ask_customer":
        await workflow.wait_condition(answer_arrived)  # customer_answer Signal
        self.working_memory.append(customer_answer)
        continue

    result = await self._run_tool(step.tool, request)
    self.working_memory.append({"tool": step.tool, "result": result})

if decision is None:
    raise ApplicationError(
        "agent did not reach a decision within the turn budget",
        type="AgentLoopExhausted",
        non_retryable=True,
    )

if decision.recommendation == "deny":
    return RefundResult(...)

if decision.recommendation != "approve":
    await workflow.wait_condition(lambda: self.approved)  # approve Signal

if request.hold_before_effect:
    # Stage only: park at the next action so the Worker kill lands at the
    # same point every time. The stage sends `release` after the restart.
    await workflow.wait_condition(lambda: self.released)

# 15 s heartbeat; issue_refund heartbeats while it waits on Stripe. Only the
# stage's --simulate-stripe-* runs use 3 s. Stage runs get a 6 min
# start-to-close, others 1 min.
heartbeat_timeout, start_to_close_timeout = refund_activity_timeouts(request)
return await workflow.execute_activity(
    issue_refund,
    args=[request, decision, self.working_memory],
    heartbeat_timeout=heartbeat_timeout,
    start_to_close_timeout=start_to_close_timeout,
    schedule_to_close_timeout=timedelta(minutes=10),
    retry_policy=RetryPolicy(maximum_attempts=10, ...),
)
```

On the stage path, the two intake questions are asked by code before any model
or policy step (`refund-demo start` leaves them off). The model, or the
deterministic policy, chooses the lookups and the decision. The loop is
bounded, Workflow state replays deterministically, and every external call runs
as an Activity.

The change from a plain in-process loop is small. This repo's naive process is
scripted, so the left column is a generic loop, not code from this repo:

| Plain in-process loop | Temporal Workflow loop |
| --- | --- |
| `step = agent_decide_next_step(request, memory)` | `step = await workflow.execute_activity(agent_decide_next_step, args=[request, self.working_memory], ...)` |
| `answer = input(question)` | A `customer_answer` Signal, then `await workflow.wait_condition(...)` |
| `memory.append(result)`, held in RAM | `self.working_memory.append(result)`, rebuilt by replay after a restart |

## Useful commands

| Command | Purpose |
| --- | --- |
| `uv run refund-demo stage` | Run the recommended one-window talk path |
| `uv run naive-refund` | Explore the uncoordinated agent interactively |
| `uv run refund-worker` | Start the Temporal Worker for manual runs |
| `uv run refund-demo watch <id>` | Watch context and memory beside authoritative state |
| `uv run refund-demo inspect <id>` | Inspect a Workflow and its effect calls |
| `uv run refund-demo usage --state-dir <path>` | Sum a run's logged model tokens and dollars (needs `LOG_MODEL_USAGE=1`) |
| `uv run permission-chat --panes` | Run the authorization companion demo |

## Repository map

```text
src/refund_agent/workflow.py       durable agent loop and Signals
src/refund_agent/activities.py     model, tool, and refund side effects
src/refund_agent/stage.py          guided one-window talk runner
src/refund_agent/tui.py            stage panels and the Event History read
src/refund_agent/naive_refund.py   uncoordinated comparison
src/refund_agent/fake_stripe.py    offline effect ledger
src/refund_agent/permission_chat.py authorization-state companion
assets/                            generated demo reel and screenshots
docs/                              concepts, talk notes, and detailed demo guides
tests/                             agent, effect, stage, and settings tests
```

## Tests and visual assets

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev python scripts/render_demo_frames.py
```
