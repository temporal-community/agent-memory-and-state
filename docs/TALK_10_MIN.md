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

1. Context, memory, and state can all inform an agent.
2. Working memory inside a process can disappear, and Stripe only knows what
   reached Stripe. Neither gives a new process the loop's position.
3. Temporal lets a new Worker rebuild the loop's completed steps and next
   action, and the Workflow run's identity ties later retries to one refund in
   Stripe.

## Before you start

- **Set up:** run `make setup`, then [rehearse](#rehearse).
- **Pick the command:**

  | Take | Command | Needs |
  | --- | --- | --- |
  | Offline, no keys | `make run` | uv and the Temporal CLI |
  | Stripe test mode | `uv run refund-demo stage --real` | A Stripe `sk_test_` or `rk_test_` key |
  | Live model and Stripe test mode (what the video ran) | `uv run refund-demo stage --real --real-model --model-provider openai` (or `anthropic`) | The model keys in [Keys and live paths](../README.md#keys-and-live-paths) |

- **Safer on stage:** `--real` with the fixed policy. The model's output isn't
  the claim, so pick it when timing matters more than a live reasoning turn.
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
2. At `you>`, ask to refund the python plushy. Enter sends
   `Please refund order 1234.`
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
- The dim header line says what is scripted:
  - fixed policy or live model
  - offline ledger or Stripe test mode

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
- Three words, three meanings:
  - **Context:** what the agent sees now.
  - **Memory:** what it remembers or looks up.
  - **State:** the facts the model doesn't own.
- Facts have owners. When memory and the record disagree, the record wins.
- Workflow code runs in the Worker.
- The Temporal Service records each step in Event History.
- A new Worker replays Event History: replay, not redo.

**Avoid:** "Temporal tracks the refund's state."

- Stripe owns whether the refund happened.
- Temporal owns where the work stands.

**Detail:** [Memory and execution state](../README.md#memory-and-execution-state),
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

- Same loop, same stopping point. This time each step is recorded outside the
  Worker.
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

**Avoid:** "lost connection," "paused," and "exactly once."

**If the right pane says `Could not re-read Temporal.`:**

- The counts are the earlier reading. Say so.
- Show Event History in the Web UI.

### 9:00-10:15 History growth, claim check, Continue-As-New

**Show:** the gotcha slides.

**Land:**

- **Why history grows:** Temporal records Event History, and each turn resends
  working memory. A long agent run builds a big history.
- **This demo:** stays under 7 KB of payloads.
- **Claim check:** keep a big result in your store and a small key in Event
  History.
- **Continue-As-New:** "Temporal suggests it (about 4 MiB); your code calls it."
  - Same Workflow ID
  - New Run ID
  - Fresh Event History
- **Here:** roll over only before the refund. Its idempotency key uses the Run
  ID.

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

- **Say:** "Measured Oct 2" on GPT-5.6 Luna.
- **A full take (both demos):** 8 model calls, 5,908 tokens, $0.0019.
- **Starting over pays again:** Demo 1's start-over cost 4 more calls, 2,972
  tokens, $0.0009.
- **Replay doesn't:** the new Worker in Demo 2 added 0 model calls.
- **After a crash:** finished model calls aren't paid twice. Only a call in
  flight can be.
- **Default `make run`:** no model calls. It uses a fixed policy.
- **1M requests a month:** about 3B tokens, about $900. That's an estimate, so
  say so.

**Avoid:** "as of today," "lower cost per agent loop," and leading with $0.

**Detail:** [Cost to run](../README.md#cost-to-run).

### 11:30-12:00 The distinction

**Show:** the distinction slide, or the stage's closing frame
(`Press Enter for the takeaway`).

**Land:**

- **For reasoning:** context and memory.
- **For the operation:** execution state, held by Temporal, and effect state,
  held by Stripe.
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
  - the cost line
  - the distinction

## Other stage paths

Both are optional endings, not the main payoff. Details: [GUIDE.md](GUIDE.md).

**Retry in flight:** `make failure`, which runs `--simulate-stripe-timeout`.

1. The Worker is stopped while `issue_refund` waits on a simulated Stripe
   timeout.
2. A new Worker runs attempt 2.

**Crash after Stripe commits:** `--simulate-stripe-retry`.

1. Stripe accepts attempt 1.
2. The Worker stops before reporting it.
3. The new Worker's retry sends the same idempotency key: `2 CALLS → 1 REFUND`.

## Rehearse

1. **Words only:** walk the frames offline, without a timer.
2. **Timed offline:** one complete `make run`. Aim 30 seconds under your slot,
   so applause, latency, and transitions fit.
3. **Recovery drill:** keep going after a slow model, a slow Worker restart, an
   extra Enter, or lost terminal focus.
4. **Dress rehearsal:** the venue laptop, resolution, font size, network, and
   the command you'll run live.
5. **Final run:** the opening and the close until neither depends on the
   screen.

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
- More: [Memory and execution state](../README.md#memory-and-execution-state).

**Could Stripe handle the retry without Temporal?**

- **Stripe:** makes a repeated call safe when you send the same idempotency
  key.
- **Temporal:** after the Worker disappears, it remembers that the step still
  needs resolving.
- **Temporal also:** schedules the retry, and keeps the result for the
  application to read.

**Couldn't I build this with a database and a queue?**

- Yes. You'd build:
  - a state machine
  - retries
  - a stable key
  - reconciliation
- That is building durable execution.
- A lone done flag written after Stripe still has a failure gap. A full state
  machine is durable execution.
- More: [How other approaches compare](../README.md#how-other-approaches-compare).

**Is Temporal the agent's memory?**

- No. It holds execution state.
- Long-term memory is a store you own.
- Agent memory and Workflow state can inform one another, but they have
  different ownership and recovery contracts.
- More: [Memory and execution state](../README.md#memory-and-execution-state).

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
- Lookups and the irreversible operation cross Activity boundaries.
- Temporal records the observations and where the loop stands.
- Inside the refund Activity, the Workflow run's identity becomes the effect's
  idempotency key.

**Unless asked, don't explain:**

- the full agent loop
- the history replay algorithm
- the retry policy
- SDK syntax

**Is the refund exactly once?**

- No. A step can run more than once.
- The shared idempotency key makes those calls one refund.
- More: [Gotchas](../README.md#gotchas).
