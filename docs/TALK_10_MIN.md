# Ten-minute talk run of show

## North star

> An agent can know exactly what to do and still lose the work a customer
> submitted.

The audience should leave with three ideas:

1. Context, memory, and state can all inform an agent.
2. Process-local working memory can disappear, while Stripe only proves what
   reached Stripe; neither gives a new process the loop's position.
3. Temporal lets a new Worker rebuild that loop's completed steps and
   next action. A stable identity, the Workflow run's, also connects later
   retries to Stripe.

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

- Run `make setup` (`uv sync --extra dev --extra tui`) and one complete
  offline rehearsal (`make run`).
- Confirm `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, and a Stripe **test-mode** key
  are available if using the fully live command.
- Have a local Temporal dev server running before the talk to remove startup
  latency from the transition between demos. The stage runner will connect to
  it instead of starting another one, and Temporal Web stays up at
  <http://localhost:8233> after the stage exits. If another server holds the
  default ports, use the port variant in
  [Watch it in Temporal Web](TEMPORAL_WEB.md).
- Make the terminal fullscreen and verify that both panes fit without wrapping.
- Disable notifications and keep `uv run refund-demo stage --real` ready as the
  deterministic-model fallback.

## Run of show

### 0:00–0:45 — Hook

**Say**

“Agents are getting much better at remembering: larger context windows,
retrieval, summaries, and long-term memory. But working memory is often still
inside one process. An agent can know exactly what to do and still lose the work
a customer submitted.”

“I am going to kill the agent's process after it asks questions, performs
lookups, and chooses the refund as its next action—but before Stripe receives
the request. What changes is whether that loop has a durable owner.”

**Action**

Start `refund-demo stage`. At `Press Enter to start Demo 1 (without Temporal)`,
press Enter once to reveal the empty agent process.

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

### 1:30–3:15 — The naive agent loop loses its place

**Say before sending the request**

“Nyghtowl already bought the python plushy. Stripe says the payment is paid. The
left side is the agent process; the right side, What Survives, is what Stripe
actually knows.”

**Action**

At the `you>` prompt, ask for a refund. The naive side is a scripted process, so
both demos take the same steps; the dim third header line says so
(`Scripted steps · Stripe test mode`, or `offline ledger (no Stripe)` without
`--real`). Press Enter through two prefilled answers: whether the package was
opened and what was damaged. Pause after two automatic lookups when the screen
says `Next: issue refund` and `The demo pauses here, before Stripe.`, then press
Enter at `Press Enter to submit the refund`.

**Say over the completed-loop frame**

“This is the shape of an agent loop: ask, observe, look something up, choose the
next action. It has chosen the refund, but that execution position exists only
in this process. Stripe still shows paid and no refund because it has not been
called.”

**Action**

Hold the `PROCESS GONE` frame for three seconds. The answers and next step are
gone; `WHAT'S LEFT` is Stripe's record, which is correct because Stripe was
never called. Press Enter to start the `NEW AGENT PROCESS`, then ask, “What
happened to my refund?” That question and the Stripe lookup run inside the new
process. Pause on the answer
that no request reached Stripe and the return must start again.

In `--real` mode, that answer comes from retrieving the PaymentIntent and refund
list from Stripe. This is a read only: the naive half never submits the refund.

**Say**

“Stripe's record is correct: no refund happened. But Stripe never owned the
customer's answers or the agent's progress. Those lived in the process, so the
customer starts over.”

**Checkpoint:** `THE CUSTOMER STARTS OVER` must be visible by **3:15**.

### 3:15–3:45 — Separate the two questions

**Ask the audience**

“Stripe says paid and no refund. What tells the new agent that Nyghtowl already
answered the questions and the next action was ‘issue refund’?”

Pause briefly.

“Nothing does. Working memory helped the old agent reason, but disappeared with
it. Effect state says what changed in the world. Execution state says where
this particular autonomous loop stands.”

**Action**

Press Enter at `Press Enter for Demo 2: the same test with Temporal`.

### 3:45–6:30 — Temporal recovery knows where to continue

**Say before sending the request**

“Now the agent still uses working memory to reason, Stripe still owns the
payment and refund, and Temporal owns the submitted loop and its progress.”

**Action**

At the `you>` prompt, ask the Temporal-backed agent for the refund. The runner
replays the same two answers into the Workflow as Signals so the audience does
not repeat them, and the spinner says so: “Reusing your Demo 1 answers so you
don't type them twice.” On the saved-loop frame, point out:

- Temporal, `Saved so far:`: two customer answers, two completed lookups, next
  action `issue refund`, and `(demo pauses here, before Stripe)`.
- Stripe: payment paid; `Refund: none`.
- The left shows what this Worker sees; the right shows what survives it.

The live request must refer to order 1234 or the python plushy. The stage's fixed
policy record says this low-value damaged item is eligible without a physical
return. Asking to refund a different item may correctly produce a denial.
Rehearse the live model against the offline ledger before adding `--real`.

**Say**

“These are the same steps and the same boundary. The difference is that the
completed observations and chosen next action now have a durable owner.”

**Action**

Press Enter at `Press Enter to submit the refund`. The
`WORKER GONE` frame reads Temporal's history as it draws, which can take up to
three seconds. Hold it for three seconds once it appears, and point at
`Read from Temporal just now:` on the right.

**Say while pointing right**

“The in-memory loop disappeared with the Worker. Nothing is
running, and Temporal still has both answers, both lookups, and the next action.
Stripe still correctly says no refund. The Worker is disposable; the loop is
not.”

