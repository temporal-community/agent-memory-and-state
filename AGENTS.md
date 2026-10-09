# Repository guidance for coding agents

## Purpose

This repository is a teaching demo for a 10- to 12-minute talk about agent
memory, state, and durable execution. Preserve the story as carefully as the
code. It uses the README's four kinds of information, in the README's order:

- **Context** (working memory) is what the model has in front of it for the
  current decision; here it is the `working_memory` list, which lives in the
  agent process in Demo 1 and in the Workflow in Demo 2.
- **Long-term memory** is what an agent carries from one run to the next, and
  it lives in a store you own; this demo keeps none, on purpose.
- **Execution state** is where the work stands, and Temporal records it in
  Event History, which lives in the Temporal Service rather than in the
  Worker.
- **Effect state** is whether the refund actually happened, and Stripe, or
  the offline Stripe-like ledger, owns that record.

Execution state and effect state are authoritative: each is an owner's record
that grounds what the application may safely do, and it wins when copies
disagree. Memory is not authoritative, because it says what the agent
believed, not what happened. These are roles, not storage types: an order row
in the application database becomes context once the agent looks it up, and
the order row still wins.

## Narrative invariants

- Nyghtowl starts with a paid python-plushy order. In Stripe test mode, create
  the PaymentIntent before the first refund prompt so `PAID` is a real
  effect-owner record, not stage decoration.
- In Stripe test mode, Demo 1's new agent process must retrieve the
  PaymentIntent and refund list from Stripe. That read must never create a
  refund. In the stage run, only Demo 2 submits a refund.
- In Demo 1, the agent visibly loops: ask whether the package was opened,
  observe the answer, ask what was damaged, observe the answer, look up the
  order and refund history, then choose `issue refund` as its next action. The
  agent process disappears before Stripe is called.
- When Demo 1's agent process dies, its process-local working memory goes with
  it, including Nyghtowl's answers and the loop's next action. Stripe correctly
  keeps `PAID` with no refund, but it does not own the customer intake or the
  loop's progress. Never imply Stripe received or lost a refund request at
  this point.
- Demo 2 runs the same loop as a Temporal Workflow. Customer answers are
  Signals, lookups are Activities, and the next action is Workflow state.
  After the kill, a new Worker picks up the Workflow, and the agent resumes at
  `issue refund` without repeating questions or restarting the loop, then
  says, “Your refund is complete.”
- Do not claim Temporal prevents duplicate refunds by itself. Stripe's
  idempotency support makes the repeated effect call safe. Temporal records
  that the refund step hasn't finished and drives it to completion with
  retries; Stripe, not Temporal, owns whether the refund happened.
- Do not describe Demo 2's run as two refund requests. It is one logical
  refund operation that may need more than one Activity attempt or effect
  call.
- Do not claim that each step runs only once. An Activity that was running
  at the crash has no recorded result, so Temporal runs it again. The intended
  result is “one customer request, possibly two calls, one refund.”
- A restarted application must keep or derive the same Workflow ID and
  surface its status or result. Temporal does not automatically update an
  arbitrary chat session.
- Say “refund complete” only when Stripe returned `succeeded`. Render `pending`
  or any other status literally; an accepted API call is not proof of a
  completed refund.
- General-audience stage copy uses one simple name per role. Demo 1's side is
  the “agent process”: `AGENT PROCESS`, `PROCESS GONE`, `NEW AGENT PROCESS`,
  never “Worker,” because it is not a Temporal Worker. Demo 2's side uses
  `TEMPORAL WORKER`, `WORKER GONE`, `NEW TEMPORAL WORKER`, and “new Worker.”
  Say “new” rather than mixing in “replacement” or “reloaded.” Keep SDK and
  event-history terms in the detailed `refund-demo watch` and inspection
  paths.
- Label scripted parts on screen. Each demo header carries one dim mode line
  (scripted steps; fixed policy or live model; sample lookups; Stripe test mode
  or offline ledger). The reuse of Demo 1's answers and the demo-only wait
  before Stripe, where the Workflow waits for the `release` Signal, are
  labeled where they happen. Never label the offline ledger as just “Stripe”:
  its heading is `OFFLINE LEDGER (Stripe stand-in)`, and `STRIPE (test mode)`
  appears only with `--real`.
- Give each stage frame one cue, carried by the input prompt. It says
  literally what Enter does next (“start”) and matches the frame that follows.
  Stage-mode frames have no footer cue panel.
