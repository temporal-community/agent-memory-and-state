# Ten-minute talk run of show

## North star

> A refund can succeed while the agent forgets it still owes the customer an
> answer.

The audience should leave with three ideas:

1. Context, memory, and state can all inform an agent.
2. The effect owner can prove what happened without knowing which application
   work still needs to finish.
3. Temporal lets a reloaded agent reconnect to that unfinished work. A stable
   identity connects execution recovery to the effect owner's record.

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
retrieval, summaries, and long-term memory. But remembering what the customer
said is not the same as remembering that your application still owes them an
answer.

A refund can succeed while the agent forgets it is in the middle of helping the
customer.”

“I am going to lose a real process at the worst possible boundary twice. What
changes is how execution progress is recorded and whether the effect keeps a
stable identity.”

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

### 1:30–3:15 — Naive recovery waits for the customer

**Say before sending the request**

“The left side is this agent session. The right side is the refund system.”

**Action**

At the `you>` prompt, ask the agent for the refund in your own words. The refund
commits, but confirmation does not reach the conversation. Pause with the
successful refund record visible on the right, then press Enter to replace the
Worker.

**Say over the one-refund frame**

“The refund system has the answer: the refund succeeded. But no durable
execution remembers that this customer is still waiting for that answer.”

**Action**

The screen reloads with `REPLACEMENT WORKER`, no chat history, and the same
successful refund record on the right. Ask, “Did I get my refund?” Pause on the
agent's “Let me check” and successful answer.

**Say**

“And that answer is correct. Stripe kept the authoritative fact. But notice who
restarted the work: the customer. This is a new reconciliation triggered by a
new message, not the interrupted interaction resuming.”

**Checkpoint:** `THE CUSTOMER RESTARTED THE WORK` must be visible by **3:15**.

### 3:15–3:45 — Separate the two questions

**Ask the audience**

“Who knows whether the refund happened? Stripe. Who knows that this customer is
still waiting for an answer?”

Pause briefly.

“In the naive system, nobody—until the customer comes back. Effect state tells
us what happened. Execution state tells the application what still needs to
finish.”

**Action**

Press Enter to prepare the durable version.

### 3:45–6:30 — Temporal recovery knows where to continue

**Say before sending the request**

“Now Temporal owns execution progress. The effect owner still owns the refund.
Temporal does not replace Stripe and does not turn the two systems into one
transaction.”

**Action**

At the `you>` prompt, ask the Temporal-backed agent for the refund. On the
in-flight frame, point out:

- Temporal: the refund step is still open; the Worker has not reported back.
- Refund system: the refund succeeded; one call produced one refund.
- Temporal has not received the completion yet.

The live request must refer to order 1234 or the plush python. The stage's fixed
policy record says this low-value damaged item is eligible without a physical
return. Asking to refund a different item may correctly produce a denial.
Rehearse the live model against the offline ledger before adding `--real`.

**Say**

“This is the uncertain boundary: the world changed, but the Worker has not
reported completion.”

**Action**

Press Enter to replace the Worker. Hold the `WORKER GONE` frame for three
seconds.

**Say while pointing right**

“The context and working view disappeared with the Worker. Temporal still owns
where execution stands. The effect system still owns the refund outcome. The
Worker is disposable; the execution is not.”

**Action**

Press Enter to start the replacement Worker. After recovery, point to `calls 2`
and `unique refunds 1`, but make the left pane the headline: `NO NEW CUSTOMER
REQUEST` and “Your refund is complete.”

**Say**

“On the naive side, Stripe had the right answer, but the customer had to come
back and ask for it. Here they asked once. The reloaded agent reconnects to the
same work and can say, ‘Your refund is complete.’ Temporal retried the unresolved
step with the same operation identity, and the effect owner returned the
original result: two calls, one refund.”

**Checkpoint:** The recovered result should be visible by **6:30**.

### 6:30–8:30 — Explain the mechanism

**Say**

“There are two owners and one identity:

- Temporal owns the Workflow's execution progress and retry.
- Stripe owns whether the refund committed.
- The Workflow run identity becomes the Stripe idempotency key.”

“That Workflow identity is also how the reloaded agent reconnects to existing
work instead of starting another refund.”

“Temporal does not promise exactly-once calls. We observed two calls. It gives
the attempt a durable recovery point and stable identity so the retry can
reconcile with the system that owns the effect instead of guessing from
memory.”

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

“The agent loop is ordinary Python. The irreversible operation crosses an
Activity boundary. Temporal records the attempt, detects Worker loss, and
retries. Inside the Activity, the Workflow run identity becomes the effect's
idempotency key.”

Do not explain the full agent loop, history replay algorithm, retry policy, or
SDK syntax unless asked.

### 9:30–10:00 — Close

**Say**

“Memory and state both inform the agent, but they have different operational
roles.

Memory helps choose the next action.

The effect owner knows what happened.

Execution state remembers what still needs to finish.”

“Do not ask agent memory to serve as proof of an external effect. Give the work
a durable execution owner, and carry one identity across the systems that must
recover it.”

## Stage controls

| Control | Screen or action | Target time |
| --- | --- | --- |
| Enter | Empty naive agent | 0:45 |
| Type refund request | Your message and the successful refund record remain visible | 1:45 |
| Enter | Replacement Worker opens with no chat history | 2:05 |
| Ask “Did I get my refund?” | New agent checks Stripe; `THE CUSTOMER RESTARTED THE WORK` appears | 2:45 |
| Enter | Empty durable agent | 3:45 |
| Type refund request | Effect accepted; completion uncertain | 4:30 |
| Enter | Current Worker replaced; `WORKER GONE` | 5:15 |
| Enter | Reloaded agent answers without customer follow-up | 6:15 |
| Enter | Final takeaway | 9:30 |

## If time slips

- **Behind at 3:15:** Ask the audience question without waiting for answers.
- **Behind at 6:30:** Say the two-owner explanation over the recovered frame.
- **Behind at 8:30:** Skip the code excerpt entirely.
- **Never cut:** `NO NEW CUSTOMER REQUEST`, “Your refund is complete,” or the
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

| Attempt | Mode | Total | Manual recovery by 3:15 | No-follow-up payoff | Owners named | No “exactly once” claim | Close from memory | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |

## Likely questions after the talk

**Why not query Stripe before refunding?**

You should query authoritative effect state when answering what happened; the
naive demo now does. That still does not remember which interrupted application
work is waiting for the answer. For issuing or retrying a refund, a separate
read followed by a write can also race with another caller, so a stable
idempotency key remains important.

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
