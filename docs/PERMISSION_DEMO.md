# Permission state demo

The refund demos focus on execution state: where the work stands and whether an
effect committed.

This companion demo applies the same boundary to authorization state:

> May this agent push to my repository?

The authorization system owns that answer. Context and memory may carry a copy,
but they cannot make a revoked grant current again.

## Run it

Two-pane view:

```bash
uv run permission-chat --panes
```

Plain REPL:

```bash
uv run permission-chat
```

Say "you can push" to grant permission, then say "push" to make the agent act.
Use `:help` to list every command.

## The three cases

### Context only

The grant exists for the current conversation and disappears on `:new`.

This is appropriate for conversational intent, but not for an authorization
fact that must remain enforceable.

### Remembered permission

Enable memory:

```text
:remember on
```

The agent recalls the grant across sessions. Revoke it in the external system:

```text
:revoke
```

Memory still says yes. If the agent trusts that recollection, it acts on a
permission that no longer exists.

### Authoritative permission state

Enable the authorization record:

```text
:state on
```

Revoke the grant and ask the agent to push again. The agent refuses because it
checks the current system of record.

## Takeaway

Remembering "you may push" is not the same as being authorized now.

The pattern is identical to the refund:

| Agent copy | Authoritative record |
| --- | --- |
| "I already refunded" | Stripe refund state |
| "You may push" | Authorization grant |

When they disagree, the owner of the fact wins.