- The crash cue is the one exception. It reads “Press Enter to submit the
  refund” in both demos so the presenter never says “kill,” and the frame that
  follows must say, in dim text, that the demo stopped the process or Worker
  before the refund reached Stripe.
- A label that says a value was read from Temporal after the kill must be
  backed by an Event History read, as `loop_from_history` does, never by a
  cached Query result. Keep the cached-fallback label distinct.
- Treat `NO REPEATED QUESTIONS`, `NO LOOP RESTART`, and the customer-facing
  result as the primary payoff: contrast what a memory store could bring back
  with what Temporal records, which is the completed observations and the
  loop's next action. Do not make a duplicate refund or an uncertain Stripe effect the
  main payoff. `2 CALLS → 1 REFUND` is supporting evidence about effect safety
  in the manual technical path, and the post-effect idempotency case belongs
  in the manual walkthrough
  (`docs/GUIDE.md#later-loss-after-stripe-accepts-the-refund`). Show call
  counts only when there is more than one call (the retry paths); never show a
  one-call count on the default path.

## Implementation boundaries

- Keep Workflow code deterministic. Network calls, model calls, filesystem
  access, and other nondeterministic work belong in Activities.
- Preserve a stable effect identity across retries. The current implementation
  derives the Stripe idempotency key from the Workflow run identity.
- Keep the stage runner isolated with its private task queue and state
  directory. It must not stop or delete unrelated Workers or user data.
- Offline deterministic mode is the default stage path. `--real` is Stripe test
  mode only, and live Stripe keys must remain rejected.
- Live model mode supports Anthropic and OpenAI. Record an explicit provider in
  Workflow input so new Workers cannot switch providers based on key
  availability.
- Build the Anthropic and OpenAI clients with `max_retries=0` and a timeout
  shorter than the `agent_decide_next_step` start-to-close timeout, and keep
  `stripe.max_network_retries = 0`. The Temporal Activity retry policy is the
  only retry layer, so every retry is visible in Temporal.
- Keep the Stripe refund call's client timeout (`STRIPE_TIMEOUT_SECONDS`: 3 s
  to connect, 10 s to read, per socket operation) shorter than the
  `issue_refund` start-to-close timeout, and keep `issue_refund` heartbeating
  every second while it waits (`_call_with_heartbeats`). A slow call is then
  not taken for a lost Worker, and a hung one fails and retries with the same
  idempotency key. The heartbeat timeout is 15 s, or 3 s on the stage's
  simulated-failure paths.
- Pass `temporal_identity()` to every Temporal client, so each process reports
  `<pid>@refund-demo` (or `TEMPORAL_IDENTITY` verbatim) and the machine's
  hostname never shows in the Temporal Web UI.
- Never print, commit, or expose values from `.env` or API-key environment
  variables.
- Do not run a real-model or Stripe test-mode rehearsal unless the task calls
  for it. Stripe test mode still creates external test objects.

## Changing the Workflow safely

- Workflow code must stay deterministic. A new Worker rebuilds a run by
  replaying its Event History, which means it runs the Workflow code again from
  the top and checks each step against what the history recorded.
- A change to the order or kind of Commands breaks replay of runs that are
  already in flight. Commands come from steps such as starting an Activity,
  starting a timer, or starting a child Workflow. Moving where the Workflow
  waits for a Signal also changes which Commands come next.
- Guard such a change with `workflow.patched("<change-id>")`, so runs that
  started before the change keep the old path. After every run that took the
  old path has finished, delete the old path and replace the guard with
  `workflow.deprecate_patch("<change-id>")`. Remove that call once every run
  that recorded the patch has finished. Worker Versioning is the other option:
  it can pin runs that started on the old code to Workers that still run that
  code.
- Run `make test` before merging. It includes `tests/test_replay.py`, which
  replays the saved history in `tests/histories/stage_offline.json` against
  the current Workflow code.
- When a change is intentional and patched, the existing
  `tests/histories/stage_offline.json` must still replay, which shows that the
  patch works. To cover the new path too, regenerate the history as the
  docstring of `tests/test_replay.py` describes. If runs recorded with the old
  code must still replay, keep the old history file under a new name and have
  the test replay both. Replace it outright only when you mean to drop support
  for those runs.

## Important paths

- `src/refund_agent/stage.py`: guided single-terminal talk path
- `src/refund_agent/tui.py`: technical and general-audience panels
- `src/refund_agent/workflow.py`: Demo 2's agent loop (the
  `RefundApprovalAgent` Workflow) and its Activity boundary
