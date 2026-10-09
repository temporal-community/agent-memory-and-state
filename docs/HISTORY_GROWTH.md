# When Event History grows: claim check and Continue-As-New

Back to the [README](../README.md#gotchas).

Temporal records the input and result of every Activity in Event History,
which the Temporal Service stores outside the Worker. After a crash, a new
Worker replays that history: it runs the Workflow code again from the top, and
each Activity that already finished returns its recorded result instead of
running again. That is how this demo's loop resumes at `issue refund`. Because
every step is recorded, a long agent run builds a big history. A bigger
history makes that rebuild after a crash slower, and the record has limits
that an agent loop can reach without meaning to. This page explains why an
agent loop's history grows, which limits it can hit, how to see the size of a
run, and the two fixes: a claim check and Continue-As-New.

## Why an agent loop grows its history

On every turn, the `RefundApprovalAgent` Workflow passes the request and the
whole `working_memory` list to `agent_decide_next_step`
([`workflow.py`](../src/refund_agent/workflow.py)), and `issue_refund` receives
the list once more. Each tool result is recorded once as that tool's result,
then again inside every later `agent_decide_next_step` input. After N tool
turns, the recorded bytes grow with N squared, not N.

In this demo the history stays small, because the loop stops at
`MAX_TURNS = 10`. With the default refund request of `refund-demo stage`, the
`agent_decide_next_step` input grows from about 0.5 KB to about 1.1 KB over
five turns, and all Activity payloads together come to under 7 KB. Those sizes
come from serializing the default values with the SDK's default converter, not
from a live run, and what you type as the refund request changes them
slightly. To get the real number for your run, read it in the
[Temporal Web UI](#see-it-in-the-temporal-web-ui).

The problem appears when tool results are large and the loop runs long.
Consider a payload-only model, an estimate rather than a measured run, with
20 KiB tool results and no turn cap. Turn 1 saves 20 KiB, turn 2 saves 40 KiB,
and turn 20 alone saves 400 KiB, so the total climbs fast:

- Around turn 20, the total passes 4 MiB, and Temporal suggests
  Continue-As-New. Nothing is enforced yet.
- Around turn 32, it passes 10 MiB, and the server logs warnings.
- Around turn 72, it passes 50 MiB, and the server terminates the Workflow
  Execution.

Real histories carry more than payloads, so the real crossings come at or
before these turns. Even at turn 72 the run has fewer than a thousand events:
bytes reach the limits before the event count does.

The model input grows the same way. In the same example, the turn-70 model
call alone sends about 350K input tokens, about $1.06 on Claude Sonnet 4.6 at
the 2026-09-29 list price of $3 per million input tokens (about 4 bytes per
token, uncached). [Cost to run](../README.md#cost-to-run) has this demo's own
tokens and dollars per pass, and how they were measured.

## The limits (Temporal server defaults)

| Threshold | History size | Events | What happens |
| --- | --- | --- | --- |
| Continue-As-New suggested | 4 MiB | 4,096 | `workflow.info().is_continue_as_new_suggested()` returns `True`. Nothing is enforced. Python Workflow code gets only a yes/no, not a reason. |
| Warning | 10 MB | 10,240 | The server logs warnings. |
| Limit | 50 MB | 51,200 | The Workflow Execution is terminated. |
| One payload | 2 MB | n/a | The Workflow Task or Activity attempt that produced it fails (see the notes below). |

Notes on the table:

- The payload warning comes at a few hundred KB. Temporal's docs list both
  256 KB and 512 KB, and the server's default is 512 KiB.
- When a payload the Workflow produces is over the limit, it fails the
  Workflow Task, and on Python SDK 1.23+ the run stays open until you deploy a
  fix. An oversized Activity result fails that Activity attempt instead.
- The SDK enforces the payload limit only when the server reports its limits
  at Worker start.
- Temporal's docs write the warning, limit, and payload sizes in MB, but the
  server's [dynamic config defaults](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go)
  are binary: 10 MiB, 50 MiB, and 2 MiB. A MiB is 1,048,576 bytes, about 5%
  more than a MB. The growth estimate above uses MiB to match the server. Read
  as MB, each crossing would come up to two turns earlier, so no conclusion
  here depends on the unit.

Self-hosted servers can tune these in dynamic config. Temporal Cloud's history
and payload limits are fixed. Sources:
[Event History limits](https://docs.temporal.io/workflow-execution/event#event-history-limits),
[Temporal Cloud limits](https://docs.temporal.io/evaluate/cloud/limits),
[payload size errors](https://docs.temporal.io/troubleshooting/blob-size-limit-error),
[very long-running Workflows](https://temporal.io/blog/very-long-running-workflows)
(the Continue-As-New suggestion), and the server's
[dynamic config defaults](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go).

## See it in the Temporal Web UI

You can watch a run's history size without changing any code:

1. Open a finished Demo 2 run in the Temporal Web UI, on a server you started
   yourself (see [Start your own dev server](GUIDE.md#start-your-own-dev-server)).
   The Workflow's summary shows its history size.
2. In the History tab, open any `WorkflowTaskStarted` event. It carries
   `historySizeBytes`, the size at that point.
3. Open the first and the last `agent_decide_next_step` `ActivityTaskScheduled`
   events and compare their inputs. Each one's summary names its turn, such as
   `Agent turn 1: decide the next step`. The later one carries every earlier
   observation.
4. From a terminal, `temporal workflow describe --workflow-id <workflow-id>`
   prints the history length and size. The Workflow ID is
   `talk-refund-<token>` by default, or the ID you passed with
   `--workflow-id`, such as `nyghtowl-take-01` in the guide's examples.

## Measured in the fleet demo

The companion
[fleet demo](https://github.com/temporal-community/temporal-ai-hitl-adk-langgraph)
ran one full pass per tab on 2026-09-30. On the Human → Agent tab, with the
model calls inline, the parent Workflow ended at 4,947 events and 9,443,220
bytes (9.0 MiB, or 9.4 MB), about 1 MiB under the server's 10 MiB warning. On
the Cross-Framework tab, with the model calls in child Workflows, the parent
ended at 2,154 events and 408,054 bytes (0.4 MiB).

The fleet rolls each driver Workflow over at 10,000 events, at a quiet point
when the driver is idle with nothing pending
([Continue-As-New code](https://github.com/temporal-community/temporal-ai-hitl-adk-langgraph/blob/as-presented-2026-07/agent_fleet/workflows.py#L390-L414)).
The parent has the same guard, but a pass ends before it fires. Both count
events, not bytes. The inline parent reached 9.0 MiB at 4,947 events, so on a
longer run it would pass the 10 MiB warning long before 10,000 events.

On the Agent → Human tab, one full pass (51 orders) made 322 model calls and
used 732,256 tokens, $1.49, on `gemini-3.8-flash` with its default (medium)
thinking, at list prices valid through 2026-12-31. That leaves out 51 venue
searches, also Gemini calls, whose tokens LangGraph doesn't keep. On main, the
fleet README's
[history note](https://github.com/temporal-community/temporal-ai-hitl-adk-langgraph/blob/main/README.md#what-this-is-not)
gives these sizes rounded in MB, and its
[Cost to run](https://github.com/temporal-community/temporal-ai-hitl-adk-langgraph/blob/main/README.md#cost-to-run)
has every tab and what changes the cost.

## The ownership rule

Temporal owns where the work stands: which steps finished, what the loop is
waiting for, and what it does next. Small observations belong in Workflow
state, because they are what let a new Worker resume without repeating
questions. Large records belong in your own store, such as S3, and Workflow
state keeps only a key to each one (a claim check).

This demo needs neither fix below, and the repo implements neither: its loop
stops at `MAX_TURNS = 10` and never gets close to a limit. An agent that pulls
a customer's full order history into context would need a claim check.

## Fix 1: claim check

Use a claim check when a single result is too big to carry through Event
History. You save a ticket instead of the data. It works like a coat check:
your store (S3 or a database) keeps the coat, and Event History keeps only the
ticket, a small key. The ticket replaces the big value in the Activity's
result and in the next step's input, and an Activity loads the record when a
step needs it. The read has to happen in an Activity because Workflow code
must be deterministic. Replay runs the Workflow code again, so a direct read
from the store could return different data the second time and break replay.

The Python SDK has this built in as
[External Storage](https://docs.temporal.io/external-storage). You configure
`temporalio.converter.ExternalStorage` with a `StorageDriver`, such as
`temporalio.contrib.aws.s3driver.S3StorageDriver`, on both the Client and the
Worker.

- Payloads at or above `payload_size_threshold` (256 KiB by default) are
  stored through the driver, and history keeps only a reference. For an agent
  loop, lower the threshold.
- The docs list External Storage as Public Preview, and the Python SDK marks
  it experimental. It was added in SDK 1.25.0. This repo's `uv.lock` pins
  1.30.0 (`pyproject.toml` allows any 1.x from 1.30), and 1.31.0 and 1.33.0
  made breaking changes around it.

What a claim check does not do:

- It moves bytes; it doesn't shrink the prompt. The model still reads every
  record. Shrinking context is summarization or compaction, which is the
  memory system's job.
- Temporal never deletes offloaded objects. You own their lifecycle.
- The Temporal Web UI shows a reference instead of the data unless you run a
  codec server.
- Every Client and Worker needs the same driver, with the same name.

## Fix 2: Continue-As-New

Use Continue-As-New when a run goes on so long that its whole history is the
problem, even if no single result is large. Temporal only suggests it; your
Workflow code makes the call. Once
`workflow.info().is_continue_as_new_suggested()` returns `True`, wait for a
quiet point in the loop, with no Activity or customer question in flight, and
call `workflow.continue_as_new()`. It works like starting a new notebook and
copying over only the notes you need.

The new run has the same Workflow ID, a new Run ID, and an empty Event
History. It receives only the input you pass, such as the turns done and the
customer's answers. Memo and search attributes carry over by default. The old
run stays readable until its retention period ends. Signals, Queries, and
Updates sent by Workflow ID reach the newest run.

```python
if workflow.info().is_continue_as_new_suggested():
    await workflow.wait_condition(workflow.all_handlers_finished)
    # Carry position and small entries, not the transcript.
    workflow.continue_as_new(compact_state)
```

Rules:

- Carry compact state. If you carry the full `working_memory` without a claim
  check, the new run just starts the same growth curve over. The carried
  entries stay small only when large records are already behind keys.
- Wait for Signal and Update handlers to finish first, and never call
  `continue_as_new` from a handler. The call ends the run by raising
  `ContinueAsNewError` on purpose. In SDK 1.30.0 that error subclasses
  `BaseException`, so `except Exception` lets it through, but a bare `except:`
  or `except BaseException` around the call would swallow it.
- Version the carried state's shape, because running Workflows continue into
  new code.
- In this repo, roll over only before `issue_refund`. Its Stripe idempotency
  key includes the Run ID, which Continue-As-New changes, so a refund retried
  in the new run would carry a different key and Stripe couldn't tell it was a
  retry. If a key ever has to survive Continue-As-New, derive it from
  `workflow.info().first_execution_run_id`, not from the request ID, which
  defaults to the Workflow ID and would collide across reused IDs.

For working patterns, see
[Continue-As-New](https://docs.temporal.io/design-patterns/continue-as-new),
the [claim check cookbook](https://docs.temporal.io/ai/cookbook/claim-check-pattern-python),
and [External Storage in Python](https://docs.temporal.io/develop/python/data-handling/external-storage).

## What Continue-As-New looks like (sketch)

This is a standalone sketch, not in this repo, that uses the demo's names. Its
request has two fields the demo's lacks: `resume` and
`continue_as_new_after_turns`. The loop checks at its top:

```python
        for turn in range(start_turn, MAX_TURNS):
            # QUIET POINT: no Activity running, no question waiting.
            if self._continue_as_new_due(turn, start_turn, request):
                await workflow.wait_condition(workflow.all_handlers_finished)
                carried = replace(request, resume=self._checkpoint(turn))
                workflow.continue_as_new(carried)
            step = await workflow.execute_activity(
                agent_decide_next_step,
                ...,  # args and timeout
                summary=f"Agent turn {turn + 1}: decide the next step",
            )

    def _continue_as_new_due(self, turn: int, start: int, req: RefundRequest) -> bool:
        # Production trigger: the server suggests it (4 MiB or 4,096 events).
        suggested = workflow.info().is_continue_as_new_suggested()
        # Demo threshold, off by default: roll over once, after N turns.
        after = req.continue_as_new_after_turns
        return turn > start and (suggested or turn == after)
```

`_checkpoint(turn)` returns `{turns_used, customer_answers}`, and the new run's
`@workflow.init` restores both from `request.resume`. That checkpoint holds no
lookup results, so it fits a rollover before the first lookup, as in the
capture below. A loop that can roll over later, as the server suggestion can,
must also carry its observations or claim-check references to them.

Example Event History, captured from the sketch workflow, 2026-10-01, with
`continue_as_new_after_turns=2`: one Workflow ID (`nyghtowl-can-sketch`), two
Run IDs. Workflow Task events fill the gaps in the numbering. The sketch looks
up its own sample order, `ORD-1001` (headphones, 8,999 cents), not the demo's
order 1234 (the python plushy, $80.00).

Run 1, `01a0fb37…`: Continued As New, 25 events, 3,991 bytes.

| Event | Type | Key detail |
| --- | --- | --- |
| 1 | WorkflowExecutionStarted | input: `resume: null`, `continue_as_new_after_turns: 2` |
| 5-7 | ActivityTask Scheduled, Started, Completed | `agent_decide_next_step`, "Agent turn 1: decide the next step": ask `item_opened` |
| 11 | WorkflowExecutionSignaled | `customer_answer`: `item_opened`, `no` |
| 15-17 | ActivityTask Scheduled, Started, Completed | `agent_decide_next_step`, "Agent turn 2: decide the next step": ask `damage` |
| 21 | WorkflowExecutionSignaled | `customer_answer`: `damage`, `none` |
| 25 | WorkflowExecutionContinuedAsNew | new run `cb1b5c52…`, with the input below |

Run 2, `cb1b5c52…`: Completed, 23 events, 3,983 bytes.

| Event | Type | Key detail |
| --- | --- | --- |
| 1 | WorkflowExecutionStarted | continued from `01a0fb37…`; input: `resume: {turns_used: 2, customer_answers: {item_opened: no, damage: none}}` |
| 3 | WorkflowTaskStarted | `historySizeBytes` 554 (run 1's last: 3,461) |
| 5-7 | ActivityTask Scheduled, Started, Completed | `agent_decide_next_step`, "Agent turn 3: decide the next step": call `lookup_order` |
| 11-13 | ActivityTask Scheduled, Started, Completed | `lookup_order`: `ORD-1001`, headphones, 8,999 cents |
| 17-19 | ActivityTask Scheduled, Started, Completed | `agent_decide_next_step`, "Agent turn 4: decide the next step": decide |
| 23 | WorkflowExecutionCompleted | result `approve` |

Run 2 asks nothing again, and its turn count picks up at 3: both came in as
input.
