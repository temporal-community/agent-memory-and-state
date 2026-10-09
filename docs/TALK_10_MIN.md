# Talk run of show

Back to the [README](../README.md#where-to-go-next).

Presenter notes for the talk and the video.

- **Length:** the run of show ends at 12:30. The cuts in
  [If time slips](#if-time-slips) bring it to about 10 minutes.
- **Slides:** they carry the quick hits.
- **These notes:** what to show and what to land at each beat.
- **Quoted lines:** say them as written.

## North star

> An agent can know exactly what to do and still lose the work a customer
> submitted.

The audience leaves with three ideas:

1. Context, long-term memory, and state all inform an agent, but they do
   different jobs. Context comes first, because it's what the model reasons on.
2. Working memory lives inside the process and disappears with it, and Stripe
   only knows what reached Stripe. Neither can tell a new process where the
   work stood.
3. Temporal records where the work stands in Event History, so a new Worker
   can rebuild the completed steps and the next action. Every refund attempt
   sends the same idempotency key, built from the Workflow ID and Run ID, so
   Stripe makes one refund.

## Before you start

- **Set up:** run `make setup`, then [rehearse](#rehearse).
- **Pick the command:**

  | Take | Command | Needs |
  | --- | --- | --- |
  | Offline, no keys | `make run` | uv and the Temporal CLI |
  | Stripe test mode | `uv run refund-demo stage --real` | A Stripe `sk_test_` or `rk_test_` key |
  | Live model and Stripe test mode (what the video ran) | `uv run refund-demo stage --real --real-model --model-provider openai` (or `anthropic`) | The model keys in [Keys and live paths](../README.md#keys-and-live-paths) |

- **Safer on stage:** `--real` with the fixed policy. The talk's point doesn't
  depend on what the model decides, so pick this when steady timing matters
  more than showing a live model turn.
- **Fallback:** keep `--real` ready in case the live model fails.
- **Dev server:** run `temporal server start-dev` in another terminal first
  ([details](GUIDE.md#start-your-own-dev-server)).
  - It removes server startup between demos.
  - It keeps the Web UI up after the stage exits.
- **Stripe Dashboard:** with `--real`, keep it ready in test mode.
- **URL bar:** hide it. It shows your account ID.
- **Terminal:** fullscreen at 100-120 columns. Check that both panes fit.
- **Notifications:** off.
- **Flags, Web UI checks, and errors:** [GUIDE.md](GUIDE.md).

## Run of show

### 0:00-0:20 Hook

**Show:** the title slide or the stage's first frame.

**Land:**

- An agent helping a customer loses track of a refund, so the customer starts
  over and answers every question again.
- "In the next few minutes, you'll learn how to prevent that."

**Avoid:** a self-intro, and "this never happens again."

### 0:20-2:00 Demo 1: a standard refund agent

**Show:**

1. Enter at `Press Enter to start Demo 1 (without Temporal)`.
2. At `Ask for a refund` / `you>`, ask to refund the python plushy, or press
   Enter on an empty line to send the default, `Please refund order 1234.`
3. Enter through the two prefilled answers:
   - `Was the package opened? [Yes]`
   - `What was damaged? [Split seam]`
4. The lookups land with `(memory)` tags, then `→ Next: issue refund`. The
   bottom panel says `Next step: submit the refund.`
5. Enter at `Press Enter to submit the refund`.
   - `PROCESS GONE` appears with "The demo stops the process here, before the
     refund reaches Stripe."
   - Hold it for 3 seconds.
   - `WHAT'S LEFT` is Stripe's record: paid, no refund.
6. Enter at `Press Enter to start a new agent process`.
7. Enter at `Ask the new process: What happened to my refund?`.
8. The agent checks Stripe and says to start the return again under
   `THE CUSTOMER STARTS OVER`.

**Land:**

- The agent is a loop: ask, look things up, choose the next step.
- The process stops before the refund reaches Stripe, and the answers and next
  step go with it.
- Stripe is right: paid, no refund.
- But Stripe never had the answers or the next step, so the customer starts
  over.
- The dim line under the title says what this run uses, so no one mistakes a
  stand-in for the real thing. In a default run it reads
  `Scripted steps · offline ledger (no Stripe)`.
  - With `--real`, the second part reads `Stripe test mode`.
  - With `--real-model`, it starts with `Live model` and the provider instead
    of `Scripted steps`.

**Avoid:** "kill the process" and "lost connection."

- The cue says "submit."
- The screen says the demo stopped the process.

**Then:** leave the terminal at `Press Enter for Demo 2: the same test with Temporal`
while you present the slides.

### 2:00-7:00 Slides: memory and state, then Temporal

**Show:** the deck from "What just happened" through the Temporal slides.
Talk from the quick hits on each slide.

**Land:**

- A memory store could bring back the answers, but not whether the refund went
  out or which step runs next.
- Three words, in this order:
  - **Context:** what the agent has in front of it for this decision. The
    model reasons only on what's in context, so what goes in shapes every
    choice.
  - **Long-term memory:** what the agent carries from run to run. It lives in
    a store you own.
  - **State:** the facts the model doesn't own. Here it splits in two:
    - **Execution state:** where the work stands. Temporal records it in
      Event History.
    - **Effect state:** whether the refund happened. Stripe owns that.
- Facts have owners. When memory and the record disagree, the record wins.
- Workflow code runs in the Worker.
- The Temporal Service records each step in Event History.
- "Replay, not redo." A new Worker runs the Workflow code again from the top,
  and each finished Activity returns its recorded result instead of running
  again.

**Avoid:** "Temporal tracks the refund's state."

- Stripe owns whether the refund happened.
- Temporal owns where the work stands.

**Detail:** [Context, memory, and state](../README.md#memory-and-execution-state),
[Architecture](../README.md#architecture).

### 7:00-9:00 Demo 2: the same test with Temporal

**Show:**

1. Enter at `Press Enter for Demo 2: the same test with Temporal`.
2. At `Ask for a refund (order 1234, the python plushy)`, ask again. The
   spinner says it is reusing your Demo 1 answers.
3. The right pane, `Saved so far:`, shows:
   - 2 customer answers
   - 2 completed lookups
   - `Next action: issue refund`
   - `(demo pauses here, before Stripe)`
4. Enter at `Press Enter to submit the refund`.
   - `WORKER GONE` appears with "The demo stops the Worker here, before the
     refund reaches Stripe."
   - The right pane says `Read from Temporal just now:`. It can take up to 3
     seconds to appear.
   - Hold it for 3 seconds.
5. Enter at `Press Enter to start a new Worker`.
   - `NEW TEMPORAL WORKER` shows `NO REPEATED QUESTIONS`, `NO LOOP RESTART`,
     and "Your refund is complete."
   - The right pane shows `Refund: SUCCEEDED`.
6. Optional:
   - the Workflow in the Web UI
   - with `--real`, the one refund in the Stripe Dashboard

**Land:**

- It's the same loop, stopped at the same point. This time the Temporal
  Service records each step in Event History, outside the Worker.
- That's why `Read from Temporal just now:` can show the answers, lookups, and
  next action while no Worker is running.
- "The Worker stops before the refund reaches Stripe."
- "The Worker is disposable; the loop is not."
- In the Web UI the Workflow is still Running. Its next task waits for a
  Worker.
- The new Worker replays Event History and continues at `issue refund`.
- It asks nothing again and doesn't resend finished model calls.
- Every retry sends the same idempotency key, so Stripe makes one refund.
- Temporal owns the attempt; Stripe owns the outcome.
- The agent says "Your refund is complete" only after Stripe returns
  `succeeded`.

**Avoid:** "lost connection," "exactly once," and calling the Workflow
"paused."

- The Workflow stays Running.
- The on-screen `(demo pauses here, before Stripe)` is the Workflow waiting for
  the demo's `release` Signal before the refund.

**If the right pane says `Could not re-read Temporal.`:**

- The counts on screen are from before the Worker stopped. Say so.
- Then show Event History in the Web UI.

### 9:00-10:15 History growth, claim check, Continue-As-New

**Show:** the gotcha slides.

**Land:**

- **Why history grows:** each turn sends all of working memory to the model
  step again, and Event History records every send. A long agent run builds a
  big history.
- **This demo:** allows at most 10 turns and stays under 7 KB of payloads.
- **Claim check:** keep a big result in your store and only a small key in
  Event History.
- **Continue-As-New:** "Temporal suggests it (about 4 MiB); your code calls it."
  The Workflow keeps its Workflow ID and gets a new Run ID and a fresh Event
  History.
- **Here:** roll over only before the refund. The refund's idempotency key
  includes the Run ID, so a refund retried in a new run would send a new key,
  and Stripe couldn't tell it was a retry.

**Avoid:** making Continue-As-New sound automatic, or saying the Workflow
"keeps track of" its history.

**Detail:** [Gotchas](../README.md#gotchas), [HISTORY_GROWTH.md](HISTORY_GROWTH.md).

### 10:15-10:45 The trade-off

**Show:** the trade-off slide.

**Land:**

- Not every agent needs this. It earns its place when work:
  - outlives a process or a deploy
  - waits on people or systems
  - retries real side effects
- **What it costs:**
  - Event History holds customer data.
  - Someone runs the service or pays for Temporal Cloud.
- **What it won't do:** make the model's choice right. Evals and guardrails do.

**Detail:** [How other approaches compare](../README.md#how-other-approaches-compare),
[What it is not](../README.md#what-it-is-not).

### 10:45-11:30 Cost

**Show:** the cost slide.

**Land:**

- **Lead with why:** starting over repeats every model call and pays for each
  one again. Replay returns recorded results, so it doesn't pay again for
  finished calls. Only a call in flight at the crash can run twice.
- **Say the date and model:** "Measured October 2, on GPT-5.6 Luna."
- **Demo 1:** one pass made 4 model calls, 2,962 tokens, $0.0009. Starting
  over made 4 more calls, 2,972 tokens, and $0.0009 more.
- **Demo 2:** the pass before the kill made 4 model calls, 2,946 tokens,
  $0.0009. Replay after the kill added 0 model calls, so no more tokens or
  dollars.
- **At scale:** 1M requests a month comes to about 3B tokens and about $900.
  Say it's an estimate, and give its basis: the measured Demo 1 pass size,
  model calls only, at GPT-5.6 Luna list prices as of 2026-09-29.
- **Default `make run`:** makes no model calls, because a fixed policy stands
  in for the model.

**Avoid:** "as of today," "lower cost per agent loop," and leading with $0.

**Detail:** [Cost to run](../README.md#cost-to-run).

### 11:30-12:00 The distinction

**Show:** the distinction slide, or the stage's closing frame
(`Press Enter for the takeaway`).

**Land:**

- **For reasoning:** context and memory.
- **For the operation:** execution state, which Temporal records in Event
  History, and effect state, which Stripe owns.
- "Memory helps reasoning continue. Temporal helps the operation continue."
- Stripe, not either of them, knows whether money moved.
- "Do not ask agent memory to serve as proof of an external effect."
- "Give the work a durable execution owner, and carry one identity across the
  systems that must recover it."

**Detail:** [Demo takeaways](../README.md#demo-takeaways).

### 12:00-12:30 Run it yourself

**Show:** the run-it slide.

**Land:**

- **No keys:** `make setup && make run` runs both demos offline.
- **Name what this take ran:** the video used a live model and Stripe test
  keys. `make run` needs neither.
- **Local Temporal:** `temporal server start-dev` gives you a local Temporal
  Service and Web UI.
- **For your coding agent:** the Temporal developer skill.

**Detail:** [Run it](../README.md#run-it), [Where to go next](../README.md#where-to-go-next).

## Stage cues

| Prompt | What appears | Target |
| --- | --- | --- |
| `Press Enter to start Demo 1 (without Temporal)` | Empty `AGENT PROCESS` | 0:20 |
| `you>` + Enter through 2 answers | `(memory)` lookups<br>`→ Next: issue refund`<br>`Next step: submit the refund.` | 1:00 |
| `Press Enter to submit the refund` | `PROCESS GONE`, `WHAT'S LEFT` | 1:15 |
| `Press Enter to start a new agent process` | `NEW AGENT PROCESS`: "No answers. No next step." | 1:25 |
| `Ask the new process: What happened to my refund?` | `THE CUSTOMER STARTS OVER` | 2:00 |
| `Press Enter for Demo 2: the same test with Temporal` | Empty `TEMPORAL WORKER` | 7:00 |
| `Ask for a refund (order 1234, the python plushy)` | `Saved so far:`, `Next action: issue refund` | 7:45 |
| `Press Enter to submit the refund` | `WORKER GONE`, `Read from Temporal just now:` | 8:00 |
| `Press Enter to start a new Worker` | `NO REPEATED QUESTIONS`<br>`NO LOOP RESTART`<br>`Refund: SUCCEEDED` | 9:00 |
| `Press Enter for the takeaway` | Closing frame | 11:30 |

**With a live model:**

- Ask about order 1234 or the python plushy.
- Another item can be denied, and a denial in Demo 1 ends the stage.

## If time slips

- **Demo 1:** press Enter for the default request and question.
- **Slides:** skip agency levels, memory kinds, and the vocabulary slide.
- **History growth:** one line ("history grows; claim check and
  Continue-As-New keep it bounded"), then point at [Gotchas](../README.md#gotchas).
- **Trade-off:** one sentence.
- **Never cut:**
  - `THE CUSTOMER STARTS OVER`
  - `NO REPEATED QUESTIONS`
  - `NO LOOP RESTART`
  - "Your refund is complete."
  - the cost difference: starting over pays again, and replay doesn't
  - the distinction

## Other stage paths

Both are optional endings, not the main payoff. Both run offline; add `--real`
for Stripe test mode. Details: [GUIDE.md](GUIDE.md).

**Retry in flight:** `make failure`, which runs
`uv run refund-demo stage --simulate-stripe-timeout`.

1. The Worker is stopped while `issue_refund` waits on a simulated Stripe
   timeout, before any refund is accepted.
2. A new Worker runs attempt 2 with the same idempotency key. Only then does
   the refund reach Stripe.

**Crash after Stripe accepts the refund:**
`uv run refund-demo stage --simulate-stripe-retry`.

1. Stripe accepts attempt 1.
2. The Worker stops before Temporal records the result.
3. The new Worker's retry sends the same idempotency key, so the two calls
   resolve to one refund: `2 CALLS → 1 REFUND`.

## Rehearse

1. **Words only:** walk the frames offline, without a timer.
2. **Timed offline:** one complete `make run`. Aim 30 seconds under your slot,
   so applause, latency, and transitions fit.
3. **Recovery drill:** keep going after a slow model, a slow Worker restart, an
   extra Enter, or lost terminal focus.
4. **Dress rehearsal:** the venue laptop, resolution, font size, network, and
   the command you'll run live.
5. **Final run:** practice the opening and the close until you can say both
   without looking at the screen.

| Take | Mode | Total | Starts over by 2:00 | Resumes at `issue refund` | Owners named | No "exactly once" | Close from memory | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |

## Likely questions

**Why not check Stripe before refunding?**

- The new agent process does.
- Stripe says paid with no refund, but it never had the answers or the next
  step.
- A separate read and write can race, so the idempotency key still matters.
- More: [Context, memory, and state](../README.md#memory-and-execution-state).

**Could Stripe handle the retry without Temporal?**

- **Stripe:** makes a repeated call safe when you send the same idempotency
  key. But Stripe can't start a retry on its own; something has to know the
  call is still owed.
- **Temporal:** Event History records that the refund step hasn't finished,
  even after the Worker disappears.
- **Temporal also:** schedules the retry for the next Worker, and records the
  result for the application to read.

**Couldn't I build this with a database and a queue?**

- Yes, and then you're building durable execution yourself. You'd need:
  - a state machine
  - retries
  - a stable idempotency key
  - reconciliation with Stripe
- A single "done" flag isn't enough. If the process dies after Stripe accepts
  the refund but before the flag is written, nothing on your side knows the
  refund went out.
- More: [How other approaches compare](../README.md#how-other-approaches-compare).

**Is Temporal the agent's memory?**

- No. It records execution state in Event History, which lives in the
  Temporal Service, not the Worker.
- Long-term memory is a store you own.
- Agent memory and Workflow state can inform one another, but they have
  different ownership and recovery contracts.
- More: [Context, memory, and state](../README.md#memory-and-execution-state).

**What does the code look like?**

Show only the boundary, this condensed excerpt from
`src/refund_agent/workflow.py`:

```python
result = await workflow.execute_activity(
    issue_refund,
    args=[request, decision, self.working_memory],
    heartbeat_timeout=heartbeat_timeout,
    retry_policy=RetryPolicy(...),
)
```

- The agent loop is ordinary Python.
- Customer answers arrive as durable Signals.
- The lookups and the refund run as Activities, so Temporal records each
  result and where the loop stands.
- Inside the refund Activity, the idempotency key is built from the Workflow ID
  and Run ID.

**Unless asked, don't explain:**

- the full agent loop
- the history replay algorithm
- the retry policy
- SDK syntax

**Is the refund exactly once?**

- No. A step can run more than once.
- The shared idempotency key makes those calls one refund.
- More: [Gotchas](../README.md#gotchas).