- `src/refund_agent/activities/`: the Activities, split by role. `model.py` holds
  the model turn and usage logging, `tools.py` the three lookups, `refund.py`
  the refund side effect and its idempotency key, and `view.py` the display
  helpers. Activity names must not change: Event History and
  `tests/test_replay.py` refer to them by name.
- `src/refund_agent/naive_refund.py`: Demo 1's agent process, the comparison
  without Temporal
- `src/refund_agent/fake_stripe.py`: the offline ledger (the Stripe stand-in)
  and its call counter
- `README.md`: what the demo shows, how to run it, the four kinds of
  information and who owns each fact (`#memory-and-execution-state`),
  architecture, cost, and how other approaches compare
- `docs/GUIDE.md`: stage flags, Web UI checks, expected output, the manual
  walkthrough, the authorization companion demo, and every error
- `docs/HISTORY_GROWTH.md`: Event History growth, claim check, and
  Continue-As-New
- `docs/TALK_10_MIN.md`: canonical talk timing, wording, and controls

## Verification

Install development and terminal dependencies with `make setup`, which runs:

```bash
uv sync --extra dev --extra tui
```

Running `uv sync` without those extras removes both, including Rich for the
stage view.

Before committing a change, run `make test`, `make lint`, and
`make typecheck`, or:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy
```

CI (`.github/workflows/ci.yml`) runs the same lint, type check, and tests on
every push to `main` and on every pull request.

Changes to stage copy or control flow also require a complete offline rehearsal
(`make run`):

```bash
uv run refund-demo stage
```

Verify the content is visible at the intended terminal size, not merely present
in the Rich render tree. The smallest stage terminal is 80 columns, and the
recording width is 100 to 120 columns (`tests/test_tui.py` checks 80 and 100).
Each pane line should fit one row at both 80 and 100 columns, so test the
longest line at those widths, not only at 128, the width
`scripts/render_demo_frames.py` renders at.

## Documentation and generated media

- Each doc owns its topics and has its own reader. Say each point once, in the
  doc that owns it, and link there from elsewhere. Add to the owner rather
  than starting a new doc.
  - `README.md` is for people trying the demo and their coding agents. It owns
    the concepts, architecture, cost, how other approaches compare, gotchas,
    and what the demo is not. It uses no presenter language.
  - `docs/GUIDE.md` is for whoever runs or presents the demo. It owns the
    stage flags, Web UI checks, expected output, the manual walkthrough, the
    authorization companion demo, and troubleshooting.
  - `docs/TALK_10_MIN.md` is the presenter's run of show, which the presenter
    only glances at while speaking. It owns the talk's timing, wording, and
    controls.
  - `docs/HISTORY_GROWTH.md` is for readers who plan to run long agents on
    Temporal. It owns Event History growth, its limits, the claim check, and
    Continue-As-New.
- These wording rules apply to every doc:
  - Temporal is not a memory store. It records execution state in Event
    History, so say Temporal “records,” never “remembers.”
  - Stripe, or the offline ledger, owns whether the refund happened. Never say
    Temporal tracks the refund's state.
  - Give cost in tokens and dollars together, and never make “$0” a headline.
    Lead with why the demos differ: starting over pays for every model call
    again, replay doesn't pay again for finished calls, and only a call in
    flight at a crash can run twice. Show each demo's numbers and the estimate
    at scale, not a total for a full run of both demos.
  - Don't write “proves,” and don't call the agent, its loop, or the Worker
    “plain.”
  - Don't write “exactly once” or claim a step runs only once; the reason is
    under Narrative invariants.
- Keep `README.md`, `docs/GUIDE.md`, and `docs/TALK_10_MIN.md` aligned when
  the story or stage flow changes. Stage copy appears in the README's key
  lines (`#same-crash-two-outcomes`), the guide's transcript
  (`#stage-transcript`), and the talk's cue table.
- A few facts are repeated on purpose, so change every copy: the measured cost
  (README `#cost-to-run`, the top of the guide's `#run-the-stage`, and the
  talk's cost beat) and the README's three Troubleshooting rows (the first
  rows of the guide's `#troubleshooting`).
- Each `Makefile` recipe is the raw command shown beside it in the README's
  Make targets table. Change both together, and keep `make reset` from
  deleting files or stopping servers.
- Update the README's `Last verified` line only for runs that actually
  happened.
- `scripts/render_demo_frames.py` generates deterministic HTML frames. Generated
  raster screenshots, GIFs, and videos are separate artifacts; do not claim
  they were updated unless they were regenerated and visually inspected.
- Do not commit `.env`, `.demo-state`, local Temporal databases, stage logs, or
  temporary rendering directories.
