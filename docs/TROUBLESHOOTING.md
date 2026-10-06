# Troubleshooting

Back to the [README](../README.md).

Stage errors are printed as `STAGE | <message>`. Workflow and Activity failures
show up in Temporal Web and in `.demo-state/stage-<token>/worker.log`.

The five most likely errors are Temporal not reachable, the dev server or the
Worker exiting while starting, the missing Rich extra, and
`WorkflowAlreadyStartedError`. The full table below also covers configuration,
live-model, Stripe, timeout, usage-log, and Temporal Web errors.

| You see | Cause | Fix |
| --- | --- | --- |
| ``STAGE \| Temporal is not reachable and the `temporal` CLI is not on PATH`` | Nothing answers at `TEMPORAL_ADDRESS`, and the stage can't start a server | Install the Temporal CLI, or run `temporal server start-dev` first |
| `STAGE \| could not connect to configured Temporal service <address>` | `TEMPORAL_ADDRESS` names a non-local host that isn't answering. The stage won't silently fall back to localhost | Fix or unset `TEMPORAL_ADDRESS` |
| `STAGE \| Temporal dev server exited while starting:` plus a log tail | Usually port 7233 or 8233 is already in use | Run `lsof -nP -iTCP:7233 -iTCP:8233 -sTCP:LISTEN`, then use the port variant in [Start your own dev server](TEMPORAL_WEB.md#start-your-own-dev-server) |
| `STAGE \| Temporal dev server did not become ready` | The started server didn't answer within 20 s. This also happens when `TEMPORAL_ADDRESS` uses a localhost port other than 7233, because the stage starts its server without `--port` | Start the server yourself on the port you configured, or unset `TEMPORAL_ADDRESS` |
| `STAGE \| Worker exited while starting:` plus a log tail | The Worker crashed at startup. A common cause is a live or malformed `STRIPE_API_KEY` in `.env`, which the Worker rejects even in offline mode | Read the tail. Use a `sk_test_` or `rk_test_` key, or remove the key |
| `STAGE \| both live-model keys are configured; choose --model-provider` | Both model keys are set and `AGENT_MODEL_PROVIDER` is blank | Add `--model-provider anthropic` or `--model-provider openai` |
| `STAGE \| --real-model requires ANTHROPIC_API_KEY or OPENAI_API_KEY`, or `STAGE \| anthropic live model requires ANTHROPIC_MODEL` | A live model was requested without its key or model name | Set both in `.env` |
| `STAGE \| --model-provider requires --real-model` | You passed a provider without `--real-model` | Add `--real-model`, or drop `--model-provider` |
| `STAGE \| STRIPE_API_KEY is required for a real refund`, `STAGE \| A live Stripe key was detected and has been rejected`, or `STAGE \| STRIPE_API_KEY must be a Stripe test mode key` | `--real` needs a Stripe test key | Put a `sk_test_` or `rk_test_` key in `.env`, or drop `--real` |
| `STAGE \| Stripe could not create the test payment: ...` or `STAGE \| Stripe could not verify the naive outcome: ...` | Stripe rejected the call or couldn't be reached | Check the key and the network, or run the offline default |
| `STAGE \| timed out waiting for the durable agent loop` | The durable Workflow didn't reach `ready_to_refund` within 90 s. With `--real-model`, a model turn usually failed (see the next rows) | Open the Workflow in Temporal Web, or read `worker.log` in the newest `.demo-state/stage-*` folder |
| `Anthropic returned a permanent error (HTTP 400): ...` | `ANTHROPIC_MODEL` names a model that rejects the forced tool choice this code sends (`tool_choice` type `any`), for example `claude-sonnet-5-5`, `claude-opus-5-5`, or `claude-fable-5-1` | Use `claude-sonnet-4-6` |
| `agent did not reach a decision within the turn budget` (type `AgentLoopExhausted`) | The live model used all 10 turns without calling `submit_decision` | Run it again, and check the request text and the model |
| `agent asked for an unknown tool: ...` or `agent asked an unsupported question: ...` | The live model chose a tool or question the loop doesn't allow. These are non-retryable by design | Run it again |
| `LOG_MODEL_USAGE must be 1, true, yes, 0, false, or no` in `worker.log` | `LOG_MODEL_USAGE` has another value. It fails each live model turn before the paid call, so Temporal's retries make no API calls, and the stage then times out | Set it to `1` or unset it |
| `MODEL USAGE \| no usage log at ...` | `LOG_MODEL_USAGE` was off during the run, or `usage` looked in the wrong folder | Pass the `Stage logs:` path as `--state-dir`, or rerun with `LOG_MODEL_USAGE=1` |
| `Stripe rejected the refund: ...` (type `StripeRefundError`) | Stripe refused the refund, for example `refund-demo start --real` run against the default `pi_dry_run_demo` | Use `refund-demo start --real --seed`, or pass a real test PaymentIntent |
| `Stripe refund call failed (retryable): ...` (type `StripeRetryableError`) in an `issue_refund` attempt's failure | The refund call timed out (3 s to connect, 10 s of silence while reading), lost its connection, or got a 409, 429, or 5xx that Stripe did not mark `Stripe-Should-Retry: false`. Temporal retries it with the same idempotency key, after any `Retry-After` wait | Usually nothing. If every attempt fails, check the network and Stripe's status |
| `The stage view needs rich. Install it with: uv sync --extra tui` | A plain `uv sync` removed the optional Rich extra | Run `uv sync --extra dev --extra tui` |
| `WorkflowAlreadyStartedError` traceback | You reused a `--workflow-id` while that take is still Running | Use a new ID, or run `uv run refund-demo stop <id>` |
| `Could not re-read Temporal.` and `Showing the earlier reading:` in the `WORKER GONE` pane | The history read failed or took longer than 3 s. The counts shown are from before the Worker stopped | Check the Temporal server, then open the Workflow's History tab in Temporal Web |
| A Query in Temporal Web fails or hangs during `WORKER GONE` | Queries need a live Worker | Use the History tab while the Worker is gone |
| `Starting a new Worker. It picks up from Temporal's history...` stays up for several seconds | Temporal may first offer the new task to the killed Worker's sticky queue and wait out its timeout (10 s by default in the Python SDK). A `WorkflowTaskTimedOut` event may appear | Expected; nothing to fix |
| `refund-demo result <id>` hangs | No Worker is polling that Workflow's task queue | For a Workflow started with `refund-demo start`, run `uv run refund-worker`. A stage Workflow uses a private `refund-stage-<token>` queue that only the stage's own Worker polls |
| `THE SYSTEM \| cleanup done, refunded $0.00 of demo charges` | There was no outstanding demo test payment | Not an error |
