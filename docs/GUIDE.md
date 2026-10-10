# Run and present the demo

Back to the [README](../README.md).

This guide picks up where the README's quick start ends. It walks through what
the demo does at each step, how to watch the same run in the Temporal Web UI,
how to run each piece by hand, and how to fix what goes wrong.

The demo turns on one distinction. Memory helps the agent reason, but it
doesn't record where the work stands. Temporal records that execution state in
Event History, which lives in the Temporal Service rather than in the Worker,
so a new Worker can pick the work back up. Stripe, or the offline ledger that
stands in for it, is the only record of whether the refund happened.

If you're presenting the demo, the timed notes for a 10-minute talk are in
[TALK_10_MIN.md](TALK_10_MIN.md).

**Contents:**

- [Run the stage](#run-the-stage)
- [Expected output](#expected-output)
- [Watch it in the Temporal Web UI](#watch-it-in-the-temporal-web-ui)
- [Manual walkthrough](#manual-walkthrough)
- [Authorization companion demo](#authorization-companion-demo)
- [Troubleshooting](#troubleshooting)

## Run the stage

`refund-demo stage` runs both demos in one terminal, and this guide calls it
the stage.

```bash
uv run refund-demo stage      # or: make run
```

Press Enter at each prompt to move to the next step. By default, the stage
uses a deterministic policy in place of a model and an offline Stripe-like
ledger in place of Stripe. If it can't reach a Temporal server, it starts a
local dev server. When it exits, it shuts down only the processes it started.

**Cost.** Starting over pays for every model call again. Replay doesn't pay
again for calls that already finished, so only a call that was in flight at
the crash can run twice. These numbers were measured with `--real-model` on
GPT-5.6 Luna on 2026-10-02:

- A Demo 1 pass makes 4 model calls: 2,962 tokens, $0.0009. If the customer
  starts over, as Demo 1 tells them to, the redo makes 4 more calls: 2,972
  tokens, $0.0009 more.
- A Demo 2 pass makes 4 model calls before the kill: 2,946 tokens, $0.0009.
  Replay after the kill makes 0 calls (0 tokens, $0).
- Without `--real-model`, every stage run uses the fixed policy and makes no
  model calls (0 tokens, $0).

The README's [Cost to run](../README.md#cost-to-run) has the token breakdown,
the Claude estimates, and an estimate for 1M requests a month.

### What the runner does

1. The stage welcomes Nyghtowl back and shows the last python-plushy order as
   `PAID`.
2. **Demo 1.** You ask for a refund, and the agent process works through the
   loop in its own memory:
   - It asks the two intake questions. Press Enter to accept each suggested
     answer.
   - It runs the lookups its policy or model picks, which is two on the
     default path.
   - It chooses `issue refund`, calling the same decision step that Demo 2
     uses, but in process.
3. The stage kills the agent process after it chooses `issue refund` but
   before any refund call, and holds on a visible `PROCESS GONE` frame.
4. The stage starts a new agent process (`NEW AGENT PROCESS`) and sends it the
   customer's status question across that process boundary.
   - The new process checks Stripe, or the offline ledger, for the payment.
     With `--real`, it retrieves the PaymentIntent and its refund list directly
     from Stripe, without submitting a refund.
   - It has no answers and no next step, so the customer starts the return
     again (`THE CUSTOMER STARTS OVER`).
5. **Demo 2.** The stage starts the Workflow and replays your Demo 1 answers
   into it as `customer_answer` Signals, and the screen says "Reusing your
   Demo 1 answers so you don't type them twice..."
   - The lookups run as Activities. Each one has a plain-words summary in
     Event History, such as `Look up order 1234`.
6. The stage kills the Worker at the same next action.
   - The `WORKER GONE` frame reads Event History from Temporal, which needs no
     Worker.
   - Under `Read from Temporal just now:`, it shows two customer answers, the
     completed lookups, and `Next action: issue refund`. There are two
     completed lookups by default, and three when a live model also checks the
     refund policy.
7. The stage starts a new Worker and sends the demo-only `release` Signal, and
   the refund goes through. The Workflow waits for that Signal right before
   `issue_refund`, and the stage stops the Worker during that pause, so the
   crash lands at the same point on every run. A real app has no pause: its
   Worker can stop at any step, and Temporal recovers the same way. The README
   lists [what's written for the demo](../README.md#whats-written-for-the-demo).
   - The `NEW TEMPORAL WORKER` resumes at `issue refund` without repeating
     questions, issues the refund, and reports completion.

**The kill is real.** The failure the demo shows is a Worker that dies in the
middle of the agent loop. The default run sends the Worker a real SIGKILL one
step before the refund.

- Before the kill, Demo 2's agent loop shows `→ Next: issue refund`, the stage
  waits for you to press Enter, and the Worker is still alive.
- After the kill (`WORKER GONE`), the Workflow is still `Running`, even though
  no Worker is alive.

That is expected. The Temporal Service, here the dev server, keeps the
Workflow's Event History, and a Worker only polls the Task Queue for the next
step to run. So the Workflow waits until a new Worker arrives. To see this for
yourself, [watch it in the Temporal Web UI](#watch-it-in-the-temporal-web-ui).

**What the screens say.**

- Demo 1's side is called the agent process (`PROCESS GONE`,
  `NEW AGENT PROCESS`), because it is not a Temporal Worker. The word "Worker"
  is used only for Demo 2 (`WORKER GONE`, `NEW TEMPORAL WORKER`).
- Every input prompt says what Enter does next, such as
  `Press Enter to submit the refund`.
- Each demo's header has a dim line that names what is scripted and what is
  live:
  - Demo 1, by default: `Scripted steps · offline ledger (no Stripe)`
  - Demo 2, by default:
    `Fixed policy (no LLM) · sample lookups · offline ledger (no Stripe)`
  - Both, with `--real-model`: `Live model (openai) · sample lookups · …` (or
    `anthropic`)
- The ledger pane is headed `OFFLINE LEDGER (Stripe stand-in)` by default and
  `STRIPE (test mode)` with `--real`.

### Two owners

In Demo 2, two systems each own a different fact. Temporal records each
Activity attempt and where the work stands, which gives a new Worker its
recovery point. Stripe, or the offline ledger, records whether the refund
happened, but it holds neither the customer's answers nor where the loop
stood. The README's [Facts have owners](../README.md#memory-and-execution-state)
explains the general rule.

What this demo adds is the shared idempotency key. Every `issue_refund`
attempt in a run sends the same key, so a retry after a crash gets its answer
from Stripe, not from memory. The
[later-loss walkthrough](#later-loss-after-stripe-accepts-the-refund) shows
that case.

### Live models

```bash
uv run refund-demo stage --real-model --model-provider openai   # or anthropic
```

**Setup.**

- OpenAI mode needs `OPENAI_API_KEY` and `OPENAI_MODEL`, and Claude mode needs
  `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. Put local values in `.env`;
  exported shell variables take precedence.
- `AGENT_MODEL_PROVIDER` can replace `--model-provider`. If only one model key
  is set, the stage infers the provider. If both are set and no provider is
  chosen, the stage stops and asks you to choose one.
- Run a live model against the offline ledger first, before you combine it
  with `--real`.
- The order is fixed: order 1234, an $80 python plushy. Its policy record says
  explicitly that this low-value damaged item needs no physical return. Refer
  to order 1234 or the python plushy in your request, because a live model can
  correctly deny a request for a different item.

**How it behaves.**

- Both demos call the live model through the same decision step.
- Demo 1 has no retry layer. Its agent process calls the decision step
  directly, so one failed model call, such as an API error, ends Demo 1, and
  the stage stops with the reason.
- Demo 2 calls the decision step from the `agent_decide_next_step` Activity,
  so Temporal retries a failed call and Event History records each finished
  turn. After the kill, replay returns those recorded results instead of
  calling the model again.
- If the model escalates instead of approving, the stage sends Demo 2's
  approval Signal itself, with the note `approved by the guided stage runner`.
  Demo 1 has no Signal to wait on, so it treats an escalation as approved.
- If the model denies in Demo 1, the stage stops before Demo 2, because there
  is no refund to interrupt. If it denies in Demo 2, the screen shows the
  model's rationale and that no refund was issued, instead of exiting on an
  empty screen.
- If `--real` created a Stripe test payment before a denial,
  [clean it up](#stripe-test-mode-and-cleanup).
- Both providers see the order amount in dollars, as `"$80.00"`, so the
  rationale reads like `Approve the $80.00 refund for order-1234…`. The stored
  request and working memory still keep cents (`amount_cents`).

The on-screen differences and messages are in
[With a live model](#with-a-live-model).

### Stripe test mode and cleanup

```bash
uv run refund-demo stage --real   # or: make run-real
```

`--real` needs a Stripe `sk_test_` or `rk_test_` key in `STRIPE_API_KEY`, and
it rejects live keys. It creates Stripe test objects:

- Before the first refund prompt, the runner creates and confirms Nyghtowl's
  Stripe test PaymentIntent, so `PAID` is a real record.
- Demo 1's new agent process reads that PaymentIntent and its refunds from
  Stripe, and confirms that no refund reached Stripe.
- Only Demo 2 refunds the test payment.

If a run ends before the refund, reconcile it:

```bash
uv run refund-demo cleanup
```

Cleanup refunds only the outstanding test payments this demo created. It
doesn't delete Stripe test objects or make the Dashboard's row counts match,
because Stripe keeps both the payment and the refund records. If it reports
`refunded $0.00`, it found no outstanding demo payment.

### Which lines read Stripe

Not every Stripe line on screen is a live Stripe read.

- `Payment: PAID` is a fixed label in Demo 2's pane, and in Demo 1's pane
  before the kill.
- Demo 2's refund line reads a local mirror of Stripe's response.
- Only Demo 1's new agent process reads Stripe directly, in its status check,
  and only with `--real`. Offline, that check reads its own ledger, and the
  pane is headed `OFFLINE LEDGER (Stripe stand-in)`.
- Offline runs still say "Stripe" in the agent's lines, the Worker log, and
  the `issue_refund` summary in Event History, because "Stripe" is the story's
  name for the system that owns the refund.

### Simulated failures

Two flags move the kill into the refund call itself, so you can show what a
retry does. Both run offline unless you add `--real`, which uses Stripe test
mode. You can use only one of them per run.

**Stripe timeout, the recommended retry demo.** The Worker is killed while the
refund Activity is in flight instead of before it:

```bash
uv run refund-demo stage --simulate-stripe-timeout   # or: make failure
```

1. Attempt 1 enters `issue_refund`, but the simulated Stripe API does not
   respond.
2. The Worker is killed before any refund is accepted.
3. Temporal advances the Activity to attempt 2 and waits until you start a new
   Worker.
4. The new Worker runs attempt 2 with the same idempotency key and calls
   Stripe normally. Only then does the refund reach Stripe.

This path has no pause before the refund, so it sends no `release` Signal.
Use it when the story is "the API was down."

**Later loss, `--simulate-stripe-retry`.**

1. Stripe accepts attempt 1.
2. The Worker disappears before Temporal records the result.
3. Attempt 2 reuses the same idempotency key, so two calls resolve to one
   refund.

This is the technical walkthrough of idempotency, not the main story. See
[Later loss](#later-loss-after-stripe-accepts-the-refund).

### Reset between runs

<a id="reset-between-takes"></a>Default runs need no reset. Every stage run
gets a fresh token, so it gets a new Workflow ID (unless you pass
`--workflow-id`), a private Task Queue named `refund-stage-<token>`, and its
own state directory, `.demo-state/stage-<token>/`.

If you pass `--workflow-id`, use a new one for every run. Reusing one while an
earlier run is still Running fails with `WorkflowAlreadyStartedError`.

| After | Run |
| --- | --- |
| A `--real` run that ended before Demo 2's refund | `uv run refund-demo cleanup` ([what it does](#stripe-test-mode-and-cleanup)) |
| An aborted run that left a Running Workflow | `uv run refund-demo stop <workflow-id>` |
| The stage process was killed hard | 1. `pgrep -fl refund_agent` lists stray stage processes.<br>2. Check each command line: `python -m refund_agent.worker` or `python -m refund_agent.naive_refund`.<br>3. Stop only those. |
| You want an empty Workflow list in the Web UI | Press Ctrl+C on your own in-memory `temporal server start-dev`, then start it again.<br>Never do this to a server someone else is using. |
| You want to clear local files | Stop any dev server that uses `.demo-state/temporal.db`, then run `rm -rf .demo-state`.<br>This removes stage logs, token logs (`model-usage.jsonl`), offline ledgers, and the stage-started server's database. |

## Expected output

### Stage transcript

This is a default run of
`uv run refund-demo stage --workflow-id nyghtowl-take-01`, pressing Enter at
every prompt. For a quick check, look for these lines, in order.

**Demo 1:**

1. `→ Next: issue refund`
2. `PROCESS GONE`
3. `No refund request reached Stripe.`
4. `Please start the return again.`

**Demo 2:**

1. `WORKER GONE`
2. `Read from Temporal just now:` with `Next action: issue refund`
3. `NO REPEATED QUESTIONS`
4. `NO LOOP RESTART`
5. `Your refund is complete.`

The full run is below, condensed, with the box drawing removed. Pane titles
are in capitals.

```text
Agent memory and state
  An agent can know exactly what to do and still lose the work a customer submitted.
  We'll stop the agent right before it calls Stripe: first without Temporal, then with it.
An agent works with different kinds of information
  This demo explains three of them:
  CONTEXT           what the agent can see right now
  LONG-TERM MEMORY  what the agent remembers or looks up
  STATE             the official records; this demo shows two types:
    execution       what's done and what's next (Temporal)
    effect          whether the refund really happened (the payment record)
Press Enter to start Demo 1 (without Temporal)

Demo 1: Without Temporal, the agent loses its place
  Its answers and next step live only inside this agent process.
  Scripted steps · offline ledger (no Stripe)
  AGENT PROCESS  Welcome back, Nyghtowl
  WHAT SURVIVES  LAST ORDER  Python plushy · $80.00
                 OFFLINE LEDGER (Stripe stand-in)  Payment: PAID  Refund: none
  THE QUESTION   What if this agent process disappears right before the refund?
Ask for a refund
you>                        (Enter alone sends "Please refund order 1234.")
agent> Was the package opened? [Yes]
agent> What was damaged? [Split seam]
  AGENT LOOP
    ✓ Package opened: Yes
    ✓ Damage: Split seam
    ✓ Order: python plushy (memory)
    ✓ Refund history: clean (memory)
    → Next: issue refund
  WORK NOT SAVED
    Next step: submit the refund.
    The answers and next step exist only inside this process.
Press Enter to submit the refund

  AGENT PROCESS  PROCESS GONE
                 It held the answers and next step.
                 They are gone with it.
                 The demo stops the process here,
                 before the refund reaches Stripe.
  WHAT'S LEFT    Only Stripe's record: PAID, no refund.
                 That is correct. Stripe was never called.
Press Enter to start a new agent process

  NEW AGENT PROCESS  Welcome back, Nyghtowl
                     No answers. No next step.
  FRESH START        It can still read Stripe.
                     It cannot see the old answers.
Ask the new process: What happened to my refund?
you>                        (Enter alone sends "What happened to my refund?")
  AGENT  Let me check Stripe.
         No refund request reached Stripe.
         I lost your return answers.
         Please start the return again.
  THE CUSTOMER STARTS OVER
    Stripe's record is right: paid, no refund.
    But Stripe never had the answers or the next step.
Press Enter for Demo 2: the same test with Temporal

Demo 2: With Temporal, the agent keeps its place
  Temporal keeps each answer, lookup and next step outside the Worker.
  Fixed policy (no LLM) · sample lookups · offline ledger (no Stripe)
Ask for a refund (order 1234, the python plushy)
you>
Reusing your Demo 1 answers so you don't type them twice...
  TEMPORAL WORKER  AGENT LOOP
                     ✓ Package opened: Yes
                     ✓ Damage: Split seam
                     ✓ Order: python plushy (memory)
                     ✓ Refund history: clean (memory)
                     → Next: issue refund
  WHAT SURVIVES    TEMPORAL        Saved so far:
                                   Customer answers: 2
                                   Completed lookups: 2
                                   Next action: issue refund
                                   (demo pauses here, before Stripe)
                   OFFLINE LEDGER  Payment: PAID
                                   Refund: none
Press Enter to submit the refund

  TEMPORAL WORKER  WORKER GONE
                   Its in-memory loop is gone.
                   The demo stops the Worker here,
                   before the refund reaches Stripe.
                   Temporal still has the saved loop. →
  WHAT SURVIVES    TEMPORAL        Read from Temporal just now:
                                   Customer answers: 2
                                   Completed lookups: 2
                                   Next action: issue refund
                   OFFLINE LEDGER  Payment: PAID
                                   Refund: none
Press Enter to start a new Worker
Starting a new Worker. It picks up from Temporal's history...

  NEW TEMPORAL WORKER  NO REPEATED QUESTIONS
                       NO LOOP RESTART
                       Same loop, rebuilt from Temporal.
                       AGENT
                         Your refund is complete.
  WHAT SURVIVES        TEMPORAL        Finished by the new Worker.
                       OFFLINE LEDGER  Payment: PAID
                                       Refund: SUCCEEDED
Press Enter for the takeaway

The difference
  Without Temporal: the customer had to start over.
  With Temporal: a new Worker picked up at the saved next action.
Memory helps reasoning continue.
Temporal helps the operation continue.
Stripe knows whether money moved.
Stage logs: .demo-state/stage-<token>
```

- With `--real`, the ledger heading reads `STRIPE (test mode)`, and the header
  lines end in `Stripe test mode`.
- The `Stage logs:` path is relative to the directory you ran the stage from,
  so from there it works as `refund-demo usage --state-dir`.
- Demo 2's `WORKER GONE` frame can take up to 3 seconds to appear, because it
  reads Event History while it draws. If that read fails or runs out of time,
  the pane says `Could not re-read Temporal.` and
  `Showing the earlier reading:` instead of `Read from Temporal just now:`.

### With a live model

`stage --real-model --model-provider openai` (or `anthropic`) runs both demos
on the live model, through the same decision step. Compared with the default
transcript:

- Both demos' headers start with `Live model (openai)` or
  `Live model (anthropic)` instead of `Scripted steps` in Demo 1 and
  `Fixed policy (no LLM)` in Demo 2. Offline, a header reads, for example,
  `Live model (anthropic) · sample lookups · offline ledger (no Stripe)`. With
  `--real`, it reads `Live model (openai) · sample lookups · Stripe test mode`.
- While Demo 1 waits on the model, the screen shows
  `The agent is choosing its next step...`.
- The model picks the lookups. In the measured 2026-10-02 run, it also checked
  the refund policy in both demos, so each loop adds
  `✓ Refund policy: eligible (memory)` and Demo 2's pane shows
  `Completed lookups: 3`.
- The rationale speaks in dollars, because the model sees `"$80.00"`.
- The new Demo 1 process's reply is fixed text, not model output. It still
  says "No refund request reached Stripe. I lost your return answers. Please
  start the return again."
- If the model denies the Demo 1 request, the stage stops before Demo 2 with
  `STAGE | the model denied the Demo 1 refund; run the stage again`. A `--real`
  run adds a cleanup hint.
- If it denies in Demo 2, the screen shows the model's rationale and that no
  refund was issued, and the prompt is
  `The model denied this request. Press Enter to exit`.
- If Demo 1's process fails, for example on a missing key or an API error, the
  stage stops with `STAGE | the Demo 1 agent process failed: <reason>`.

### Worker log

The Worker log, `.demo-state/stage-<token>/worker.log`, shows the resume. This
excerpt is from an offline run, with the `MODEL REASONING`, `MEMORY COPY`,
`CONTEXT`, and `THE AGENT` lines and the separator line removed. In the default
mode, the `MODEL REASONING` lines come from the deterministic policy, not a
model.

```text
EXECUTION STATE | Worker connected to localhost:7233 on task queue refund-stage-<token>
EXECUTION STATE | phase=agent_loop_start
EXECUTION STATE | phase=waiting_for_answer id=item_opened
EXECUTION STATE | phase=observed answer=item_opened
EXECUTION STATE | phase=waiting_for_answer id=damage
EXECUTION STATE | phase=observed answer=damage
EXECUTION STATE | phase=observed tool=lookup_order
EXECUTION STATE | phase=observed tool=lookup_customer_history
EXECUTION STATE | phase=decided recommendation=approve
EXECUTION STATE | phase=ready_to_refund | DURABLE WAIT
EXECUTION STATE | Worker connected to localhost:7233 on task queue refund-stage-<token>
EXECUTION STATE | phase=refund_resumed
EXECUTION STATE | issuing refund: attempt 1, decision approve, idempotency key ...<last 8 hex>
THE SYSTEM | refund accepted at Stripe: re_dry_<16 hex> (dry-run, attempt 1)
```

- The second `Worker connected` line is the new Worker. No
  `agent_decide_next_step` or lookup output follows it, even though the new
  Worker runs the Workflow code again from the top. `workflow.logger` stays
  silent during replay, and each finished Activity returns its recorded result
  from Event History instead of running again. `phase=refund_resumed` is the
  first line from new work, which starts once the `release` Signal arrives.
- In the default mode, "at Stripe" means the offline ledger.

With `--real-model`, the `MODEL REASONING` lines are the model's choices. This
is from the measured 2026-10-02 run, condensed:

```text
MODEL REASONING | turn 3: plan -> call lookup_order
EXECUTION STATE | phase=observed tool=lookup_order
MODEL REASONING | turn 4: plan -> call lookup_customer_history
EXECUTION STATE | phase=observed tool=lookup_customer_history
MODEL REASONING | turn 5: plan -> call check_refund_policy
EXECUTION STATE | phase=observed tool=check_refund_policy
MODEL REASONING | turn 6: decide -> approve (Approve the $80.00 refund for order-1234. ...)
EXECUTION STATE | phase=decided recommendation=approve
```

- Turns 1 and 2 are the intake questions, which code asks without a model
  call.
- With `LOG_MODEL_USAGE=1`, each model call also logs a `MODEL USAGE` line
  with its input and output tokens.

## Watch it in the Temporal Web UI

### Start your own dev server

Start the dev server yourself if you want its Web UI to stay up after the
stage exits. The stage reuses any server it can reach at `TEMPORAL_ADDRESS`
(default `localhost:7233`), and it stops only the processes it started, so
your server and its Web UI stay up. A server the stage starts for you uses
`.demo-state/temporal.db`, and the stage shuts it down when it exits, which
takes the Web UI with it.

```bash
# Terminal 1: in-memory dev server, with a fresh Workflow list each time
temporal server start-dev
# Web UI: http://localhost:8233

# Terminal 2: give the run a name you can find in the Web UI
uv run refund-demo stage --workflow-id nyghtowl-take-01
```

If the default ports are taken, run this demo's server on other ports and
point the stage at it. The stage then connects to that server instead of
starting its own:

```bash
lsof -nP -iTCP:7233 -iTCP:8233 -sTCP:LISTEN   # who holds the default ports?

# Terminal 1
temporal server start-dev --port 7243 --ui-port 8243
# Web UI: http://localhost:8243

# Terminal 2
TEMPORAL_ADDRESS=localhost:7243 TEMPORAL_NAMESPACE=default \
  uv run refund-demo stage --workflow-id nyghtowl-take-01
```

- Check `.env` too. If `TEMPORAL_ADDRESS` names a remote server that answers,
  the stage uses that server.
- Never press Ctrl+C on a server someone else is using.

### What to check at each frame

Open the `RefundApprovalAgent` Workflow. The stage screens don't print its
Workflow ID. Without `--workflow-id`, the ID is `talk-refund-<token>`, where
`<token>` matches the `stage-<token>` folder in the `Stage logs:` line printed
at the end.

1. **At Demo 2's `Press Enter to submit the refund`:** on the Queries tab, run
   `stage_progress`. It returns:
   - `phase: "ready_to_refund"`
   - two `customer_answer` entries (with the default answers, `item_opened`:
     `Yes` and `damage`: `Split seam`)
   - the `lookup_order` and `lookup_customer_history` results
2. **After the kill (`WORKER GONE`):** use the History tab.
   - The Workflow's status is still `Running`.
   - The events include two `WorkflowExecutionSignaled` (`customer_answer`)
     events and the completed `agent_decide_next_step`, `lookup_order`, and
     `lookup_customer_history` Activities. There is no `issue_refund` and no
     pending Activity.
   - This is the same Event History that the stage's `WORKER GONE` pane reads.
   - Don't run a Query now, because Queries need a live Worker.
   - On the Workers tab, or the Task Queue page, check the Last Accessed time.
     A live Worker's time is never much more than a minute old. A killed
     Worker stays listed until 5 minutes after its last poll, and its Last
     Accessed time keeps getting older.
   - The Deployments page shows only versioned Workers, so it doesn't show
     this.
3. **After recovery:** the Workflow is `Completed`.
   - No new `agent_decide_next_step`, lookup, or `customer_answer` event
     appears. The new Worker ran the Workflow code again from the top, but
     each finished Activity returned its recorded result and each earlier
     Signal was read back from Event History, so none of them ran or arrived
     again.
   - The new application-level work is the `release` Signal and one
     `issue_refund` Activity at attempt 1, alongside the usual Workflow Task
     events.
   - The result carries the run's `idempotency_key`
     ([how it's derived](../README.md#architecture)).
   - That `ActivityTaskStarted` event's identity is the new Worker's
     `<pid>@refund-demo`, with a different PID from the first Worker's earlier
     `WorkflowTaskStarted` events.
   - Before the refund, you may see a `WorkflowTaskTimedOut` event
     (schedule-to-start). Temporal first offered the task to the killed Worker
     and stopped waiting after 10 seconds. The next `WorkflowTaskStarted`
     shows the new identity.
   - While the stage's last frame is up, a `stage_progress` Query returns
     `phase: "completed"`.

Each Activity row carries a plain-words summary:

- `Agent turn N: decide the next step`, for each agent turn
- `Look up order 1234`
- `Look up the customer's refund history`
- `Check the refund policy`
- `Issue the refund in Stripe`, after recovery (offline too, where the ledger
  stands in for Stripe)

A few more things show in the Web UI:

- Every client the demo starts reports `<pid>@refund-demo` instead of the SDK
  default `<pid>@<hostname>`, so the machine's hostname never appears on the
  Workers tab or in event identities.
- To replace that identity, set `TEMPORAL_IDENTITY`. The value is used
  verbatim, so a Worker restart no longer shows a new PID.
- The Workflow's summary also shows its Event History size, which
  [When Event History grows](HISTORY_GROWTH.md) uses.

![Temporal Web UI showing the running RefundApprovalAgent Workflow and its stage_progress Query at ready_to_refund](../assets/temporal-workflow-state.png)

### From the CLI

These commands work even when no Worker is running. For the port variant, add
`--address localhost:7243`.

```bash
temporal workflow describe --workflow-id nyghtowl-take-01
temporal workflow show --workflow-id nyghtowl-take-01
```

- `show` prints the Event History. Besides the events above, look for
  `WorkflowExecutionSignaled` when a human approves, and for `issue_refund`
  attempt 2 after a Worker recovery on the retry paths.
- `describe` also prints the history length and size.
  [When Event History grows](HISTORY_GROWTH.md) says why that matters in an
  agent loop.

## Manual walkthrough

The stage is the path the talk uses, and it runs everything for you in one
terminal. This walkthrough runs each process and each recovery step
separately, so you can watch one piece at a time. Use it for development,
rehearsal, debugging, or a longer technical session. It is also where the
later-loss case lives: a crash after Stripe accepts the refund.

Both demos run the same loop: two intake questions, then the lookups the agent
picks, then `issue refund`. In Demo 1, the loop's position exists only in its
process. In Demo 2, the answers arrive as Signals and the lookups run as
Activities, and Event History records both. The next action is Workflow
state, which replay rebuilds from those events. So a new Worker can pick up
the loop from Event History and resume without repeating questions.

### Setup and configuration

You need Python 3.11 or newer, the [Temporal CLI](https://docs.temporal.io/cli),
and [uv](https://docs.astral.sh/uv/). Then run:

```bash
uv sync --extra dev --extra tui
test -e .env || cp .env.example .env   # never overwrites an existing .env
```

Fill in only the services you use. The Worker and CLI load `.env`
automatically, and exported shell values take precedence. Configuration is
never loaded into deterministic Workflow code.

**The model and the refund effect are independent.** Whether a run calls a
model and whether it touches Stripe are separate choices:

- `refund-demo start` calls the live model whenever a model key is set, even
  with `--dry-run`. Without a model key, it uses the deterministic policy and
  makes no model calls.
- The stage uses a model only with `--real-model`.
- `AGENT_MODEL_PROVIDER` selects `anthropic` or `openai`, and the CLI option
  `--model-provider` records that choice in the Workflow input.
- For the refund, `--dry-run` writes to an offline Stripe-like ledger under
  `.demo-state`. `--real` calls Stripe test mode and requires a `sk_test_` or
  `rk_test_` key; live Stripe keys are rejected.

| Variable | Purpose |
| --- | --- |
| `AGENT_MODEL_PROVIDER` | Selects `anthropic` or `openai` when using a live model |
| `ANTHROPIC_API_KEY` | Enables Claude model reasoning |
| `ANTHROPIC_MODEL` | Claude model ID used when Anthropic is selected |
| `OPENAI_API_KEY` | Enables OpenAI model reasoning |
| `OPENAI_MODEL` | OpenAI model ID used when OpenAI is selected |
| `STRIPE_API_KEY` | Stripe test key required by `--real` |
| `EFFECT_RESTART_WINDOW_SECONDS` | Holds the later-loss boundary open for a Worker kill |
| `LOG_MODEL_USAGE` | Set to `1` to log each live model call's tokens to `model-usage.jsonl` in `DEMO_STATE_DIR`.<br>Summarize them with `uv run refund-demo usage` |
| `TEMPORAL_ADDRESS` | Temporal endpoint, default `localhost:7233` |
| `TEMPORAL_NAMESPACE` | Temporal Namespace, default `default` |
| `TEMPORAL_TASK_QUEUE` | Worker Task Queue, default `refund-demo` |
| `TEMPORAL_IDENTITY` | Client identity shown in the Web UI, used verbatim by every process.<br>When it's unset, each process reports `<pid>@refund-demo` instead of the SDK's `<pid>@<hostname>` |
| `DEMO_STATE_DIR` | Offline ledger, views, logs, and local state, default `.demo-state` |

### Start Temporal and the Worker

Terminal 1:

```bash
mkdir -p .demo-state
temporal server start-dev --db-filename .demo-state/temporal.db
```

The Web UI is at <http://localhost:8233>. If another Temporal server is
already on `:7233`, use that server and skip the start command.

Terminal 2:

```bash
uv run refund-worker
```

Python does not reload a running Worker. Restart it after changing Workflow or
Activity code.

### Demo 1 by hand

Run the two-pane agent process:

```bash
uv run naive-refund
```

The left pane, `AGENT PROCESS`, shows the agent loop inside the process. The
right pane, `WHAT SURVIVES`, shows the paid order and the refund state. Run
standalone, it reads Demo 1's offline ledger, so its heading is
`OFFLINE LEDGER (Stripe stand-in)`.

1. Press Enter or type `refund`. The standalone view condenses the agent's two
   questions, two answers, and two lookups into its completed-loop checklist,
   while the stage asks the questions one at a time.
2. Type `restart` (`deploy` and `oom` do the same). The pane becomes
   `NEW AGENT PROCESS`: "No answers. No next step." Stripe still says paid
   with no refund (`FRESH START`).
3. Ask, `What happened to my refund?`
4. The new agent process checks Stripe and answers correctly. But the customer
   must start the return over, because there is no active execution to
   resume.

Type `reset` to start over, or `quit` to exit.

In `refund-demo stage --real`, step 4 reads Stripe directly. It retrieves the
test PaymentIntent and its refund list inside a fresh agent-process
subprocess. The question crosses stdin and the result crosses structured
stdout, so this is a real process boundary, not a UI-only transition. No
refund is submitted here; the stage's only refund submission comes later, in
Demo 2.

**What this shows.** Stripe's record of the payment survives the crash, but
the agent's working memory and its unfinished work die with the process. A
long-term memory store could bring back the customer's answers. It still
wouldn't say where the loop stood or what to do next, and Stripe's record
doesn't either, because it only knows the payment and its refunds. That
missing piece is execution state. You could build it yourself with a
database-backed state machine and a recovery job. Demo 2 uses Temporal
instead.

To run the stage's autonomous loop, with its pause before the refund:

```bash
uv run naive-refund reset
uv run naive-refund refund --order 1234 --interactive-loop --hold-before-effect
```

For a live model, add `--real-model --model-provider openai` (or `anthropic`).

The command asks its questions on stdin, emits each `AGENT STEP`, and waits
after choosing the refund. It writes no refund to the ledger.

- If the model denies, it prints `no refund issued for order 1234` and exits
  instead of waiting.
- With `--real-model` and no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, it stops
  with an `AGENT ERROR` line rather than falling back to the fixed policy.

The older post-effect boundary is still available for technical comparison:

```bash
uv run naive-refund refund --order 1234 --exit-after-effect
uv run naive-refund ledger
```

### Demo 2 by hand

With Temporal and the Worker running, start a refund and wait for it:

```bash
uv run refund-demo start --dry-run --workflow-id demo-refund
uv run refund-demo result demo-refund
```

The Worker prints the request context, each model-reasoning turn, retrieved
memory, the decision, and execution-state transitions.

If the agent escalates, approve it:

```bash
uv run refund-demo approve demo-refund "verified defect, approving"
uv run refund-demo result demo-refund
```

Low-value requests tend to approve automatically. To push the deterministic
policy toward escalation, use a larger amount, such as `--amount-cents 15000`.

To terminate a Workflow you do not want to release:

```bash
uv run refund-demo stop demo-refund
```

**Stripe test mode.** Put a test key in `.env`:

```text
STRIPE_API_KEY=sk_test_...
```

Then seed a succeeded test charge and refund it:

```bash
uv run refund-demo start --real --seed --workflow-id stripe-refund-demo
uv run refund-demo approve stripe-refund-demo "approved"   # if it escalates
uv run refund-demo result stripe-refund-demo
uv run refund-demo cleanup   # refunds any leftover seeded charges
```

This runs in Stripe test mode only. It never creates a live charge, and it
rejects live keys.

### Later loss: after Stripe accepts the refund

The stage stops the agent before the refund. Here the failure lands later:
Stripe accepts the refund, then the Worker dies before the Activity reports
it. At that point only Stripe knows the refund went out, and the process
can't know whether money moved.

This matters because an Activity that was in flight at a crash can run again,
so its call must be safe to send twice.

**In one terminal,** the stage runs the whole case for you:

```bash
uv run refund-demo stage --real --simulate-stripe-retry   # drop --real to rehearse offline
```

Like the default path, this pauses before the refund, and the stage sends the
demo-only `release` Signal to end the pause.

1. The runner waits until Stripe accepts attempt 1.
2. It kills the Worker before the Activity reports completion.
3. It pauses with the retry unresolved.
4. Press Enter to start a new Worker.
5. Attempt 2 uses the same Stripe idempotency key and returns the same refund.

Event History compacts the failure, so it shows no separate
`ActivityTaskTimedOut` event. Instead, after recovery, the
`ActivityTaskStarted` event carries `attempt: 2` and a `lastFailure` heartbeat
timeout.

**In four terminals,** you can run the complete real Stripe path:

```bash
# Terminal 1: Temporal
temporal server start-dev --db-filename .demo-state/temporal.db

# Terminal 2: a Worker that holds the uncertain boundary open
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker

# Terminal 3: two-panel view
uv run refund-demo watch demo-restart

# Terminal 4: start a seeded Stripe test refund
uv run refund-demo start --real --seed --workflow-id demo-restart
uv run refund-demo approve demo-restart "approved"   # if it escalates
```

Wait for these lines in Terminal 2:

```text
THE SYSTEM      | refund accepted at Stripe: re_... (stripe-test, attempt 1)
EXECUTION STATE | restart window open 30s; run: refund-demo kill-worker
```

Kill the Worker and inspect the ambiguous boundary from Terminal 4:

```bash
uv run refund-demo kill-worker
uv run refund-demo inspect demo-restart
```

Stripe already has the refund, but Temporal does not yet have a completed
Activity result.

Restart the Worker in Terminal 2. Either command works, because the restart
window opens only on attempt 1:

```bash
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker   # or: uv run refund-worker
```

Then wait for the result, inspect again, and reconcile the test charge from
Terminal 4:

```bash
uv run refund-demo result demo-restart
uv run refund-demo inspect demo-restart
uv run refund-demo cleanup
```

The final inspection shows that `issue_refund` completed on attempt 2, that
two calls used the same idempotency key, and that one unique refund exists.

**Timing and running it offline.** Keep the restart window under the normal
60-second Activity start-to-close timeout. The schedule-to-close budget is 10
minutes, so the Worker can take longer to come back without losing the run. To
run this offline, replace `--real --seed` with `--dry-run`. Without the
restart window, the run completes with no later loss.

**Why there is still one refund.** Two calls reached Stripe, but only one
refund exists. Stripe's idempotency support stops a repeated call from
creating a second refund, and both attempts in one run send the same key
because it comes from the Workflow run's identity
([how](../README.md#architecture)). Temporal records that the step is
unresolved, schedules the retry after the Worker disappears, and records the
result once an attempt finishes. It doesn't merge its record and Stripe's into
one database transaction ([two owners](#two-owners)); instead, it gives the
uncertain attempt a durable recovery point and a stable identity. One
condition applies: a restarted application can read the result only if it
keeps or derives the same Workflow ID.

### The clean replay case

The later loss needs idempotency, because the first call may have committed
without a recorded Activity result. The common case is simpler: once a step
completes and is recorded, replay returns its result without running it again.

Start a Worker without the restart window, and hold the Workflow after the
refund:

```bash
uv run refund-worker
uv run refund-demo start --dry-run --hold --workflow-id demo-hold
```

`--hold` sets a second demo-only flag, `hold_after_effect`. The Workflow
pauses after the refund instead of before it, and the same `release` Signal
ends the pause.

After the Worker prints `refund recorded; holding for release`, kill and
restart it:

```bash
uv run refund-demo kill-worker
uv run refund-worker
```

Inspection still shows one call on attempt 1. Release the Workflow:

```bash
uv run refund-demo release demo-hold
uv run refund-demo result demo-hold
```

Replay returned the completed step's recorded result, so the step didn't run
again. The idempotency key is the backstop only for the boundary where the
result was not recorded.

### Two-panel view

```bash
uv run refund-demo watch demo-restart
```

The left panel is the Worker's in-process decision view. It shows the current
context, the retrieved domain facts copied into working memory, and the
decision. When the Worker disappears, the left panel reads `LOST`, and when a
new Worker resumes, replay fills it in again.

The right panel keeps five things apart: the execution state Temporal records,
the effect state owned by Stripe or the offline ledger, the pending Activity
attempt, the refund ID and call count, and the unique refund count.

For a talk, make the terminal fullscreen. Press Ctrl+C to exit.

### Recovery notes

- `result` reads and waits; it does not drive the Workflow. If `result` hangs,
  see [Troubleshooting](#troubleshooting).
- Use a fresh Workflow ID for each run, and terminate a stale run with
  `refund-demo stop <id>`.
- Do not resume a run created under incompatible older Workflow code.
- To see a manual run's Event History, use [the CLI commands](#from-the-cli)
  with its Workflow ID, such as
  `temporal workflow show --workflow-id demo-restart`.

## Authorization companion demo

The refund demos are about execution state and effect state: where the work
stands and whether the refund happened. This companion applies the same
boundary to authorization state:

> May this agent push to my repository?

The authorization system owns the answer. Context and memory may carry a copy,
but they cannot make a revoked grant current again. The push is simulated, so
nothing touches GitHub.

```bash
uv run permission-chat --panes   # two-pane view (needs the tui extra)
uv run permission-chat           # single-pane REPL
```

1. Say "you can push" to grant permission.
2. Say "push" to make the agent act.

`:help` lists every command.

| Case | Try | What happens |
| --- | --- | --- |
| Context only | Grant, then `:new` | The grant exists for the current conversation and disappears on `:new`.<br>Fine for conversational intent, not for an authorization fact that must stay enforceable. |
| Remembered permission | `:remember on`, grant, then `:revoke` | The agent recalls the grant across sessions.<br>`:revoke` revokes it in the external system, but memory still says yes.<br>If the agent trusts that recollection, it acts on a permission that no longer exists. |
| Authoritative permission state | `:state on`, `:revoke`, then push | The agent refuses, because it checks the current system of record. |

Remembering "you may push" is not the same as being authorized now. The
pattern is the same as the refund:

| Agent copy | Authoritative record |
| --- | --- |
| "I already refunded" | Stripe refund state |
| "You may push" | Authorization grant |

When they disagree, the owner of the fact wins.

## Troubleshooting

Errors from `refund-demo stage` start with `STAGE |`. Workflow and Activity
failures show up in the Web UI and in `.demo-state/stage-<token>/worker.log`.
The first five rows are the most likely.

| You see | Cause | Fix |
| --- | --- | --- |
| ``STAGE \| Temporal is not reachable and the `temporal` CLI is not on PATH`` | Nothing answers at `TEMPORAL_ADDRESS`, and the stage can't start a server | Install the Temporal CLI, or run `temporal server start-dev` first |
| `STAGE \| Temporal dev server exited while starting:` plus a log tail | Usually port 7233 or 8233 is already in use | Run `lsof -nP -iTCP:7233 -iTCP:8233 -sTCP:LISTEN`, then use the port variant in [Start your own dev server](#start-your-own-dev-server) |
| `STAGE \| Worker exited while starting:` plus a log tail | The Worker crashed at startup.<br>A common cause is a live or malformed `STRIPE_API_KEY` in `.env`, which the Worker rejects even in offline mode | Read the tail.<br>Use a `sk_test_` or `rk_test_` key, or remove the key |
| `The stage view needs rich. Install it with: uv sync --extra tui` | Running `uv sync` without `--extra tui` removed the optional Rich extra | Run `uv sync --extra dev --extra tui` |
| `WorkflowAlreadyStartedError` traceback | You reused a `--workflow-id` while that run is still Running | Use a new ID, or run `uv run refund-demo stop <id>` |
| `STAGE \| could not connect to configured Temporal service <address>` | `TEMPORAL_ADDRESS` names a non-local host that isn't answering.<br>The stage won't silently fall back to localhost | Fix or unset `TEMPORAL_ADDRESS` |
| `STAGE \| Temporal dev server did not become ready` | The started server didn't answer within 20 s.<br>This also happens when `TEMPORAL_ADDRESS` uses a localhost port other than 7233, because the stage starts its server without `--port` | Start the server yourself on the port you configured, or unset `TEMPORAL_ADDRESS` |
| `STAGE \| both live-model keys are configured; choose --model-provider` | Both model keys are set and `AGENT_MODEL_PROVIDER` is blank | Add `--model-provider anthropic` or `--model-provider openai` |
| `STAGE \| --real-model requires ANTHROPIC_API_KEY or OPENAI_API_KEY`, or `STAGE \| anthropic live model requires ANTHROPIC_MODEL` | A live model was requested without its key or model name | Set both in `.env` |
| `STAGE \| --model-provider requires --real-model` | You passed a provider without `--real-model` | Add `--real-model`, or drop `--model-provider` |
| `STAGE \| STRIPE_API_KEY is required for a real refund`, `STAGE \| A live Stripe key was detected and has been rejected`, or `STAGE \| STRIPE_API_KEY must be a Stripe test mode key` | `--real` needs a Stripe test key | Put a `sk_test_` or `rk_test_` key in `.env`, or drop `--real` |
| `STAGE \| Stripe could not create the test payment: ...` or `STAGE \| Stripe could not verify the naive outcome: ...` | Stripe rejected the call or couldn't be reached | Check the key and the network, or run the offline default |
| `STAGE \| timed out waiting for the durable agent loop` | Demo 2's Workflow didn't reach `ready_to_refund` within 90 s.<br>With `--real-model`, a model turn usually failed (see the next rows) | Open the Workflow in the Web UI, or read `worker.log` in the newest `.demo-state/stage-*` folder |
| `Anthropic returned a permanent error (HTTP 400): ...` | `ANTHROPIC_MODEL` names a model that rejects the forced tool choice this code sends (`tool_choice` type `any`), for example `claude-sonnet-5-5`, `claude-opus-5-5`, or `claude-fable-5-1` | Use `claude-sonnet-4-6` |
| `agent did not reach a decision within the turn budget` (type `AgentLoopExhausted`) | The live model used all 10 turns without calling `submit_decision` | Run it again, and check the request text and the model |
| `agent asked for an unknown tool: ...` or `agent asked an unsupported question: ...` | The live model chose a tool or question the loop doesn't allow.<br>These are non-retryable by design | Run it again |
| `LOG_MODEL_USAGE must be 1, true, yes, 0, false, or no` in `worker.log` | `LOG_MODEL_USAGE` has another value.<br>Each live model turn then fails before the paid call, so Temporal's retries make no API calls, and the stage times out | Set it to `1` or unset it |
| `MODEL USAGE \| no usage log at ...` | `LOG_MODEL_USAGE` was off during the run, or `usage` looked in the wrong folder | Pass the `Stage logs:` path as `--state-dir`, or run again with `LOG_MODEL_USAGE=1` |
| `Stripe rejected the refund: ...` (type `StripeRefundError`) | Stripe refused the refund, for example `refund-demo start --real` run against the default `pi_dry_run_demo` | Use `refund-demo start --real --seed`, or pass a real test PaymentIntent |
| `Stripe refund call failed (retryable): ...` (type `StripeRetryableError`) in an `issue_refund` attempt's failure | The refund call timed out (3 s to connect, 10 s of silence while reading), lost its connection, or got a 409, 429, or 5xx that Stripe did not mark `Stripe-Should-Retry: false`.<br>Temporal retries it with the same idempotency key.<br>If Stripe sent a `Retry-After` of 60 s or less, the retry honors it first; a longer one is ignored | Usually nothing. If every attempt fails, check the network and Stripe's status |
| `Could not re-read Temporal.` and `Showing the earlier reading:` in the `WORKER GONE` pane | The Event History read failed or took longer than 3 s.<br>The counts shown are from before the Worker stopped | Check the Temporal server, then open the Workflow's History tab in the Web UI |
| A Query in the Web UI fails or hangs during `WORKER GONE` | Queries need a live Worker | Use the History tab while the Worker is gone |
| `Starting a new Worker. It picks up from Temporal's history...` stays up for several seconds | Temporal may first offer the new task to the killed Worker's sticky queue and wait out its timeout (10 s by default in the Python SDK).<br>A `WorkflowTaskTimedOut` event may appear | Expected; nothing to fix |
| `refund-demo result <id>` hangs | No Worker is polling that Workflow's Task Queue | If you started it with `refund-demo start`, run `uv run refund-worker`.<br>A stage Workflow uses a private `refund-stage-<token>` Task Queue that only the stage's own Worker polls |
| `THE SYSTEM \| cleanup done, refunded $0.00 of demo charges` | There was no outstanding demo test payment | Not an error |
