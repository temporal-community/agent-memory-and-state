# Manual refund demo

The recommended talk path is the guided one-window runner:

```bash
uv run refund-demo stage
```

This guide exposes every process and recovery step separately. Use it for
development, rehearsal, debugging, or a longer technical walkthrough.

The guided stage makes an autonomous loop visible. The agent chooses two
questions, observes the answers, performs two lookups, and chooses `issue
refund`. On the naive side that position exists only in the Worker. On the
durable side, answers are Signals, lookups are Activities, and the next action
is Workflow state. A replacement Worker resumes without repeating questions.

## Setup

Prerequisites:

- Python 3.11 or newer
- [Temporal CLI](https://docs.temporal.io/cli)
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync --extra dev --extra tui
```

Copy `.env.example` to `.env` and fill in only the services you intend to use.
The Worker and CLI load `.env` automatically. Exported shell values take
precedence, and configuration is never loaded into deterministic Workflow code.

## Model and effect modes

The model and refund effect are independent:

- With `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`, the agent can use Claude.
- With `OPENAI_API_KEY` and `OPENAI_MODEL`, the agent can use OpenAI.
- `AGENT_MODEL_PROVIDER` selects `anthropic` or `openai`; the CLI
  `--model-provider` option records that choice in Workflow input.
- Without a configured live-model provider, `--dry-run` uses the deterministic
  policy.
- `--dry-run` writes to an offline Stripe-like ledger under `.demo-state`.
- `--real` calls Stripe test mode and requires a `sk_test_` or `rk_test_` key.
- The guided `--real` runner creates the paid test PaymentIntent before the
  first refund prompt, then refunds that same payment in the durable half.
- Live Stripe keys are rejected.

| Variable | Purpose |
| --- | --- |
| `AGENT_MODEL_PROVIDER` | Selects `anthropic` or `openai` when using a live model |
| `ANTHROPIC_API_KEY` | Enables Claude model reasoning |
| `ANTHROPIC_MODEL` | Claude model id used when Anthropic is selected |
| `OPENAI_API_KEY` | Enables live model reasoning |
| `OPENAI_MODEL` | Model id used when a key is present |
| `STRIPE_API_KEY` | Stripe test key required by `--real` |
| `EFFECT_RESTART_WINDOW_SECONDS` | Holds the uncertain boundary open for a Worker kill |
| `TEMPORAL_ADDRESS` | Temporal endpoint, default `localhost:7233` |
| `TEMPORAL_NAMESPACE` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | Worker task queue |
| `DEMO_STATE_DIR` | Offline ledger, views, logs, and local state |

Test live model behavior without Stripe first:

```bash
uv run refund-demo stage --real-model --model-provider anthropic
```

The stage fixture always represents order 1234, an $80 plush python that is
explicitly eligible for a refund without a physical return. A request for a
different item can correctly be denied by a live model. On denial, the stage
shows the model's rationale and confirms that no refund was issued. If `--real`
created a Stripe test payment before that denial, run
`uv run refund-demo cleanup` to reconcile the test charge.

## Start Temporal and the Worker

Terminal 1:

```bash
mkdir -p .demo-state
temporal server start-dev --db-filename .demo-state/temporal.db
```

Temporal Web is at <http://localhost:8233>.

If another Temporal server already listens on `:7233`, use that server and skip
the start command.

Terminal 2:

```bash
uv run refund-worker
```

Python does not reload a running Worker. Restart it after changing Workflow or
Activity code.

## Demo 1: uncoordinated progress

Run the naive two-pane agent:

```bash
uv run naive-refund
```

The left pane shows the process-local agent loop. The right pane shows the paid
order and Stripe's refund state.

1. Press Enter or type `refund`. The standalone view condenses the agent's two
   questions, two answers, and two lookups into its completed-loop checklist;
   the guided stage asks the questions one at a time.
2. Type `restart`. The process-local answers and loop position disappear.
   Stripe still says paid with no refund.
3. Ask, `What happened to my refund?`
4. The replacement agent checks Stripe and answers correctly, but the customer
   must restart the return because there is no active execution to resume.

With `refund-demo stage --real`, step 4 retrieves the test PaymentIntent and its
refund list directly from Stripe inside a fresh naive-agent subprocess. The
question crosses stdin and the result crosses structured stdout, so this is a
real process boundary rather than a UI-only transition. It does not create a
refund. The only stage refund submission happens later in the Temporal-backed
run.

This is durable effect state beside lost working memory and lost application
work. A persisted memory layer could restore the answers, but neither those
facts nor Stripe's record would own the active loop position. A custom database
state machine and recovery job could supply that missing execution state;
Temporal is the implementation shown on the durable side.

Use `reset` to start over and `quit` to exit.

For the same scripted autonomous loop and pre-effect pause used by the stage
runner:

```bash
uv run naive-refund reset
uv run naive-refund refund --order 1234 --interactive-loop --hold-before-effect
```

The command asks its questions on stdin, emits each `AGENT STEP`, then waits
after choosing the refund. No refund is written to the ledger. The older
post-effect boundary is still available for technical comparison:

```bash
uv run naive-refund refund --order 1234 --exit-after-effect
uv run naive-refund ledger
```

## Demo 2: manual multi-terminal path

The complete real Stripe path uses four terminals:

```bash
# Terminal 1: Temporal
temporal server start-dev --db-filename .demo-state/temporal.db

# Terminal 2: Worker with the uncertain boundary held open
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker

# Terminal 3: two-pane view
uv run refund-demo watch stripe-refund-demo

# Terminal 4: drive the Workflow
uv run refund-demo start --real --seed --workflow-id stripe-refund-demo
uv run refund-demo approve stripe-refund-demo "approved"   # if it escalates
uv run refund-demo kill-worker
uv run refund-demo inspect stripe-refund-demo

# Terminal 2: recover the Worker and drive attempt 2
uv run refund-worker

# Terminal 4: wait for the result and reconcile the test charge
uv run refund-demo result stripe-refund-demo
uv run refund-demo cleanup
```

To rehearse offline, remove the restart window and replace `--real --seed` with
`--dry-run`.

## Run a normal refund

```bash
uv run refund-demo start --dry-run --workflow-id demo-refund
uv run refund-demo result demo-refund
```

The Worker prints the request context, each model-reasoning turn, retrieved
memory, the decision, and execution-state transitions.

If the agent escalates:

```bash
uv run refund-demo approve demo-refund "verified defect, approving"
uv run refund-demo result demo-refund
```

A low-value request tends to approve automatically. Use a larger amount such as
`--amount-cents 15000` to push the deterministic policy toward escalation.

Terminate a Workflow you do not want to release with:

```bash
uv run refund-demo stop demo-refund
```

## The uncertain-effect beat

This is the mechanical core of the durability payoff.

The failure lands after Stripe accepts the refund but before the Activity can
report completion. The process cannot know whether money moved. Temporal owns
the attempt, Stripe owns the effect, and the retry uses one idempotency key.
Temporal does not turn the two records into one database transaction; it gives
the uncertain attempt a durable recovery point and stable identity.

Stripe's idempotency support is what keeps a repeated call from creating a
second refund. Temporal remembers that the step is unresolved, arranges the
retry after the Worker disappears, and records the result so a reloaded agent
can reconnect to the same work. The application must retain or derive the same
Workflow ID when that agent reloads.

Start the Worker with a visible restart window:

```bash
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker
```

Start a seeded Stripe test refund:

```bash
uv run refund-demo start --real --seed --workflow-id demo-restart
uv run refund-demo approve demo-restart "approved"   # if it escalates
```

Wait for:

```text
THE SYSTEM      | refund accepted at Stripe: re_... (stripe-test, attempt 1)
EXECUTION STATE | restart window open 30s; run: refund-demo kill-worker
```

Kill the Worker:

```bash
uv run refund-demo kill-worker
```

Inspect the ambiguous boundary:

```bash
uv run refund-demo inspect demo-restart
```

Stripe already has the refund, while Temporal does not yet have a completed
Activity result.

Restart the Worker in its own terminal, then wait for the result:

```bash
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker
uv run refund-demo result demo-restart
uv run refund-demo inspect demo-restart
```

The final inspection shows:

- `issue_refund` completed on attempt 2
- two calls used the same idempotency key
- one unique refund exists

Keep the restart window under the normal 60-second Activity start-to-close
timeout. The schedule-to-close budget is 10 minutes, so the Worker can take
longer to return without losing the run.

For an offline rehearsal, replace `--real --seed` with `--dry-run`.

After a real run:

```bash
uv run refund-demo cleanup
```

## The clean replay case

The uncertain beat needs idempotency because the first call may have committed
without a recorded Activity result. The common case is simpler: once a step
completes and is recorded, replay returns its result without rerunning it.

Start a plain Worker and hold the Workflow after the refund:

```bash
uv run refund-worker
uv run refund-demo start --dry-run --hold --workflow-id demo-hold
```

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

Replay prevented the completed step from running again. The idempotency key is
the backstop only for the boundary where the result was not recorded.

## Two-panel view

```bash
uv run refund-demo watch demo-restart
```

The left panel is the Worker's in-process decision view:

- current context
- retrieved domain facts copied into working memory
- the decision

It reads `LOST` when the Worker disappears and repopulates from replay when a
replacement Worker resumes.

The right panel separates:

- execution state owned by Temporal
- effect state owned by Stripe or the offline ledger
- pending Activity attempt
- refund id and call count
- unique refund count

Make the terminal fullscreen for a talk. Press Ctrl+C to exit.

## Stripe test mode

Put a Stripe test key in `.env`:

```text
STRIPE_API_KEY=sk_test_...
```

Seed a succeeded test charge and refund it:

```bash
uv run refund-demo start --real --seed --workflow-id stripe-refund-demo
uv run refund-demo approve stripe-refund-demo "approved"   # if it escalates
uv run refund-demo result stripe-refund-demo
```

The demo uses Stripe test mode only. It never creates a live charge and rejects
live keys.

Clean up leftover seeded charges:

```bash
uv run refund-demo cleanup
```

## Event history

```bash
temporal workflow show --workflow-id demo-restart
temporal workflow describe --workflow-id demo-restart
```

Useful events include:

- model and tool Activities from the bounded loop
- `WorkflowExecutionSignaled` when a human approves
- `issue_refund` attempt 2 after Worker recovery

## Recovery notes

- `result` reads and waits. It does not drive the Workflow. If it hangs, confirm
  that a Worker is polling.
- Use a fresh Workflow id for each run.
- Do not resume a run created under incompatible older Workflow code.
- Terminate a stale run with `refund-demo stop <id>`.
- Use `refund-demo cleanup` after Stripe test rehearsals.
