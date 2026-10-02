# Expected output

Back to the [README](../README.md). The README's
[What you should see](../README.md#what-you-should-see) lists the key lines;
this page has the full condensed transcript and the Worker log.

## Stage transcript

Default run: `uv run refund-demo stage --workflow-id nyghtowl-take-01`,
pressing Enter at every prompt. The frames below are condensed, with the box
drawing removed. Pane titles are in capitals.

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
    ✓ Found order: python plushy
    ✓ Checked refund history: clean
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
                     ✓ Found order: python plushy
                     ✓ Checked refund history: clean
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
Memory helps the agent decide.
Temporal records where the work stands.
Stripe knows whether money moved.
Stage logs: .demo-state/stage-<token>
```

With `--real`, the ledger heading reads `STRIPE (test mode)` and the header
lines end in `Stripe test mode`. With `--real-model`, the Demo 2 header starts
with `Live model (anthropic)` or `Live model (openai)` instead of
`Fixed policy (no LLM)`. The `Stage logs:` path is relative to the directory
you ran the stage from, so it works as `refund-demo usage --state-dir` from
there.

The durable `WORKER GONE` frame can take up to 3 seconds to appear, because it
reads Event History while it draws. If that read fails or runs out of time, the
pane says `Could not re-read Temporal.` and `Showing the earlier reading:`
instead of `Read from Temporal just now:`.

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

The second `Worker connected` line is the new Worker. No `agent_step`
or lookup output follows it, because replay reads those results from Event
History instead of running them again. In the default mode, "at Stripe" means
the offline ledger.
