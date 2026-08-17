# Repository guidance for coding agents

## Purpose

This repository is a teaching demo for a ten-minute talk about agent memory,
authoritative state, and durable execution. Preserve the story as carefully as
the code:

- Context is what the model sees for a decision.
- Memory is retained or retrieved information the agent reasons with.
- Authoritative state is an owner's record that grounds what the application
  may safely do.
- Temporal owns execution progress. Stripe, or the offline Stripe-like ledger,
  owns the refund outcome.

These are operational roles, not mutually exclusive storage types. A domain
record can become working memory when retrieved and context when shown to the
model.

## Narrative invariants

- The durable customer asks once. After the Worker is replaced, the reloaded
  agent reconnects to the same Workflow and says, “Your refund is complete.”
- The naive refund system retains an authoritative successful-refund record.
  The replacement agent may query it and answer correctly after the customer
  asks for status. Never imply that the effect fact disappeared or was
  unavailable.
- The naive failure is manual reconciliation: nothing durable remembers that
  the interrupted customer request is still waiting for an answer. The customer
  must return and trigger a new check.
- Do not claim Temporal prevents duplicate refunds by itself. Stripe's
  idempotency support makes the repeated effect call safe; Temporal remembers
  that an unresolved step needs recovery and drives it to completion.
- Do not describe the durable run as two refund requests. It is one logical
  refund operation that may require more than one Activity attempt or effect
  call.
- Do not claim exactly-once execution. The intended result is “one customer
  request, possibly two calls, one refund.”
- A reloaded application must retain or derive the same Workflow ID and surface
  its status or result. Temporal does not automatically update an arbitrary
  chat session.
- General-audience stage copy should use plain language such as “Worker gone,”
  “replacement Worker,” and “reloaded agent.” Keep SDK and event-history terms
  in the detailed `refund-demo watch` and inspection paths.
- Do not make a duplicate refund the naive stage payoff. A competent replacement
  agent can query the authoritative refund system. Contrast that customer-driven
  reconciliation with Temporal resuming unfinished application work.

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
  Workflow input so replacement Workers cannot switch providers based on key
  availability.
- Never print, commit, or expose values from `.env` or API-key environment
  variables.
- Do not run a real-model or Stripe test-mode rehearsal unless the task calls
  for it. Stripe test mode still creates external test objects.

## Important paths

- `src/refund_agent/stage.py`: guided single-terminal talk path
- `src/refund_agent/tui.py`: technical and general-audience panels
- `src/refund_agent/workflow.py`: durable agent loop and Activity boundary
- `src/refund_agent/activities.py`: model, tool, and refund side effects
- `src/refund_agent/naive_refund.py`: uncoordinated comparison
- `src/refund_agent/fake_stripe.py`: offline effect owner and call counter
- `docs/TALK_10_MIN.md`: canonical talk timing, wording, and controls
- `docs/CONCEPTS.md`: terminology and ownership model
- `docs/REFUND_DEMO.md`: manual technical walkthrough

## Verification

Install development and terminal dependencies with:

```bash
uv sync --extra dev --extra tui
```

Before committing a change, run:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

Changes to stage copy or control flow also require a complete offline rehearsal:

```bash
uv run refund-demo stage
```

Verify the content is visible at the intended terminal size, not merely present
in the Rich render tree.

## Documentation and generated media

- Keep `README.md`, `docs/TALK_10_MIN.md`, `docs/CONCEPTS.md`, and
  `docs/REFUND_DEMO.md` aligned when the story or stage flow changes.
- `scripts/render_demo_frames.py` generates deterministic HTML frames. Generated
  raster screenshots, GIFs, and videos are separate artifacts; do not claim
  they were updated unless they were regenerated and visually inspected.
- Treat the customer-facing reloaded-agent screen as the primary payoff.
  `2 CALLS → 1 REFUND` is supporting evidence about effect safety.
- Do not commit `.env`, `.demo-state`, local Temporal databases, stage logs, or
  temporary rendering directories.
