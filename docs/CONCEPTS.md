# Memory, state, and authority

The demo separates three operational roles without requiring a philosophical
ruling on whether state is a kind of memory:

- **Context** is what the model sees for this decision.
- **Memory** is what the agent retrieves or recalls to make the decision.
- **State** is an owner's record of progress or facts that informs and constrains
  what the application may safely do.

In this demo, the model sees all of working memory each turn, so the README's
table calls it context. On its own, "memory" usually means long-term memory in
a store.

All three can help an agent decide, and the same data can cross these
boundaries. The useful question is not what to call the bytes, but which record
wins when two copies disagree.

## Memory

Memory is information the agent retains or retrieves to reason. It may be the
only account of something no other system records, such as its plan or the
observation that a customer sounded upset. It may also contain a copy of facts
owned by another system.

Memory does not establish authority by itself. Unless provenance and freshness
are explicitly attached and checked, an autonomous agent may not know which
contents were observed, inferred, or made stale by a change elsewhere.

Memory appears at two timescales:

- **Working memory** is what the model works with this turn. The context window
  holds it; context management selects and refreshes it.
- **Long-term memory** carries knowledge across sessions. It may be episodic,
  describing what happened; semantic, describing facts as the agent recalls
  them; or procedural, describing how to do things, such as skill files and
  tool definitions.

Both forms can be durable. Durability alone does not make them authoritative
about a fact owned elsewhere.

The model also has parametric memory: what it learned in training. It lives in
the weights, so you can't see or edit it while the agent runs; only retraining
or fine-tuning changes it. When the weights and a record disagree, the record
wins.

### Temporal is not a memory store

Temporal rebuilds this run's working memory by replay, but long-term memory is
still a store you own, and
[Event History is bounded](HISTORY_GROWTH.md). Temporal can run the store's
reads and writes as Activities, so each one is recorded and retried like any
other step. How best to combine the two is still an open design question.

### Can domain state also be memory?

Yes. These are roles, not storage types. An order row is authoritative domain
state in the application database. When the agent retrieves that row, the
retrieved representation also becomes part of its working memory and may enter
model context. If the agent later keeps a summary, that summary is long-term
memory. The source order record remains authoritative when the copies disagree.

Likewise, a database is not automatically "state" rather than "memory." A table
of the agent's reflections can be a memory store; an orders table can be a
domain-state store; a Temporal Event History records execution state.

## State

State is an owner's record of a fact or process it owns. State often should be
retrieved into an agent's context because it helps the agent decide. Its special
property is not that the agent avoids using it; it is that other components
reconcile to that record when copies disagree. The record may lag the physical
world, but it remains the operational source of truth.

| State | Question | Owner in this demo |
| --- | --- | --- |
| **Execution state** | Where does the work stand? | Temporal |
| **Effect state** | Did the real effect commit? | Stripe or the offline ledger |
| **Authorization state** | May this agent act? | The authorization system (read it live) |
| **Domain state** | What are the business facts? | The application database |

An autonomous agent can cache any of these facts in context or memory. The
cached copy does not replace the owner. For any fact, ask: does another system
already own it? Asked of every fact, it finds more kinds of state than these
four, such as token budgets, locks, and quotas.

## The uncoordinated-progress trap

The dangerous band between memory and state is process-local loop progress:

> I observed the answers and lookups; my next action is to issue the refund.

A deploy, eviction, restart, OOM, or network partition can remove that progress
at exactly the point where the application owes work. The effect owner still
has its authoritative record, but that record contains only what reached it.
The README calls this failure mode lost loop position.

In the naive stage demo, an agent process runs the same loop and decision step
as the durable agent, with no Temporal: it asks two questions, performs the
lookups the policy or model picks, and chooses `issue refund` as its next
action. The process is then
killed before calling Stripe. Its process-local working memory disappears too.
A new agent process correctly finds a paid order with no refund in Stripe,
but Stripe never owned Nyghtowl's answers, the completed observations, or the
next action. The customer therefore starts over.