If the pane instead says `Could not re-read Temporal.`, the counts are the
earlier reading from before the kill. Say so, and use Temporal Web History as the
proof.

**Action**

Press Enter at `Press Enter to start a new Worker`. After recovery, make the
left pane, `NEW TEMPORAL WORKER`, the headline: `NO REPEATED QUESTIONS`,
`NO LOOP RESTART`, “Same loop, rebuilt from Temporal,” and “Your refund is
complete.” Point right to `Refund: SUCCEEDED`.

**Say**

“On the naive side, the working memory disappeared and Stripe only knew that no
refund had arrived. Here a new Worker rebuilds the same loop from
Temporal, continues at its next action, and can say, ‘Your refund is complete’
only after Stripe returns `succeeded`.”

**Checkpoint:** The recovered result should be visible by **6:30**.

### 6:30–8:30 — Explain the mechanism

**Say**

“There are two owners and one identity:

- Temporal owns the Workflow's completed observations and execution progress.
- Stripe owns whether the refund committed.
- The Workflow run's identity becomes the Stripe idempotency key.”

“In a real application, the Workflow ID is how a reloaded agent finds this work
again instead of starting another refund. Here the stage runner simply keeps
it.”

“Today I replaced the Worker before the Stripe call, so the visible payoff was
loop recovery. If the Worker instead disappears just after Stripe commits,
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

“The agent loop is ordinary Python. Customer answers arrive as durable Signals;
lookups and the irreversible operation cross Activity boundaries. Temporal
records the observations and where the loop stands. Inside the refund Activity,
the Workflow run's identity becomes the effect's idempotency key.”

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

For a visible retry without a release Signal, start with `uv run refund-demo
stage --real --simulate-stripe-timeout`. Attempt 1 waits on a simulated
unresponsive Stripe API, the Worker is killed, and attempt 2 remains pending
until you start a new Worker.

For the optional uncertain-effect ending, start with `uv run refund-demo stage
--real --simulate-stripe-retry`. After Stripe accepts attempt 1, the runner
kills the Worker and waits with the Activity unresolved. Press Enter once to
start a new Worker. Temporal's Event History then exposes
`ActivityTaskStarted` attempt 2 with the heartbeat timeout in `lastFailure`.

| Control | Screen or action | Target time |
| --- | --- | --- |
| Enter at `start Demo 1 (without Temporal)` | Empty `AGENT PROCESS` | 0:45 |
| Type refund request + Enter through 2 answers | Four observations and `Next: issue refund` are visible | 1:55 |
| Enter at `kill this agent process` | `PROCESS GONE`; `WHAT'S LEFT` is Stripe's record | 2:10 |
| Enter at `start a new agent process` | `NEW AGENT PROCESS`: “No answers. No next step.” | 2:15 |
| Ask “What happened to my refund?” | Agent checks Stripe; `THE CUSTOMER STARTS OVER` appears | 2:50 |
| Enter at `Demo 2: the same test with Temporal` | Empty `TEMPORAL WORKER` | 3:45 |
| Type refund request | Temporal shows 2 answers, 2 lookups, and the saved next action | 4:30 |
| Enter at `kill this Worker` | `WORKER GONE` with `Read from Temporal just now:` (up to 3 s to appear) | 5:15 |
| Enter at `start a new Worker` | `NEW TEMPORAL WORKER` answers without repeated questions | 6:15 |
| Enter | Final takeaway | 9:30 |

## If time slips

- **Behind at 3:15:** Ask the audience question without waiting for answers.
- **Behind at 6:30:** Say the two-owner explanation over the recovered frame.
- **Behind at 8:30:** Skip the code excerpt entirely.
- **Never cut:** `NO REPEATED QUESTIONS`, `NO LOOP RESTART`, “Your refund is
  complete,” or the final three lines.

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

| Attempt | Mode | Total | Lost-loop pain by 3:15 | Resume-next-action payoff | Owners named | No “exactly once” claim | Close from memory | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |

## Likely questions after the talk

**Why not query Stripe before refunding?**

The new agent process does query Stripe. Stripe correctly says the charge
is paid and no refund exists, but it never received the customer answers or the
agent's progress. A persisted memory system could restore those facts, but it
still would not own the interrupted operation or say which action must resume.
For a later retry, a separate read and write can also race, so a stable
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

**What does it cost to run?**

The deterministic stage, with or without `--real`, makes no model calls: 0
tokens and $0. A live-model pass makes four model calls. GPT-5.6 Luna was
measured on 2026-09-30: 2,492 input and 353 output tokens (114 of them
reasoning), 2,845 tokens in all, $0.0009. Claude Sonnet 4.6 has not been run;
it is an estimated 5,400 to 6,900 input and 200 to 400 output tokens, about two
cents. Both are priced at list prices checked on 2026-09-29. Killing the Worker
adds no model calls, because the new Worker replays the recorded turns. The
README's
"Cost to run" has the full table, and [the cost methodology](COST.md) has a way
to measure a pass.

**Doesn't Event History grow forever?**

It grows with every turn, and it has limits: continue-as-new is suggested at 4
MiB or 4,096 events, and a Workflow is terminated past 50 MB or 51,200 events.
This loop stays under 7 KB of payloads. Longer agents keep large records in a
memory store and pass keys (a claim check), and roll over with continue-as-new.
See the README's "When Event History grows".
