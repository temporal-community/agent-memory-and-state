# When Event History grows: claim check and Continue-As-New

Back to the [README](../README.md#gotchas).

Temporal records the input and result of every Activity in Event History. That
record is how a new Worker rebuilds the loop and resumes at
`issue refund`. Every step is saved, so a long agent run builds a big history.
A bigger history makes that rebuild after a crash slower, and the record has
limits that an agent loop can reach without meaning to.

## Why an agent loop grows its history

On every turn, the `RefundApprovalAgent` Workflow passes the request and the
whole `working_memory` list to `agent_decide_next_step`
([`workflow.py`](../src/refund_agent/workflow.py)), and `issue_refund` receives
the list once more. Each tool result is recorded once as that tool's result,
then again inside every later `agent_decide_next_step` input. After N tool
turns, the recorded bytes grow with N squared, not N.

This demo is not at risk. The loop stops at `MAX_TURNS = 10`. With the stage's
default request, the `agent_decide_next_step` input grows from about 0.5 KB to
about 1.1 KB over five turns, and all Activity payloads together come to under
7 KB. Those sizes come from serializing the stage's default values with the
SDK's default converter, not from a live run; what you type as the refund
request changes them slightly. Read the real number from your run in the
Temporal Web UI.

The problem appears when tool results are large and the loop runs long. Take a
payload-only model (an estimate, not a measured run) with 20 KiB tool results
and no turn cap: turn 1 saves 20 KiB, turn 2 saves 40 KiB, and turn 20 alone
saves 400 KiB. The total crosses 4 MiB, where Temporal suggests
Continue-As-New, around turn 20; 10 MiB around turn 32; and 50 MiB around turn
72. Real histories carry more than payloads, so the real crossings come at or
before these turns. That is still fewer than a thousand events: bytes reach the
limits before the event count does.

The model input grows the same way. In the same example, the turn-70 model
call alone sends about 350K input tokens, about $1.06 on Claude Sonnet 4.6 at
the 2026-09-29 list price of $3 per million input tokens (about 4 bytes per
token, uncached). [Cost to run](../README.md#cost-to-run) has this demo's own
tokens and dollars per pass, and how they were measured.

## See it in the Temporal Web UI

No code changes are needed:

1. Open a finished stage run in the Temporal Web UI, on a server you started
   yourself (see [Start your own dev server](GUIDE.md#start-your-own-dev-server)).
   The Workflow's summary shows its history size.
2. In the History tab, open any `WorkflowTaskStarted` event. It carries
   `historySizeBytes`, the size at that point.
3. Open the first and the last `agent_decide_next_step` `ActivityTaskScheduled`
   events and compare their inputs. Each one's summary names its turn, such as
   `Agent turn 1: decide the next step`. The later one carries every earlier
   observation.
4. From a terminal, `temporal workflow describe --workflow-id nyghtowl-take-01`
   prints the history length and size.

## The limits (Temporal server defaults)

| Threshold | History size | Events | What happens |
| --- | --- | --- | --- |
| Continue-As-New suggested | 4 MiB | 4,096 | `workflow.info().is_continue_as_new_suggested()` returns `True`. Nothing is enforced. Python Workflow code gets only a yes/no, not a reason. |
| Warning | 10 MB | 10,240 | The server logs warnings. |
| Limit | 50 MB | 51,200 | The Workflow Execution is terminated. |
| One payload | 2 MB. The warning comes at a few hundred KB; the docs list both 256 KB and 512 KB | n/a | A payload the Workflow produces fails the Workflow Task, and on Python SDK 1.23+ the run stays open until you deploy a fix. An oversized Activity result fails that Activity attempt instead. The SDK enforces this only when the server reports its limits at Worker start. |

Self-hosted servers can tune these in dynamic config. Temporal Cloud's history
and payload limits are fixed. Sources:
[Event History limits](https://docs.temporal.io/workflow-execution/event#event-history-limits),
[Temporal Cloud limits](https://docs.temporal.io/evaluate/cloud/limits),
[payload size errors](https://docs.temporal.io/troubleshooting/blob-size-limit-error),
[very long-running Workflows](https://temporal.io/blog/very-long-running-workflows)
(the Continue-As-New suggestion), and the server's
[dynamic config defaults](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go).

## Measured in the fleet demo

The companion
[fleet demo](https://github.com/temporal-community/temporal-ai-hitl-adk-langgraph)
ran one full pass per tab on 2026-09-30. On the Human → Agent tab, with the
model calls inline, the parent Workflow ended at 4,947 events and 9,443,220
bytes (9.0 MiB), about 1 MiB under the 10 MiB warning. On the Cross-Framework
tab, with the model calls in child Workflows, the parent ended at 2,154 events
and 408,054 bytes (0.4 MiB).

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
state; they are what let a new Worker resume without repeating
questions. Large records belong in your own store, such as S3, and Workflow
state keeps only a key (a claim check).

## Fix 1: claim check

For a result that's too big: save a ticket, not the data. It works like a coat
check. Your store (S3 or a database) keeps the coat; Event History keeps only
the ticket, a small key. The ticket replaces the big value in the Activity's
result and in the next step's input, and an Activity loads the record when it
needs it. Workflow code must never read the store directly, because that isn't
deterministic.

This demo doesn't need one. An agent that pulls a customer's full order history
into context would.

The Python SDK has this built in as
[External Storage](https://docs.temporal.io/external-storage). You configure
`temporalio.converter.ExternalStorage` with a `StorageDriver`, such as
`temporalio.contrib.aws.s3driver.S3StorageDriver`, on both the Client and the
Worker.

- Payloads at or above `payload_size_threshold` (256 KiB by default) are stored
  through the driver, and history keeps only a reference. For an agent loop,
  lower the threshold.
- The docs list External Storage as Public Preview, and the Python SDK marks it
  experimental. It was added in SDK 1.25.0. This repo's `uv.lock` pins 1.30.0
  (`pyproject.toml` allows any 1.x from 1.30), and 1.31.0 and 1.33.0 made
  breaking changes around it.

What a claim check does not do:

- It moves bytes; it doesn't shrink the prompt. The model still reads every
  record. Shrinking context is summarization or compaction, which is the memory
  system's job.
- Temporal never deletes offloaded objects. You own their lifecycle.
- The Temporal Web UI shows a reference instead of the data unless you run a
  codec server.
- Every Client and Worker needs the same driver, with the same name.

## Fix 2: Continue-As-New

For a run that goes on and on: a fresh history, same Workflow. It works like a
new notebook: copy over only the notes you need. At a quiet point in the loop,
with no Activity or question in flight, once
`workflow.info().is_continue_as_new_suggested()` returns `True`, the Workflow
can end its run and start a new one. The new run has the same Workflow ID, a
new Run ID, and an empty Event History. It receives only the input you pass,
such as the turns done and the customer's answers; memo and search attributes
carry over by default. The old run stays readable until retention ends, and
Signals, Queries, and Updates sent by Workflow ID reach the newest run.

```python
if workflow.info().is_continue_as_new_suggested():
    await workflow.wait_condition(workflow.all_handlers_finished)
    # Carry position and small entries, not the transcript.
    workflow.continue_as_new(compact_state)
```

Rules:

- Carry compact state. Without a claim check, carrying the full
  `working_memory` just restarts the same growth curve; the carried entries are
  small only when large records are already behind keys.
- Wait for Signal and Update handlers to finish first. Never call
  `continue_as_new` from a handler or inside `try`/`except`: it raises on
  purpose.
- Version the carried state's shape, because running Workflows continue into
  new code.
- In this repo, roll over only before `issue_refund`. Its Stripe idempotency
  key includes the Run ID, which Continue-As-New changes. If a key ever has to
  survive Continue-As-New, derive it from
  `workflow.info().first_execution_run_id`, not from the request ID (which
  defaults to the Workflow ID and would collide across reused IDs).

This repo implements neither fix, because the shipped loop never gets close to
a limit. For working patterns, see
[Continue-As-New](https://docs.temporal.io/design-patterns/continue-as-new),
the [claim check cookbook](https://docs.temporal.io/ai/cookbook/claim-check-pattern-python),
and [External Storage in Python](https://docs.temporal.io/develop/python/data-handling/external-storage).

## What Continue-As-New looks like (sketch)

The demo doesn't run this. It's a standalone sketch, not in this repo, that
uses the demo's names. Its request has two fields the demo's lacks: `resume`
and `continue_as_new_after_turns`. The loop checks at its top:

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
lookup results, so it fits a rollover before the first lookup, as in the capture
below. A loop that can roll over later, as the server suggestion can, must also
carry its observations or claim-check references to them.

Example Event History, captured from the sketch workflow, 2026-10-01, with
`continue_as_new_after_turns=2`: one Workflow ID (`nyghtowl-can-sketch`), two
Run IDs. Workflow Task events fill the gaps in the numbering.

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
