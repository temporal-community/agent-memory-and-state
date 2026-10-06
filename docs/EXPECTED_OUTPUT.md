# Expected output

Back to the [README](../README.md). This page has the full condensed stage
transcript, the pane text when the history read fails, what changes with a
live model, and the Worker log that shows the resume.

## Stage transcript

Default run: `uv run refund-demo stage --workflow-id nyghtowl-take-01`,
pressing Enter at every prompt. The frames below are condensed, with the box
drawing removed. Pane titles are in capitals.

To check a run quickly, look for these lines in order.

- Demo 1: `→ Next: issue refund`, `PROCESS GONE`, then
  `No refund request reached Stripe.` and `Please start the return again.`
- Demo 2: `WORKER GONE`, `Read from Temporal just now:` with
  `Next action: issue refund`, then `NO REPEATED QUESTIONS`,
  `NO LOOP RESTART`, and `Your refund is complete.`

```text
Agent memory and state
  An agent can know exactly what to do and still lose the work a customer submitted.
  We'll stop the agent right before it calls Stripe: first without Temporal, then with it.
Three things that help an agent act
  CONTEXT  what the agent can see right now
  MEMORY   what the agent remembers or looks up
  STATE    the official record: what's done and what's next
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

With `--real`, the ledger heading reads `STRIPE (test mode)` and the header
lines end in `Stripe test mode`. The `Stage logs:` path is relative to the
directory you ran the stage from, so it works as `refund-demo usage --state-dir`
from there.

The durable `WORKER GONE` frame can take up to 3 seconds to appear, because it
reads Event History while it draws. If that read fails or runs out of time, the
pane says `Could not re-read Temporal.` and `Showing the earlier reading:`
instead of `Read from Temporal just now:`.

## With a live model

`stage --real-model --model-provider openai` (or `anthropic`) runs both demos
on the live model, through the same decision step. Compared with the default
transcript:

- Both demo headers start with `Live model (openai)` or
  `Live model (anthropic)`, instead of `Scripted steps` in Demo 1 and
  `Fixed policy (no LLM)` in Demo 2. With `--real`, both read
  `Live model (openai) · sample lookups · Stripe test mode`.
- While Demo 1 waits on the model, the screen shows
  `The agent is choosing its next step...`.
- The model picks the lookups. In the measured 2026-10-02 take it also checked
  the policy in both demos, so each loop adds
  `✓ Refund policy: eligible (memory)`, and Demo 2's pane shows
  `Completed lookups: 3`.
- The model sees the order amount as `"$80.00"`, never cents, so its rationale
  speaks in dollars.
- The new Demo 1 process still says "No refund request reached Stripe. I lost
  your return answers. Please start the return again." That reply is fixed
  text, not model output.
- If the model denies the Demo 1 request, the stage stops before Demo 2 with
  `STAGE | the model denied the Demo 1 refund; run the stage again`, plus a
  cleanup hint for a `--real` take. A Demo 2 denial shows the model's rationale
  and that no refund was issued.
- If Demo 1's process fails, for example on a missing key or an API error, the
  stage stops with `STAGE | the Demo 1 agent process failed: <reason>`. Demo 1
  has no retry layer, so one failed model call ends it.

In Temporal Web, each Activity row carries a plain-words summary:
`Agent turn N: decide the next step`, `Look up order 1234`,
`Look up the customer's refund history`, `Check the refund policy`, and
`Issue the refund in Stripe` (also offline, where the ledger stands in for
Stripe). See [Temporal Web](TEMPORAL_WEB.md#what-to-check-at-each-frame).

## Worker log

The Worker log (`.demo-state/stage-<token>/worker.log`) shows the resume. This
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

The second `Worker connected` line is the new Worker. No
`agent_decide_next_step` or lookup output follows it, because replay reads
those results from Event History instead of running them again. In the default
mode, "at Stripe" means the offline ledger.

With `--real-model`, the `MODEL REASONING` lines are the model's choices. From
the measured 2026-10-02 take, condensed:

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

Turns 1 and 2 are the intake questions, which code asks without a model call.
With `LOG_MODEL_USAGE=1`, each model call also logs a `MODEL USAGE` line with
its input and output tokens.
