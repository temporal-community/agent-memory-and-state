# Agent memory and state

A small teaching demo for a Python meetup talk on durable execution for agents.
Everything here is plain Python with no agent framework.

Autonomous agents fail in a way supervised ones don't: they lose track of where
the work is and repeat real effects, an approval that never resumes, a refund
issued twice. Context and memory don't fix that, because memory records what the
agent knows, not the facts other systems own. These demos show what does, and
who owns each piece.

In a supervised agent, the human is the durability layer. They notice the stuck
approval, the duplicate refund, and step in. Autonomy removes the human, and
nothing takes over that job unless you build it. That job is state: where the
work stands and who may act, owned by a system of record outside the model, not
held in the agent's memory.

- **naive-refund** (Demo 1): the refund task built the naive way, with no durable
  execution. On a restart, context and memory come back for free, but the lost
  process-local state makes it refund a second time.
- **the refund agent** (Demo 2): the same task made durable. It retrieves what it
  needs, reasons, decides, and issues a Stripe refund in test mode, and it
  survives the same restart and refunds exactly once.
- **permission-chat** (alternative): the authorization companion. The same
  memory-and-state layers around a GitHub push permission, whose system of
  record is the auth system, not Temporal.

## Memory and state

Both memory and state can be durable, so durability is not the difference. Each
is authoritative, but over a different domain: memory over what the agent
knows, state over a fact another system owns. Getting that boundary wrong,
trusting memory where another system owns the fact, is what breaks autonomous
agents. State is the version everything else reconciles to.

**MEMORY** is what the agent knows. It is often the only account of things no
other system records: its plan, that the customer sounded upset. What it cannot
do is vouch for provenance, so a memory store cannot tell you which of its
contents were witnessed and which were inferred. It comes in two timescales, and
both are memory:

- **Working memory** is what the model works with this turn. The context window
  is the buffer that holds it; the window only holds, so the selecting and
  refreshing (context management) is what supplies the working-memory role.
- **Long-term memory** carries across sessions: episodic (what happened) and
  semantic (facts as the agent recalls them).

**STATE** is the owner's record of a fact it owns: a system of record outside the
agent. Being that record does not mean being right at every instant (a record can
lag the world). It means being the version everything else reconciles to. Every
fact an autonomous agent must be able to trust has such an owner, and there is
more than one:

- **Execution state** answers "where does the work stand." Owner: the
  durable-execution platform (Temporal).
- **Effect state** answers "did the real effect commit." Owner: the service that
  did the thing (Stripe, GitHub).
- **Authorization state** answers "may this agent act." Owner: the auth system
  (an OAuth token, a policy engine, a grants table).
- **Domain state** answers "what are the business facts." Owner: your database.

The everyday test for which is which: if something outside the agent owns whether
it is true, it is that owner's fact, and it belongs in their record. The trap is the
band in between: process-local state, the progress and the "I already refunded"
the agent holds in the process. It is a belief that thinks it is a record, and it
is gone on restart.

When the agent's copy and the owner's record disagree, the record wins. Trusting
memory where you needed the owner of record is the duplicate refund (Demo 1) and
acting on a revoked grant (the permission demo). The idempotency beat in Demo 2 is two owners
meeting: a recorded call is not proof the money moved, Temporal owns the attempt
and Stripe owns the outcome. The workflow's identity becomes the idempotency key,
so the attempt and the effect share one name. Durable execution does not create
exactly-once effects; it lets a retry ask instead of guess.

A note on a common framing. You may have seen memory and state cut the other way:
state is the ephemeral now, memory is the durable history. That is a lifespan
cut, and it does not fit here. A workflow's execution state lives for as long as
the execution runs, kept durable across restarts by replay, then retained as
history for the namespace retention period and deleted after. That is neither ephemeral like
a variable nor long-lived like a database, and the period is a config setting,
not a property of the category, so lifespan is not even binary. It cannot be the
cut. What separates memory and state is authority: who reconciles to whom when
they disagree.

## Setup

