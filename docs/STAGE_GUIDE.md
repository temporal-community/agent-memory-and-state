# Guided stage runner

Back to the [README](../README.md). The README's
[Choose the stage path](../README.md#choose-the-stage-path) table lists the
commands and their model tokens and dollars per pass; this page explains what
the runner does and what each option needs.

## What the runner does

The guided runner:

1. Welcomes Nyghtowl back and shows the last python-plushy order as `PAID`.
2. Lets you ask for a refund. The naive agent process asks two scripted
   questions (press Enter to accept each suggested answer), reports two
   lookups, and chooses `issue refund`.
3. Kills the naive agent process after it chooses `issue refund` but before any
   refund call, then holds on a visible `PROCESS GONE` frame.
4. Starts a new agent process (`NEW AGENT PROCESS`) and sends the customer's
   status question across that process boundary. The new process checks the
   effect owner; in
   `--real` mode it retrieves the PaymentIntent and refund list directly from
   Stripe without submitting a refund. The customer starts the return again
   (`THE CUSTOMER STARTS OVER`).
5. Starts the durable Workflow and replays your Demo 1 answers into it as
   `answer_question` Signals; the screen says "Reusing your Demo 1 answers so
   you don't type them twice..." The lookups run as Activities.
6. Kills the Worker at the same next action. The `WORKER GONE` frame reads Event
   History from Temporal, which needs no Worker, and shows two customer
   answers, two completed lookups, and `Next action: issue refund` under
   `Read from Temporal just now:`.
7. Starts a new Worker and sends the stage-only `release` Signal. The
   `NEW TEMPORAL WORKER` resumes at `issue refund` without repeating questions,
   issues the refund, and reports completion.

Every input prompt says literally what Enter does next, such as
`Press Enter to submit the refund`, and each demo's
header has a dim line naming what is scripted.

It uses a deterministic policy and offline Stripe-like ledger by default; the
screens label it `OFFLINE LEDGER (Stripe stand-in)`. It
starts a local Temporal dev server only when one is not already reachable and
shuts down only the processes it started.

## Simulated Stripe timeout

The timeout path is the recommended retry demo. Attempt 1 enters
`issue_refund`, but the simulated Stripe API does not respond before the Worker
disappears. This path sends no `release` Signal. Temporal advances the Activity
to attempt 2 and waits until you start a new Worker; only then does
the refund reach Stripe.

## Live models and Stripe test mode

Add `--real-model --model-provider anthropic` for Claude or
`--real-model --model-provider openai` for OpenAI. Claude mode requires
`ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`; OpenAI mode requires
`OPENAI_API_KEY` and `OPENAI_MODEL`. Real refund mode requires a Stripe
`sk_test_` or `rk_test_` key. Live Stripe keys are rejected. Put local values in
`.env`; exported shell variables take precedence. If the model escalates
instead of approving, the stage sends the approval Signal itself, with the note
`approved by the guided stage runner`.

## `--real` mode and cleanup

In `--real` mode, the runner creates and confirms Nyghtowl's Stripe test
PaymentIntent before the first refund prompt. The naive replacement reads that
PaymentIntent and its refunds from Stripe and confirms no refund reached
Stripe; only the durable half later refunds the test payment. The other
`Payment: PAID` lines on screen are fixed labels (see
[What it is not](../README.md#what-it-is-not)). If a run ends before the
refund, reconcile it with:

```bash
uv run refund-demo cleanup
```

Cleanup refunds only outstanding test payments created by this demo. It does
not delete Stripe test objects or make the Dashboard's row counts match: Stripe
retains both payment and refund records. `refunded 0 cents` means the cleanup
scan found no outstanding recognized demo payment.

## Testing a live model

Test a live model against the offline ledger before combining it with `--real`.
The demo uses a fixed, refund-eligible python-plushy order, so the spoken request
should refer to order 1234 or the python plushy. Its policy record explicitly says
that this low-value damaged item does not require a physical return. If a live
model denies a conflicting request, the stage shows its rationale and the fact
that no refund was issued instead of exiting on an empty screen.

## Post-commit uncertainty: `--simulate-stripe-retry`

For the advanced post-commit uncertainty case, use
`--simulate-stripe-retry`. Stripe accepts attempt 1, but the Worker disappears
before Temporal records the result. Attempt 2 reuses the same idempotency key,
so two calls resolve to one refund. Like the default path, this mode uses the
stage-only `release` Signal; it is the technical idempotency walkthrough, not
the recommended API-outage story. Both simulation flags also work without
`--real` for an offline rehearsal.