Persisting the answers in a separate memory system would make them retrievable,
but would not by itself make that system the owner of an active operation. To
resume safely, something must durably record that the operation exists, which
steps completed, and what remains to do.

A database-backed operation row, queue, scheduler, and reconciliation state
machine could remember and resume that work. Those pieces are execution state.
A lone "done" marker written after Stripe is also insufficient for the later
uncertain-effect case because the process can disappear between the effect and
the marker. Temporal is the durable execution implementation used in this demo,
not the only possible one.

## Authority, not lifespan

Memory and state are sometimes separated by lifespan: state is the ephemeral
present and memory is durable history. That is not the distinction used here.

A Temporal Workflow's execution state:

- lives while the execution is open
- remains durable across Worker restarts through replay
- stays as retained history for a configured period
- is eventually deleted

That is neither simply ephemeral nor permanently stored. Event History is also
bounded in size, so a long agent loop keeps large records in an external store,
such as S3, and passes only keys through the Workflow (see "When Event History
grows" in the README). Lifespan is a configuration choice. Authority is the
stable boundary:

> When the agent's copy and the owner's record disagree, the owner's record
> wins.

## Two owners meet before and after the effect

The guided stage deliberately loses the Worker after the autonomous loop chooses
the refund but before Stripe is called. At that moment:

- Temporal owns two customer-answer Signals, completed lookup Activities, and
  the loop's `issue refund` position.
- Stripe owns a paid charge and no refund.
- The Worker process owns nothing authoritative.

The stage's `WORKER GONE` frame reads those Signals and completed Activities
from Event History while no Worker is running.

After a new Worker resumes, it reaches the refund Activity and Stripe
records the refund. Both owners remain necessary.

The manual technical demo exercises the later uncertain boundary: it loses the
Worker after Stripe accepts the refund but before the Activity reports
completion.

At that moment:

- Temporal owns the record that an Activity attempt started.
- Stripe owns the record that the refund committed.
- The Worker process owns nothing authoritative.

Temporal retries the Activity because it cannot assume the first attempt
completed. The Stripe idempotency key comes from the Workflow run's identity:
`durable-refund-` plus the SHA-256 of `<workflow_id>:<run_id>`. The second call
therefore asks Stripe about the same effect instead of creating a new one.

The key stays the same across retries within one run. It changes for a new run
that reuses the Workflow ID, a reset, or continue-as-new, because each of those
gets a new Run ID. A key that must survive continue-as-new would have to come
from `workflow.info().first_execution_run_id` instead.

The result may be two calls, but it remains one refund.

Temporal does not make its Event History and Stripe one database transaction,
and durable execution does not create exactly-once effects. Temporal supplies a
durable attempt record, identity, and recovery point. Stripe uses that identity
to reconcile the retry with the effect it already owns.

## Why this changes the reloaded agent

Stripe can answer whether a refund happened, and memory can recall what the
customer said. Temporal owns a different problem: after the original Worker
disappears, it retains which observations completed and that the logical refund
is ready to run.

The application must keep or derive the same Workflow ID for the reloaded agent.
With it, the agent can surface the Workflow's current status or result instead
of repeating the questions or restarting the loop. In the guided stage, the
runner holds the Workflow handle the whole time, so what the audience sees is a
new Worker rebuilding the loop, not an application finding its Workflow
again.

At the later uncertain boundary, Temporal retries the unresolved Activity;
Stripe reconciles the stable effect identity; and Temporal records the returned
result. The agent can answer, “Your refund is complete,” without replaying the
customer interaction.

Temporal does not automatically inject that answer into a model or user
interface. The application is responsible for retaining or deriving the
Workflow ID and exposing the Workflow result to the reloaded agent.

## Authorization is the same boundary

The [permission state demo](PERMISSION_DEMO.md) applies the same model to a
GitHub push permission.

Remembering "you may push" is not proof that the grant remains active. The
authorization system owns that fact. An autonomous agent must check the current
record before acting.
