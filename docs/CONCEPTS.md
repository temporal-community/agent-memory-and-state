# Memory, state, and authority

The demo separates three operational roles without requiring a philosophical
ruling on whether state is a kind of memory:

- **Context** is what the model sees for this decision.
- **Memory** is what the agent retrieves or recalls to make the decision.
- **State** is what the application must not guess: progress and external facts
  recorded by the systems that own them.

The same data can cross these boundaries. The useful question is not what to
call the bytes, but which record wins when two copies disagree.

## Memory

Memory is what the agent knows. It may be the only account of something no
other system records, such as its plan or the observation that a customer
sounded upset.

What memory cannot establish by itself is provenance. A memory store cannot
tell an autonomous agent which contents were observed, inferred, or made stale
by a change elsewhere.

Memory appears at two timescales:

- **Working memory** is what the model works with this turn. The context window
  holds it; context management selects and refreshes it.
- **Long-term memory** carries knowledge across sessions. It may be episodic,
  describing what happened, or semantic, describing facts as the agent recalls
  them.

Both forms can be durable. Durability alone does not make them authoritative
about a fact owned elsewhere.

## State

State is an owner's record of a fact it owns. That record may lag the physical
world, but it remains the version other components reconcile to.

| State | Question | Owner in this demo |
| --- | --- | --- |
| **Execution state** | Where does the work stand? | Temporal |
| **Effect state** | Did the real effect commit? | Stripe or the offline ledger |
| **Authorization state** | May this agent act? | The authorization system |
| **Domain state** | What are the business facts? | The application database |

An autonomous agent can cache any of these facts in context or memory. The
cached copy does not replace the owner.

## The process-local trap

The dangerous band between memory and state is process-local progress:

> I already issued the refund.

It looks like a record, but it is a belief held by one process. A deploy,
eviction, restart, OOM, or network partition can remove it at exactly the point
where an autonomous agent needs certainty.

In the naive demo, the effect owner still has one refund after the process
restarts. The agent rebuilds the same context and retrieves the same customer
facts, but no durable owner records its progress. It repeats the decision and
creates a duplicate.

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

## Two owners meet at the uncertain effect

The durable refund demo deliberately loses the Worker after Stripe accepts the
refund but before the Activity reports completion.

At that moment:

- Temporal owns the record that an Activity attempt started.
- Stripe owns the record that the refund committed.
- The Worker process owns nothing authoritative.

Temporal retries the Activity because it cannot assume the first attempt
completed. The Workflow's durable identity becomes the Stripe idempotency key,
so the second call asks Stripe about the same effect instead of creating a new
one.

The result may be two calls, but it remains one refund.

Durable execution does not create exactly-once effects. It supplies a durable
attempt identity and recovery point so retries can reconcile with the effect
owner.

## Authorization is the same boundary

The [permission state demo](PERMISSION_DEMO.md) applies the same model to a
GitHub push permission.

Remembering "you may push" is not proof that the grant remains active. The
authorization system owns that fact. An autonomous agent must check the current
record before acting.
