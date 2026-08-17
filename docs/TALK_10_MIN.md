# Ten-minute talk run of show

## North star

> An agent can remember everything the customer said and still lose the work
> they submitted.

The audience should leave with three ideas:

1. Context, memory, and state can all inform an agent.
2. Stripe can prove what reached Stripe, but it cannot recover application work
   it never received.
3. Temporal lets a reloaded agent reconnect to accepted, unfinished work. A
   stable identity also connects later effect retries to Stripe's record.

## Commands

Most practice runs should be deterministic and offline:

```bash
uv run refund-demo stage
```

For a risk-controlled live talk, use a real Stripe test effect with the
deterministic agent:

```bash
uv run refund-demo stage --real
```

For a fully live dress rehearsal or talk, use Claude and Stripe test mode:

```bash
uv run refund-demo stage --real --real-model --model-provider anthropic
```

The model's output is not the claim being demonstrated. `--real` is therefore
the safer on-stage choice when timing and repeatability matter more than proving
that the reasoning turn was live.

## Before going on stage

- Run `uv sync --extra tui` and one complete offline rehearsal.
- Confirm `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, and a Stripe **test-mode** key
  are available if using the fully live command.
- Have a local Temporal dev server running before the talk to remove startup
  latency from the transition between demos. The stage runner will connect to
  it instead of starting another one.
- Make the terminal fullscreen and verify that both panes fit without wrapping.
- Disable notifications and keep `uv run refund-demo stage --real` ready as the
  deterministic-model fallback.

## Run of show

### 0:00–0:45 — Hook

**Say**

“Agents are getting much better at remembering: larger context windows,
retrieval, summaries, and long-term memory. But an agent can remember everything
the customer said and still lose the work they submitted.”

“I am going to replace a real Worker after it accepts a completed return form
but before Stripe receives the refund request. What changes is whether the
application work has a durable owner.”

**Action**

Start `refund-demo stage`. Press Enter once to reveal the empty naive agent.

**Checkpoint:** Say the hook by **0:25** and move on by **0:45**.

### 0:45–1:30 — Three operational roles

**Say**

“Context is what the model sees for this decision.

Memory is retained or retrieved information the agent reasons with.

Authoritative state is an owner's record that grounds and constrains what the
application may safely do.”

“All three can inform the agent. The same order fact can be state in the source
database, memory when the agent retrieves a copy, and context when that copy is
shown to the model. The useful question is: when copies disagree, which record
wins?”

**Action**

Point to the agent view on the left and the effect owner on the right.

**Checkpoint:** Begin the naive failure by **1:30**.

### 1:30–3:15 — The naive Worker loses a submitted form

**Say before sending the request**

“Nyghtowl already bought the plush python. Stripe says the payment is paid. The
left side is this agent session; the right side is what Stripe actually knows.”

**Action**

At the `you>` prompt, ask for a refund. Press Enter through the three prefilled
answers: opened, damage, and refund destination. Pause on `RETURN FORM —
SUBMITTED`, then press Enter to replace the Worker.

**Say over the submitted-form frame**

“The Worker accepted the form, but it only exists in this process. Stripe still
shows paid and no refund because Stripe has not been called.”

**Action**

The screen reloads with `REPLACEMENT WORKER` and the same authoritative Stripe
state on the right. Ask, “What happened to my refund?” Pause on the answer that
no request reached Stripe and the return details must be entered again.

**Say**

“That answer is correct. Stripe can prove there is no refund. But Stripe cannot
recreate whether the package was opened, what was damaged, or where Nyghtowl
wanted the money sent. The customer has to start over.”

**Checkpoint:** `THE CUSTOMER MUST START OVER` must be visible by **3:15**.

### 3:15–3:45 — Separate the two questions

**Ask the audience**

“Stripe says paid and no refund. Is Stripe missing anything?”

Pause briefly.

“No. Stripe is exactly right. The application lost a different fact: a completed
return request had been accepted and still needed to run. Effect state tells us
what reached Stripe. Execution state tells the application what still needs to
finish.”

**Action**

Press Enter to prepare the durable version.

### 3:45–6:30 — Temporal recovery knows where to continue

**Say before sending the request**

“Now Temporal owns the accepted application work. Stripe still owns the payment
and refund. Temporal does not replace Stripe.”

**Action**

At the `you>` prompt, ask the Temporal-backed agent for the refund. The same
return details are submitted as Workflow input. On the saved-request frame,
point out:

- Temporal: refund request saved; return details saved; waiting to continue.
- Stripe: payment paid; no refund yet.
- Both systems are correct, and their records answer different questions.

The live request must refer to order 1234 or the plush python. The stage's fixed
policy record says this low-value damaged item is eligible without a physical
return. Asking to refund a different item may correctly produce a denial.
Rehearse the live model against the offline ledger before adding `--real`.

**Say**

“This is the same boundary as before: the app accepted the form, but Stripe has
not been called. The difference is that accepted work now has a durable owner.”

**Action**

Press Enter to replace the Worker. Hold the `WORKER GONE` frame for three
seconds.

**Say while pointing right**

“The conversation and working view disappeared with the Worker. Temporal still
has the submitted request and every form answer. Stripe still correctly says no
refund. The Worker is disposable; the accepted work is not.”

**Action**

Press Enter to start the replacement Worker. After recovery, make the left pane
the headline: `NO NEW FORM`, `NO RE-ENTRY`, and “Your refund is complete.” Point
right to Stripe's successful refund.

**Say**

“On the naive side, Stripe had the right answer and the customer still had to
re-enter the form. Here the reloaded agent reconnects to the same submitted work
and can say, ‘Your refund is complete.’”

**Checkpoint:** The recovered result should be visible by **6:30**.

### 6:30–8:30 — Explain the mechanism

**Say**

“There are two owners and one identity:

- Temporal owns the Workflow's accepted input and execution progress.
- Stripe owns whether the refund committed.
- The Workflow identity becomes the Stripe idempotency key.”

“That Workflow identity is also how the reloaded agent reconnects to existing
work instead of starting another refund.”

“Today I replaced the Worker before the Stripe call, so the visible payoff was
form recovery. If the Worker instead disappears just after Stripe commits,
Temporal may retry. It does not promise exactly-once calls. The stable identity
lets that retry ask Stripe about the same refund instead of inventing another.”

“That is the relationship between agent memory and durable execution: memory
helps reasoning continue; Temporal helps the operation continue.”

“Could I build this with a database, queue, and reconciliation job? Yes. That is
building execution state. Temporal is the durable execution system in this
demo.”

### 8:30–9:30 — Show only the boundary

Show this condensed excerpt from `src/refund_agent/workflow.py`:

```python
result = await workflow.execute_activity(
    issue_refund,
    args=[request, decision, self.working_memory],
    heartbeat_timeout=heartbeat_timeout,
    retry_policy=RetryPolicy(...),
)
```

**Say**

“The agent loop is ordinary Python. The submitted form is Workflow input, and
the irreversible operation crosses this Activity boundary. Temporal records
where the operation stands. Inside the Activity, the Workflow identity becomes
the effect's idempotency key.”

Do not explain the full agent loop, history replay algorithm, retry policy, or
SDK syntax unless asked.

### 9:30–10:00 — Close

**Say**

“Memory and state both inform the agent, but they have different operational
roles.

Memory helps choose the next action.

Temporal remembers where execution stands.

The effect owner knows whether the world changed.”

“Do not ask agent memory to serve as proof of an external effect. Give the work
a durable execution owner, and carry one identity across the systems that must
recover it.”

## Stage controls

| Control | Screen or action | Target time |
| --- | --- | --- |
| Enter | Empty naive agent | 0:45 |
| Type refund request + Enter through 3 answers | Submitted form is visible; Stripe remains paid with no refund | 1:55 |
| Enter | Replacement Worker opens; submitted form is gone | 2:15 |
| Ask “What happened to my refund?” | Agent checks Stripe; `THE CUSTOMER MUST START OVER` appears | 2:50 |
| Enter | Empty durable agent | 3:45 |
| Type refund request | Temporal shows the saved request and form; Stripe shows no refund | 4:30 |
| Enter | Current Worker replaced; `WORKER GONE` | 5:15 |
| Enter | Reloaded agent answers without form re-entry | 6:15 |
| Enter | Final takeaway | 9:30 |

## If time slips

- **Behind at 3:15:** Ask the audience question without waiting for answers.
- **Behind at 6:30:** Say the two-owner explanation over the recovered frame.
- **Behind at 8:30:** Skip the code excerpt entirely.
- **Never cut:** `NO NEW FORM`, `NO RE-ENTRY`, “Your refund is complete,” or the
  final three lines.

## Practice sequence

1. **Words only:** Walk through the frames offline without a timer.
2. **Timed offline:** Record one complete deterministic run. Target 9:30 so
   applause, latency, and transitions do not push the talk over ten minutes.
3. **Recovery drill:** Practice continuing after a slow model, delayed Worker
   restart, accidental extra Enter, or terminal focus loss.
4. **Dress rehearsal:** Use the venue laptop, display resolution, font size,
   network, and intended live command.
5. **Final run:** Rehearse the opening and closing separately until neither
   depends on the screen.

## Rehearsal scorecard

| Attempt | Mode | Total | Start-over pain by 3:15 | No-re-entry payoff | Owners named | No “exactly once” claim | Close from memory | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |

## Likely questions after the talk

**Why not query Stripe before refunding?**

The naive replacement agent does query Stripe. Stripe correctly says the charge
is paid and no refund exists. That query cannot reconstruct the completed return
form because Stripe never received it. For a later retry, a separate read and
write can also race, so a stable idempotency key remains important.

**Could Stripe handle the retry without Temporal?**

Stripe can make a repeated call safe when the application supplies the same
idempotency key. Temporal remembers that the step still needs resolution after
the original Worker disappears, schedules the retry, preserves the Workflow's
progress, and exposes the result to the reloaded application. A team can build
those pieces with a database, queue, scheduler, and state machine; Temporal is
the durable execution system used here.

**Why not put the execution state in a database?**

You can. A durable operation row plus a queue, retry policy, stable identity,
and reconciliation logic can solve this. A lone done flag written after Stripe
still has a failure gap; a full state machine is durable execution. Temporal is
the implementation shown here.

**Is Temporal the agent's memory?**

No. This demo uses Temporal as authoritative execution state. Agent memory and
Workflow state can inform one another, but they have different ownership and
recovery contracts.

**Is the refund exactly once?**

No. The Activity can call the effect owner more than once. The stable
idempotency key makes those calls resolve to one refund.
