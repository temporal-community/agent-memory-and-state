<div align="center">

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Temporal Python SDK](https://img.shields.io/badge/Temporal_Python_SDK-1.30%2B-635bff)](https://github.com/temporalio/sdk-python)
[![Stripe](https://img.shields.io/badge/Stripe-test_mode_only-635bff?logo=stripe&logoColor=white)](https://docs.stripe.com/test-mode)
[![uv](https://img.shields.io/badge/run_with-uv-de5fe9)](https://docs.astral.sh/uv/)

</div>

# Agent Memory and State

**A visual Python demo showing how an agent can remember the conversation and
still forget the work.**

The same completed return form goes through two plain-Python agents. The naive
Worker accepts it, then disappears before calling Stripe. Stripe correctly says
the order is paid and no refund exists, but it cannot recover form answers it
never received. The durable agent reconnects to the existing Temporal Workflow,
resumes the submitted request, and reports completion without form re-entry.

There is no agent framework. The point is to make the boundary between context,
memory, and authoritative state visible.

## See the idea in 15 seconds

| Moment | Naive agent | Durable agent |
| --- | --- | --- |
| **Before the request** | Nyghtowl's plush python is paid in Stripe | The same paid order |
| **Form submitted** | Accepted only in Worker memory; Stripe has no refund request | Recorded as Temporal Workflow input; Stripe still has no refund request |
| **Worker disappears** | The completed form disappears | The process view disappears; the submitted form survives |
| **Agent reloads** | Checks Stripe correctly: paid, no refund. Customer must re-enter the form | Reconnects to the same Workflow; **no form re-entry** |
| **Outcome** | Nothing can continue the lost application request | The existing work resumes and issues the refund |

## The boundary that matters

The useful distinction is operational role and authority, not storage
technology or lifespan. Context, memory, and state can all inform an agent, and
representations of all three can be stored in a database. Ask one question:

> When two copies disagree, which record wins?

| Role | What it answers | Authority |
| --- | --- | --- |
| **Context** | What does the model see for this decision? | Assembled for the current turn |
| **Memory** | What retained or retrieved information does the agent use to reason? | The agent or its memory system |
| **Execution state** | Where does the work stand? | Temporal |
| **Effect state** | Did the refund actually commit? | Stripe |
| **Authorization state** | May the agent act? | The authorization system |
| **Domain state** | What are the business facts? | The application database |

These roles are not mutually exclusive buckets for bytes. Order facts can be
domain state in the application database, copied into the agent's memory, and
then assembled into model context. A database that stores the agent's own
recollections is a memory store; a database that owns the current order record
is authoritative domain state. When copies disagree, the role and owner—not the
database technology—determine which record wins.

The guided demo uses an even earlier gap: the application accepts a completed
return form and disappears before calling Stripe. Stripe can prove the payment
is still paid and that no refund exists. What Stripe cannot own is application
input it never received: whether the package was opened, what was damaged, and
where the customer wanted the refund. Without durable execution state, the
customer must enter that information again.

The later boundary is also important: an application can disappear after
Stripe commits a refund but before the result returns. The manual technical
walkthrough keeps that case because it requires retrying with a stable effect
identity. The ten-minute stage path leads with the form-loss case because its
customer cost is immediately visible.

A durable job table or a carefully built state machine can also provide
execution state. Temporal is the implementation used here: it records the open
operation, retries uncertain work with a stable identity, and supplies the point
from which the application resumes.

Read [Memory, state, and authority](docs/CONCEPTS.md) for the complete model,
including working and long-term memory, the lifespan framing, and the
exactly-once misconception.

## What this demo proves

- Stripe's authoritative record proves that the payment is paid and no refund
  exists in the naive run.
- Effect state cannot reconstruct a completed form that never reached the
  effect owner.
- Without execution state, recovery requires form re-entry or a custom durable
  state machine.
- A durable Workflow records where the work stands across Worker restarts.
- A reloaded agent can reconnect to that Workflow and report running or
  completed work instead of starting a new operation.
- Stripe remains authoritative about whether the refund exists.
- One Workflow identity can become one effect idempotency key.
- Durable execution does not make effects exactly once; it lets a retry ask the
  effect owner instead of guessing.

## The agent loop is ordinary Python

The production Workflow lives in
[`src/refund_agent/workflow.py`](src/refund_agent/workflow.py). This condensed
sketch shows the loop:

```python
decision: RefundDecision | None = None

for _turn in range(MAX_TURNS):
    step = await workflow.execute_activity(
        agent_step,
        args=[request, self.working_memory],
        start_to_close_timeout=timedelta(seconds=60),
    )

    if step.action == "decide":
        decision = RefundDecision(
            recommendation=step.recommendation or "escalate",
            rationale=step.rationale or "",
            source=step.source,
        )
        break

    result = await self._run_tool(step.tool, request)
    self.working_memory.append({"tool": step.tool, "result": result})

if decision is None:
    raise ApplicationError("agent exhausted its turn budget")

if decision.recommendation == "deny":
    return RefundResult(...)

if decision.recommendation != "approve":
    await workflow.wait_condition(lambda: self.approved)

return await workflow.execute_activity(
    issue_refund,
    args=[request, decision, self.working_memory],
    heartbeat_timeout=timedelta(seconds=15),
)
```

The model chooses an approved tool or reaches a decision. The loop is bounded,
Workflow state replays deterministically, and every external call runs as an
Activity.

## Run the guided demo

Prerequisites:

- Python 3.11 or newer
- [Temporal CLI](https://docs.temporal.io/cli)
- [uv](https://docs.astral.sh/uv/)

Install the project, test tools, and Rich terminal UI:

```bash
uv sync --extra dev --extra tui
```

Run the complete comparison in one fullscreen terminal:

```bash
uv run refund-demo stage
```

The guided runner:

1. Welcomes Nyghtowl back and shows the last plush-python order as `PAID`.
2. Lets you ask for a refund and answer three prefilled return-form questions.
3. Replaces the naive Worker after it accepts the form but before it calls
   Stripe.
4. Lets you ask what happened. The replacement agent correctly finds a paid
   order and no refund, but asks you to enter the lost return details again.
5. Submits the same form as Temporal Workflow input.
6. Replaces the Worker before Stripe is called; Temporal still shows the saved
   refund request and return details.
7. Reloads the agent, resumes the saved form without re-entry, issues the refund,
   and reports completion.

It uses a deterministic policy and offline Stripe-like ledger by default. It
starts a local Temporal dev server only when one is not already reachable and
shuts down only the processes it started.

### Choose how real the run should be

| Command | Model | Refund effect |
| --- | --- | --- |
| `uv run refund-demo stage` | Deterministic | Offline ledger |
| `uv run refund-demo stage --real` | Deterministic | Stripe test mode |
| `uv run refund-demo stage --real-model --model-provider anthropic` | Claude | Offline ledger |
| `uv run refund-demo stage --real --real-model --model-provider anthropic` | Claude | Stripe test mode |
| `uv run refund-demo stage --real-model --model-provider openai` | OpenAI | Offline ledger |

Claude mode requires `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`; OpenAI mode
requires `OPENAI_API_KEY` and `OPENAI_MODEL`. Set `AGENT_MODEL_PROVIDER`, or use
`--model-provider`, when both keys are configured. Real refund mode requires a
Stripe `sk_test_` or `rk_test_` key. Live Stripe keys are rejected. Put local
values in `.env`; exported shell variables take precedence.

In `--real` mode, the runner creates and confirms Nyghtowl's Stripe test
PaymentIntent before the first refund prompt. That is the `PAID` order visible
in both demos; the durable half later refunds that same test payment. If a run
ends before the refund, use `uv run refund-demo cleanup`.

Test a live model against the offline ledger before combining it with `--real`.
The demo uses a fixed, refund-eligible plush-python order, so the spoken request
should refer to order 1234 or the plush python. Its policy record explicitly says
that this low-value damaged item does not require a physical return. If a live
model denies a conflicting request, the stage shows its rationale and the fact
that no refund was issued instead of exiting on an empty screen.

## Read the payoff

The primary payoff is customer-facing:

> Stripe can tell the naive replacement agent that no refund happened. It cannot
> recreate Nyghtowl's lost return form. The durable agent reconnects to the
> submitted form and says, “Your refund is complete,” without re-entry.

The naive answer is not wrong. Stripe is authoritative and should be queried.
The contrast is whether the accepted application work still exists:

| Process-local input | Durable execution |
| --- | --- |
| Stripe says paid with no refund, but it never received the completed form. The customer starts over. | Temporal retains the submitted form, and the replacement Worker continues it without re-entry. |

The durable side has two owners:

- **Temporal** owns the Activity attempt and execution progress.
- **Stripe** owns whether the refund committed.

Stripe's paid charge is not a record of a customer's return request. Temporal
durably records the accepted application work and supplies the recovery point.
At the later uncertain-effect boundary, the shared identity also lets a retry
reconcile with Stripe rather than infer the result from memory.

## Explore the demos

| Guide | Use it for |
| --- | --- |
| [Ten-minute talk run of show](docs/TALK_10_MIN.md) | Timed speaker notes, stage cues, fallbacks, and a rehearsal scorecard |
| [Memory, state, and authority](docs/CONCEPTS.md) | The conceptual boundary and system-of-record model |
| [Manual refund demo](docs/REFUND_DEMO.md) | Multi-terminal setup, uncertain-effect beat, replay case, Stripe mode, and event history |
| [Permission state demo](docs/PERMISSION_DEMO.md) | Why remembered authorization is not current authorization |

### Useful commands

| Command | Purpose |
| --- | --- |
| `uv run refund-demo stage` | Run the recommended one-window talk path |
| `uv run naive-refund` | Explore the uncoordinated agent interactively |
| `uv run refund-worker` | Start the Temporal Worker for manual runs |
| `uv run refund-demo watch <id>` | Watch context and memory beside authoritative state |
| `uv run refund-demo inspect <id>` | Inspect a Workflow and its effect calls |
| `uv run permission-chat --panes` | Run the authorization companion demo |

### Tests and visual assets

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev python scripts/render_demo_frames.py
```

### Repository map

```text
src/refund_agent/workflow.py       durable agent loop and Signals
src/refund_agent/activities.py     model, tool, and refund side effects
src/refund_agent/stage.py          guided one-window talk runner
src/refund_agent/naive_refund.py   uncoordinated comparison
src/refund_agent/fake_stripe.py    offline effect ledger
src/refund_agent/permission_chat.py authorization-state companion
assets/                            generated demo reel and screenshots
docs/                              concepts and detailed demo guides
tests/                             agent, effect, stage, and settings tests
```

## Scope

This is a teaching demo, not a production refund service. It has no
authentication, production database, web application, multi-agent
orchestration, or operational hardening.

The demo shows Temporal capturing and replaying execution state. It does not
prescribe how an agent memory system should be stored or managed. Where durable
execution and long-term agent memory best fit together remains an open design
question.

## Acknowledgments

Thanks to Cecil for the review that shaped how this repository frames memory
and state.
