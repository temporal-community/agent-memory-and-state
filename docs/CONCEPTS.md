# Memory, state, and authority

The demo separates three operational roles without requiring a philosophical
ruling on whether state is a kind of memory:

- **Context** is what the model sees for this decision.
- **Memory** is what the agent retrieves or recalls to make the decision.
- **State** is an owner's record of progress or facts that informs and constrains
  what the application may safely do.

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
  describing what happened, or semantic, describing facts as the agent recalls
  them.

Both forms can be durable. Durability alone does not make them authoritative
about a fact owned elsewhere.

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
| **Authorization state** | May this agent act? | The authorization system |
| **Domain state** | What are the business facts? | The application database |

An autonomous agent can cache any of these facts in context or memory. The
cached copy does not replace the owner.

## The uncoordinated-progress trap

The dangerous band between memory and state is process-local loop progress:

> I observed the answers and lookups; my next action is to issue the refund.

A deploy, eviction, restart, OOM, or network partition can remove that progress
at exactly the point where the application owes work. The effect owner still
has its authoritative record, but that record contains only what reached it.

In the naive stage demo, the agent asks two questions, performs two lookups, and
chooses `issue refund` as its next action. The Worker then disappears before
calling Stripe. Memory can recall Nyghtowl's answers, and a replacement agent
correctly finds a paid order with no refund. Both records do their jobs. The
failure is that neither owns the active loop, its completed observations, or its
next action, so the customer restarts the return.

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

That is neither simply ephemeral nor permanently stored. Lifespan is a
configuration choice. Authority is the stable boundary:

> When the agent's copy and the owner's record disagree, the owner's record
> wins.

## Two owners meet before and after the effect

The guided stage deliberately loses the Worker after the autonomous loop chooses
the refund but before Stripe is called. At that moment:

- Temporal owns two customer-answer Signals, completed lookup Activities, and
  the loop's `issue refund` position.
- Stripe owns a paid charge and no refund.
- The Worker process owns nothing authoritative.

After the replacement Worker resumes, it reaches the refund Activity and Stripe
records the refund. Both owners remain necessary.

The manual technical demo exercises the later uncertain boundary: it loses the
Worker after Stripe accepts the refund but before the Activity reports
completion.

At that moment:

- Temporal owns the record that an Activity attempt started.
- Stripe owns the record that the refund committed.
- The Worker process owns nothing authoritative.

Temporal retries the Activity because it cannot assume the first attempt
completed. The Workflow's durable identity becomes the Stripe idempotency key,
so the second call asks Stripe about the same effect instead of creating a new
one.

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

The application must reconnect the reloaded agent to the same Workflow ID. It
can then surface the Workflow's current status or result instead of repeating
the questions or restarting the loop. At the later uncertain boundary, Temporal
retries the unresolved Activity; Stripe reconciles the stable effect identity;
and Temporal records the returned result. The agent can answer, “Your refund is
complete,” without replaying the customer interaction.

Temporal does not automatically inject that answer into a model or user
interface. The application is responsible for retaining or deriving the
Workflow ID and exposing the Workflow result to the reloaded agent.

## Authorization is the same boundary

The [permission state demo](PERMISSION_DEMO.md) applies the same model to a
GitHub push permission.

Remembering "you may push" is not proof that the grant remains active. The
authorization system owns that fact. An autonomous agent must check the current
record before acting.
