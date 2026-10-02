# When Event History grows: claim check and continue-as-new

Back to the [README](../README.md#when-event-history-grows-claim-check-and-continue-as-new).

Temporal records the input and result of every Activity in Event History. That
record is how a replacement Worker rebuilds the loop and resumes at
`issue refund`. The record also has limits, and an agent loop can reach them
without meaning to.

## Why an agent loop grows its history

On every turn, `RefundWorkflow` passes the request and the whole
`working_memory` list to `agent_decide_next_step`
([`workflow.py`](../src/refund_agent/workflow.py)), and `issue_refund` receives
the list once more. Each tool result is recorded once as that tool's result,
then again inside every later `agent_decide_next_step` input. After N tool
turns, the recorded bytes grow with N squared, not N.

This demo is not at risk. The loop stops at `MAX_TURNS = 10`. With the stage's
default request, the `agent_decide_next_step` input grows from about 0.5 KB to
about 1.1 KB over five turns, and all Activity payloads together come to under
7 KB. Those sizes come from serializing the stage's default values with the
SDK's default converter, not from a live run; what you type as the refund
request changes them slightly. Read the real number from your run in Temporal
Web.

The problem appears when tool results are large and the loop runs long. A
payload-only model (not a measured run) with 20 KiB tool results and no turn
cap crosses 4 MiB around turn 20, 10 MiB around turn 32, and 50 MiB around turn
72. Real histories carry more than payloads, so the real crossings come at or
before these turns. That is still fewer than a thousand events: bytes reach the
limits before the event count does.

## See it in Temporal Web

No code changes are needed:

1. Open a finished stage run in Temporal Web, on a server you started yourself
   (see [Watch it in Temporal Web](TEMPORAL_WEB.md)). The Workflow's
   summary shows its history size.
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
| Continue-as-new suggested | 4 MiB | 4,096 | `workflow.info().is_continue_as_new_suggested()` returns `True`. Nothing is enforced. Python Workflow code gets only a yes/no, not a reason. |
| Warning | 10 MB | 10,240 | The server logs warnings. |
| Limit | 50 MB | 51,200 | The Workflow Execution is terminated. |
| One payload | 2 MB. The warning comes at a few hundred KB; the docs list both 256 KB and 512 KB | n/a | A payload the Workflow produces fails the Workflow Task, and on Python SDK 1.23+ the run stays open until you deploy a fix. An oversized Activity result fails that Activity attempt instead. The SDK enforces this only when the server reports its limits at Worker start. |

Self-hosted servers can tune these in dynamic config. Temporal Cloud's history
and payload limits are fixed. Sources:
[Event History limits](https://docs.temporal.io/workflow-execution/event#event-history-limits),
[Temporal Cloud limits](https://docs.temporal.io/evaluate/cloud/limits),
[payload size errors](https://docs.temporal.io/troubleshooting/blob-size-limit-error),
[very long-running Workflows](https://temporal.io/blog/very-long-running-workflows)
(the continue-as-new suggestion), and the server's
[dynamic config defaults](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go).

## The ownership rule

Temporal owns where the work stands: which steps finished, what the loop is
waiting for, and what it does next. Small observations belong in Workflow
state; they are what let the reloaded agent resume without repeating
questions. Large records belong in a memory store, and Workflow state keeps
only a key.

## Fix 1: claim check

Store the large value outside Temporal and pass a small reference through
Workflow and Activity inputs. An Activity loads the record when it needs it.
Workflow code must never read the store directly, because that isn't
deterministic.

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
- Temporal Web shows a reference instead of the data unless you run a codec
  server.
- Every Client and Worker needs the same driver, with the same name.

## Fix 2: continue-as-new

At a quiet point in the loop, with no Activity or question in flight, the
Workflow can end its run and start a new one. The new run has the same Workflow
ID, a new Run ID, and an empty Event History. It receives only the input you
pass; memo and search attributes carry over by default. Signals and Queries
sent by Workflow ID reach the new run.

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
  key includes the Run ID, which continue-as-new changes. If a key ever has to
  survive continue-as-new, derive it from
  `workflow.info().first_execution_run_id`, not from the request ID (which
  defaults to the Workflow ID and would collide across reused IDs).

This repo implements neither fix, because the shipped loop never gets close to
a limit. For working patterns, see
[continue-as-new](https://docs.temporal.io/design-patterns/continue-as-new),
the [claim check cookbook](https://docs.temporal.io/ai/cookbook/claim-check-pattern-python),
and [External Storage in Python](https://docs.temporal.io/develop/python/data-handling/external-storage).

## What continue-as-new looks like (sketch)

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
