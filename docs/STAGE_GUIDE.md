# Guided stage runner

Back to the [README](../README.md). The README's
[Choose the stage path](../README.md#choose-the-stage-path) table lists the
commands and their model tokens and dollars per take; this page explains what
the runner does and what each option needs.

## What the runner does

The guided runner:

1. Welcomes Nyghtowl back and shows the last python-plushy order as `PAID`.
2. Lets you ask for a refund. The naive agent process asks the two intake
   questions (press Enter to accept each suggested answer), runs the lookups
   its policy or model picks (two on the default path), and chooses
   `issue refund`. It calls the same decision step as Demo 2, in process.
3. Kills the naive agent process after it chooses `issue refund` but before any
   refund call, then holds on a visible `PROCESS GONE` frame.
4. Starts a new agent process (`NEW AGENT PROCESS`) and sends the customer's
   status question across that process boundary. The new process checks the
   effect owner; in
   `--real` mode it retrieves the PaymentIntent and refund list directly from
   Stripe without submitting a refund. The customer starts the return again
   (`THE CUSTOMER STARTS OVER`).
5. Starts the durable Workflow and replays your Demo 1 answers into it as
   `customer_answer` Signals; the screen says "Reusing your Demo 1 answers so
   you don't type them twice..." The lookups run as Activities, each with a
   plain-words summary in Event History, such as `Look up order 1234`.
6. Kills the Worker at the same next action. The `WORKER GONE` frame reads Event
   History from Temporal, which needs no Worker, and shows two customer
   answers, the completed lookups (two by default, three when a live model also
   checks the refund policy), and `Next action: issue refund` under
   `Read from Temporal just now:`.
7. Starts a new Worker and sends the stage-only `release` Signal. The
   `NEW TEMPORAL WORKER` resumes at `issue refund` without repeating questions,
   issues the refund, and reports completion.

The screens call the naive side the agent process (`PROCESS GONE`,
`NEW AGENT PROCESS`), because it is not a Temporal Worker, and keep "Worker"
for the Temporal side (`WORKER GONE`, `NEW TEMPORAL WORKER`).

Every input prompt says literally what Enter does next, such as
`Press Enter to submit the refund`, and each demo's header has a dim line
naming what is scripted or live: by default
`Scripted steps · offline ledger (no Stripe)` in Demo 1 and
`Fixed policy (no LLM) · sample lookups · offline ledger (no Stripe)` in
Demo 2; with `--real-model`, `Live model (openai) · sample lookups · …` (or
`anthropic`) in both.

It uses a deterministic policy and offline Stripe-like ledger by default; the
screens label it `OFFLINE LEDGER (Stripe stand-in)`. It
starts a local Temporal dev server only when one is not already reachable and
shuts down only the processes it started.

## Put it under real conditions

The failure is a Temporal Worker that dies mid-loop. The default stage run
sends it a real SIGKILL one step before the refund. Before the kill, Demo 2's
agent loop shows `→ Next: issue refund`, the stage waits for Enter, and the
Worker is still alive.

After the kill (`WORKER GONE`), the Workflow is still `Running`, with no Worker.
That is normal: the Workflow lives on the Temporal server, and Workers only poll
its task queue.

To watch it, [start your own dev server](TEMPORAL_WEB.md#start-your-own-dev-server)
first, then follow
[What to check at each frame](TEMPORAL_WEB.md#what-to-check-at-each-frame): the
`stage_progress` Query before the kill, the History and Workers tabs while the
Worker is gone, and the completed history after recovery.

## Simulated Stripe timeout

The timeout path is the recommended retry demo. It kills the Worker while the
refund Activity is in flight instead. Run `make failure`, or the command it
runs:

```bash
uv run refund-demo stage --simulate-stripe-timeout
```

Attempt 1 enters `issue_refund`, but the simulated Stripe API does not respond,
and the Worker is killed before any refund is accepted. This path sends no
`release` Signal. Temporal advances the Activity to attempt 2 and waits until
you start a new Worker. The new Worker runs attempt 2 with the same idempotency
key; only then does the refund reach Stripe. This command runs offline with no
model calls (0 tokens, $0).

## Live models and Stripe test mode

Add `--real-model --model-provider anthropic` for Claude or
`--real-model --model-provider openai` for OpenAI. Claude mode requires
`ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`; OpenAI mode requires
`OPENAI_API_KEY` and `OPENAI_MODEL`. Real refund mode requires a Stripe
`sk_test_` or `rk_test_` key. Live Stripe keys are rejected. Put local values in
`.env`; exported shell variables take precedence. Both demos use the live
model: Demo 1's agent process calls it directly, with no retry layer, and Demo
2 calls it from the `agent_decide_next_step` Activity. If the model escalates
instead of approving, the stage sends the approval Signal itself, with the note
`approved by the guided stage runner`, and Demo 1 treats the escalation the
same way. If the model denies Demo 1's request, the stage stops with a message,
because there is no refund to interrupt.

While Demo 1 waits on the model, the screen shows
`The agent is choosing its next step...`. If Demo 1's process fails, for
example on an API error, the stage stops and prints the reason
(`STAGE | the Demo 1 agent process failed: …`); with no retry layer, one failed
model call ends Demo 1. Both providers see the order amount as `"$80.00"`,
never cents, so the model's rationale reads like
`Approve the $80.00 refund for order-1234…`. The stored request and working
memory keep cents. The [expected output](EXPECTED_OUTPUT.md#with-a-live-model)
lists the on-screen differences.

## Which lines read Stripe

Not every Stripe line on screen is a live Stripe read. `Payment: PAID` in the
durable pane, and in the naive pane before the kill, is a fixed label. The
durable refund line reads a local mirror of Stripe's response. Only the new
agent process's status check reads Stripe directly, and only with `--real`;
offline, it reads its own naive ledger. In the default mode the pane heading
says `OFFLINE LEDGER (Stripe stand-in)` (with `--real`, `STRIPE (test mode)`),
but the agent's lines, the Worker log, and the `issue_refund` summary in Event
History still say "Stripe" as the story's name for the effect owner.

## `--real` mode and cleanup

In `--real` mode, the runner creates and confirms Nyghtowl's Stripe test
PaymentIntent before the first refund prompt. The naive replacement reads that
PaymentIntent and its refunds from Stripe and confirms no refund reached
Stripe; only the durable half later refunds the test payment. The other
`Payment: PAID` lines on screen are fixed labels (see
[Which lines read Stripe](#which-lines-read-stripe)). If a run ends before the
refund, reconcile it with:

```bash
uv run refund-demo cleanup
```

Cleanup refunds only outstanding test payments created by this demo. It does
not delete Stripe test objects or make the Dashboard's row counts match: Stripe
retains both payment and refund records. `refunded $0.00` means the cleanup
scan found no outstanding recognized demo payment.

## Testing a live model

Test a live model against the offline ledger before combining it with `--real`.
The demo uses a fixed, refund-eligible python-plushy order, so the spoken request
should refer to order 1234 or the python plushy. Its policy record explicitly says
that this low-value damaged item does not require a physical return. If a live
model denies a conflicting request in Demo 1, the stage stops before Demo 2 and
says so. A denial in Demo 2 shows the model's rationale and the fact that no
refund was issued instead of exiting on an empty screen.

## Post-commit uncertainty: `--simulate-stripe-retry`

For the advanced post-commit uncertainty case, use
`--simulate-stripe-retry`. Stripe accepts attempt 1, but the Worker disappears
before Temporal records the result. Attempt 2 reuses the same idempotency key,
so two calls resolve to one refund. Like the default path, this mode uses the
stage-only `release` Signal; it is the technical idempotency walkthrough, not
the recommended API-outage story. Both simulation flags also work without
`--real` for an offline rehearsal.