Prerequisites: Python 3.11 or newer, the
[Temporal CLI](https://docs.temporal.io/cli), and optionally
[uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev --extra tui
```

The `dev` extra adds the test and lint tools. The `tui` extra adds rich for the
two-panel view.

Copy `.env.example` to `.env` and fill in what you use. The Worker and the CLI
load `.env` automatically at startup. Values already exported in your shell win
over the file, and nothing is ever loaded into deterministic Workflow code.

## Environment and modes

Two independent switches decide how real the run is.

- **The model.** If `OPENAI_API_KEY` is present, the agent uses the real model
  named by `OPENAI_MODEL` (for example `gpt-5.6-luna`). With no key, a `--dry-run`
  uses an offline deterministic policy, and a real run fails loudly.
- **The refund.** `--dry-run` writes to an offline Stripe-like ledger under
  `.demo-state` and needs no key. `--real` calls Stripe in test mode and
  requires a `sk_test_` or `rk_test_` `STRIPE_API_KEY`. Live keys are rejected.

So `--dry-run` with an OpenAI key set gives real model reasoning with an offline
refund, which is the simplest way to run the whole loop locally.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | When set, the agent reasons with a real model. |
| `OPENAI_MODEL` | The model id, required when a key is present. |
| `STRIPE_API_KEY` | Required only for `--real`. Test mode keys only. |
| `EFFECT_RESTART_WINDOW_SECONDS` | Holds the uncertain window open on the Worker, for the effect beat. |
| `TEMPORAL_ADDRESS` `TEMPORAL_NAMESPACE` `TEMPORAL_TASK_QUEUE` | Temporal connection. |
| `DEMO_STATE_DIR` | Where local state and the offline ledger live. |

## Demo 1: the naive refund agent (no durable execution)

The same refund task as Demo 2, built the naive way: everything, including the
record of what it already did, lives in the process. Run it as one interactive
two-pane window (needs the `tui` extra):

```bash
uv run naive-refund
```

The left pane is THE AGENT (in process): context, memory, and process-local
state, the ghost band the restart loses.
The right pane is THE RECORD, the durable ledger of committed refunds. Drive it:

- Press Enter (or type `refund`) to process the refund. The agent decides,
  refunds, and records completion; the ledger shows one refund.
- Type `restart` to restart the worker, the everyday event: a deploy, a rolling
  restart, an eviction, an OOM. THE AGENT pane goes to LOST: its in-memory state
  is gone, including whether it already refunded. The ledger still shows one.
- Press Enter again. Context and memory come back for free (they are
  recomputable), but with no durable record that it refunded, it refunds a
  second time and the ledger shows a DUPLICATE REFUND.
- `reset` starts over, `quit` exits.

The point: knowledge is recomputable, so losing it on a restart is cheap.
Process-local state is not, and losing it is what refunds the customer twice. This is
not an exotic crash: it is what happens on any deploy or eviction mid-task.
Demo 2 is the same agent with its execution state in a system of record
(Temporal), where the same restart resolves to one refund.

For a scripted version with a real process restart (handy for recording or CI):
`naive-refund reset`, then `naive-refund refund --order 1234 --exit-after-effect`,
then `naive-refund refund --order 1234`, then `naive-refund ledger`.

## Demo 2: the refund agent

The agent is a loop. Each turn the model looks at what it knows, plans, and
either calls a tool or decides. Tools are the retrieval it does live. It runs
until it approves, escalates to a human, or denies.

### Start Temporal and the Worker

Terminal 1, the local dev server with persistent state:

```bash
mkdir -p .demo-state
temporal server start-dev --db-filename .demo-state/temporal.db
```

The Temporal UI is at [http://localhost:8233](http://localhost:8233).

If you already have a Temporal server on `:7233` (for example a Docker Temporal),
this command fails with `address already in use`. That is fine: skip it and use
the running server. The demo connects to `:7233` by default.

Terminal 2, the Worker. Restart this whenever you change the code, because
Python does not reload a running Worker.

```bash
uv run refund-worker
```

### Run it end to end (real Stripe, two panes)

The whole stage flow: real Stripe test mode with the live two-pane view. Needs
`STRIPE_API_KEY=sk_test_...` in `.env`. Four terminals:

```bash
# Terminal 1: Temporal
temporal server start-dev --db-filename .demo-state/temporal.db

# Terminal 2: the Worker, with a restart window open for the effect beat
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker

# Terminal 3: the two-pane view
uv run refund-demo watch stripe-refund-demo

# Terminal 4: drive it
uv run refund-demo start --real --seed --workflow-id stripe-refund-demo
uv run refund-demo approve stripe-refund-demo "approved"   # only if it escalates
# watch Terminal 2 for: restart window open 30s; run: refund-demo kill-worker
uv run refund-demo kill-worker                             # THE AGENT goes LOST
uv run refund-demo inspect stripe-refund-demo
# in Terminal 2, rerun the same command to recover the Worker; it drives attempt 2
uv run refund-demo result stripe-refund-demo               # waits for the Worker, then one refund
uv run refund-demo cleanup                                 # net Stripe to zero
```

In real mode the watch panel shows the refund itself: its id, the call count, and
that it stays one refund with no duplicate. Stripe is still the system of record,
so the dashboard is where you confirm the money actually moved. To rehearse
offline, drop the restart window and swap `--real --seed` for `--dry-run`. The
sections below break down each step.

### Run a refund

Terminal 3:

```bash
uv run refund-demo start --dry-run --workflow-id demo-refund
uv run refund-demo result demo-refund
```

Watch Terminal 2. The Worker prints CONTEXT, then each MODEL REASONING turn and
the MEMORY it retrieves, then the decision and EXECUTION STATE phases. With an
OpenAI key set, the decision source reads `openai:<model>`; with no key it reads
`canned`.

If the agent escalates, it waits for a human. Approve it, with an optional note,
then read the result:

```bash
uv run refund-demo approve demo-refund "verified defect, approving"
uv run refund-demo result demo-refund
```

To stop a Workflow instead of approving it (say one you do not want to release),
`uv run refund-demo stop demo-refund` terminates it. If it seeded a real charge,
follow with `refund-demo cleanup`.

A clean, low-value refund the agent tends to clear on its own. A larger or
riskier one it investigates further and escalates. Use `--amount-cents` to move
between those paths, for example `--amount-cents 15000` to push it toward
escalation.

### The effect beat: losing the connection around the refund

This is the payoff, and it is the realistic failure. Right after Stripe accepts
the refund, before the Activity can report it completed, the worker loses its
connection or is restarted (a deploy, a network blip, a timeout). Now nothing in
the process can tell you whether the money moved. Two things make this beat work,
and both are easy to miss: the Worker must run with a restart window open, and
you have to kill it during that window. This runs against real Stripe test mode,
so you watch one refund resolve in the dashboard despite two attempts, and it is
self-contained (its own Workflow, no earlier step needed). Stop the Worker, then
start it with the window held open:

```bash
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker
```

Start a seeded real refund and let it reach the refund step. Approve if it
escalates:

```bash
uv run refund-demo start --real --seed --workflow-id demo-restart
uv run refund-demo approve demo-restart "approved"   # only if it escalates
```

Wait for the Worker to print the cue:

```text
THE SYSTEM      | refund accepted at Stripe: re_... (stripe-test, attempt 1)
EXECUTION STATE | restart window open 30s; run: refund-demo kill-worker
```

At that moment the refund has been accepted but the Activity has not reported
completion. Simulate the lost connection by hard-killing the Worker, the bluntest
version of a restart or partition at the worst possible moment:

```bash
uv run refund-demo kill-worker
```

Inspect the ambiguous point with no Worker running. The refund is already created
at Stripe, but Temporal does not yet know the Activity result:

```bash
uv run refund-demo inspect demo-restart
```

Recover the Worker by restarting it: rerun the same `refund-worker` command, in
its own terminal. `kill-worker` only kills the process; bringing it back is a
separate command you run. The returning Worker is what drives the run: after the
heartbeat timeout Temporal runs attempt 2, which reuses the same idempotency key
derived from the workflow run's durable identity, so Stripe returns the original
refund and it resolves to one. `result` does not drive anything; it waits for a
Worker to finish the run and then prints the outcome, so run it once the Worker
is back:

```bash
EFFECT_RESTART_WINDOW_SECONDS=30 uv run refund-worker
uv run refund-demo result demo-restart
uv run refund-demo inspect demo-restart
```

The final inspect shows `issue_refund` completed on attempt 2, two calls with
the same key, and one unique refund. A recorded call is not proof the money
moved: Temporal owns the attempt, Stripe owns the outcome. The workflow's
identity becomes the idempotency key, so the attempt and the effect share one
name. Durable execution does not create exactly-once effects; it lets a retry
ask instead of guess.

Keep the window under 60, the `issue_refund` start_to_close timeout, so a
Worker you do not restart cannot time out its own attempt. You have up to the
schedule_to_close budget (10 minutes) to bring a Worker back before the run gives
up, so a slow restart on stage still resumes to one refund. To rehearse offline,
swap `--real --seed` for `--dry-run` and the same beat runs against the local
ledger with no Stripe calls. After a real run, reconcile the seeded charge with
`uv run refund-demo cleanup`.

Two things that trip people up. `result` is a read, not a driver: it blocks until
a Worker has run the Workflow to completion, so if it hangs, no Worker is polling
and you just need to start one. And use a fresh `--workflow-id` for each run: do
not resume a run started under older code or before a Temporal restart, because
replaying it can wedge. Terminate a stale run with `refund-demo stop <id>` and
start a new id.

### The clean case: replay skips a completed step

The effect beat above stages the hard case, where the crash lands mid-call and
the idempotency key is what prevents the duplicate. The common case is simpler
and worth showing: once a step has completed and been recorded, a restart
replays it from history and does not run it again. No key needed, because the
step never repeats.

Run a plain Worker (no restart window) and start a run that holds open right
after the refund is recorded:

```bash
uv run refund-worker
uv run refund-demo start --dry-run --hold --workflow-id demo-hold
```

The Worker prints `refund recorded; holding for release`. Kill and restart it:

```bash
uv run refund-demo kill-worker
uv run refund-worker
```

Watch or inspect while it is held: `issue_refund` shows one call, attempt 1. The
restart did not retry it, because the completed step was replayed from history,
not repeated. Release the run to finish:

```bash
uv run refund-demo release demo-hold
uv run refund-demo result demo-hold
```

State stops the redo when the step is recorded; the idempotency key is the
backstop for the gap where it is not. This runs on the local ledger; swap
`--dry-run` for `--real --seed` to hold a real refund open, then `cleanup`.

### The two-panel view

In its own terminal, watch THE AGENT beside THE SYSTEM OF RECORD:

```bash
uv run refund-demo watch demo-restart
```

The left panel is the Worker's in-process view: context, the steps it retrieved
this run, and the decision. It reads LOST the moment the Worker is killed. When a
Worker returns and resumes the effect, the panel repopulates from the recovered
steps, so you watch it come back. The right panel is status, the recorded steps,
the pending Activity and its attempt, and the refund: its id, how many calls the
idempotency key took, and that it stays one refund with no duplicate. Both read
from Temporal and the ledger, so they survive the restart. Make the terminal
fullscreen for stage. Press Ctrl+C to exit.

### Real Stripe test mode

Put your Stripe test key in `.env` (it is loaded automatically):

```text
STRIPE_API_KEY=sk_test_...
```

A refund needs a paid PaymentIntent to refund against. The simplest path seeds
one and refunds it in a single command, so there is no id to copy:

```bash
uv run refund-demo start --real --seed --workflow-id stripe-refund-demo
uv run refund-demo approve stripe-refund-demo "approved"   # only if it escalates
uv run refund-demo result stripe-refund-demo
```

`--seed` creates a succeeded test charge (with the pm_card_visa test card) and
runs the refund against it, so the payment and refund net to zero. The refund
appears in your Stripe test dashboard. Stripe receives the same idempotency key
on a retry and returns the original refund, so a restart still resolves to one
refund. The demo never creates a live charge, is test mode only, and is not a
Stripe tutorial.

To reset the test account between rehearsals, refund any leftover demo charges:

```bash
uv run refund-demo cleanup
```

If you want to seed and refund as separate steps, `refund-demo seed-payment`
prints a PaymentIntent id you can pass to `start --real --payment-intent`.

### Event history

```bash
temporal workflow show --workflow-id demo-restart
temporal workflow describe --workflow-id demo-restart
```

Point at the `agent_step` and tool Activities (the loop), the
`WorkflowExecutionSignaled` approve when it escalated, and the `issue_refund`
started event with `attempt: 2` after the restart. A recorded call is not proof
the money moved. The shared idempotency key lets a retry ask instead of guess.

## Alternative demo: authorization state

Demos 1 and 2 are both about where the work stands. That is execution state,
owned by Temporal in Demo 2 and only a process-local ghost in Demo 1. This
companion demo is about the other kind of state a real agent leans on:
authorization state, may this agent act. Its system of record is the auth system
(an OAuth token, a policy engine, a grants table), not Temporal. The same
memory-and-state layers, a different owner.

```bash
uv run permission-chat --panes     # two-pane view (needs the tui extra)
uv run permission-chat             # or a plain REPL, no extra needed
```

The question on screen is "may the agent push to my repo." Say "you can push"
to grant it, "push" to make it act. Toggle where the grant lives and watch the
answer change:

- With only context, the grant holds for this session and vanishes on `:new`.
- With `:remember on`, memory carries the grant across sessions, but memory is a
  recollection: `:revoke` in the real world and memory still says yes, so the
  agent pushes on a permission that no longer exists.
- With `:state on`, the auth system is authoritative. Revoke it there and the
  agent refuses, because it checks the record instead of its memory.

The lesson mirrors the refund demos: a permission you must be able to trust
belongs in its system of record (here the auth system), not in the model's
memory. `:help` lists every command.

## Tests and checks

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

## Scope

Not production. No auth, no database, no multi-agent orchestration, no web
application, no operational hardening. The job is to make context, memory,
execution state, an autonomous loop, a durable wait, an uncertain effect, and
idempotent recovery visible in one short arc.

One distinction the demo leans on: execution state (where the work stands) and
memory (what the agent knows) are different concerns. It shows Temporal capturing
and replaying the execution state, the steps the agent took. It does not take on
how the agent's memory is stored or managed, and where durable execution and
agent memory best fit together is an open question.

## Acknowledgments

Thanks to Cecil for the review that shaped how this repo frames memory and state.
