# Agent Memory and State

<div align="center">

[![MIT License](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Temporal Python SDK](https://img.shields.io/badge/Temporal_Python_SDK-1.30%2B-635bff)](https://github.com/temporalio/sdk-python)
[![Stripe](https://img.shields.io/badge/Stripe-test_mode_only-635bff?logo=stripe&logoColor=white)](https://docs.stripe.com/test-mode)
[![uv](https://img.shields.io/badge/run_with-uv-de5fe9)](https://docs.astral.sh/uv/)

</div>

**What happens to an AI agent's in-flight work when its process dies?**

This demo kills an agent one step before it refunds a customer. The failure
mode is **lost loop position**. By then the agent has asked Nyghtowl two
questions, looked up her order and refund history, and chosen `issue refund`.
When the naive agent's process dies, that progress is lost, and the new
process has no way to get it back, so Nyghtowl has to start the return again.
The durable agent runs the same steps as a Temporal Workflow. A new Worker
rebuilds the loop from Event History and resumes at `issue refund` without
repeating a question.

There is no agent framework. The point is to make the boundary between context,
memory, and authoritative state visible.

**What is real and what is staged:**

- By default, the durable agent uses a deterministic refund policy, the naive
  agent is a scripted process, "Stripe" is an offline ledger, and Temporal is a
  local dev server. A default run makes no model calls: 0 tokens, $0.
- `--real` switches to Stripe test mode. `--real-model` lets Claude or OpenAI
  choose the lookups and the refund decision.
- The stage runner keeps its own copy of your Demo 1 answers for display and
  never gives it to the new agent process. It replays those answers into the
  durable run as Signals, so Demo 2 doesn't ask you to type them again, and the
  screen says so: "Reusing your Demo 1 answers so you don't type them twice."
- Each demo's header has a dim line that names what is scripted, such as
  `Scripted steps · offline ledger (no Stripe)` or
  `Fixed policy (no LLM) · sample lookups · Stripe test mode`.
- On the default path, the durable Workflow waits on a stage-only `release`
  Signal just before the refund, so the Worker kill lands at the same point in
  every take.
- The kills are real: each process gets a SIGKILL.

## See the idea in 15 seconds

![Animated comparison: the naive agent loses its answers and restarts, while the Temporal-backed agent resumes the saved loop](assets/demo-reel.gif)

[Watch or download the MP4 version](assets/demo-reel.mp4), or
[view the presentation deck: *Agentic Memory and State* (PDF)](docs/agentic-memory-and-state.pdf).

| Moment | Naive agent | Durable agent |
| --- | --- | --- |
| **Before the request** | Nyghtowl's plush python shows as paid | The same paid order |
| **Agent loop** | A scripted process asks two questions, performs two lookups, and chooses `issue refund` | The same steps in a Temporal Workflow: answers are Signals, lookups are Activities |
| **Process killed** | The naive agent process takes the answers and loop position with it; Stripe still says paid with no refund | The Worker is killed; completed observations and the next action remain in Event History |
| **Agent reloads** | A new agent process correctly checks Stripe, but the customer starts over | A new Worker rebuilds the loop from Event History; **no repeated questions** |
| **Outcome** | The customer must repeat the intake | The loop resumes at `issue refund` |

## Videos

| Video | What it shows |
| --- | --- |
| **Temporal & AI Demos: Agent Memory & State** (link added after publish) | An agent is killed one step before a refund. The naive agent loses the customer's answers; the durable loop resumes at `issue refund`. It also covers why Event History grows, and when to use a claim check or continue-as-new. |

Chapters: Hook · The problem · Demo · How memory and execution state relate ·
Where Temporal fits · Pros, cons, and gotchas · Cost to run · Takeaways and
resources. Timestamps are added after the final cut. The video's key moment is
written down in [The money moment](#the-money-moment), and the full cost is in
[Cost to run](#cost-to-run).

One runnable next step kills the Worker while the refund Activity is in flight.
It runs offline with no model calls (0 tokens, $0):

```bash
uv run refund-demo stage --simulate-stripe-timeout
```

Further reading: [Temporal docs](https://docs.temporal.io), the
[Python SDK](https://github.com/temporalio/sdk-python), and
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests).

<!-- TODO before publishing: video URL with UTM, blog post URL, related videos
(human-in-the-loop, multi-agent handoffs). Add Temporal Cloud credits only once
a code and amount are confirmed. -->

## The boundary that matters

The useful distinction is operational role and authority, not storage
technology or lifespan. Ask one question:

> When two copies disagree, which record wins?

| Role | What it answers | Authority |
| --- | --- | --- |
| **Context** | What does the model see for this decision? | Assembled for the current turn |
| **Memory** | What retained or retrieved information does the agent use to reason? | The agent or its memory system |
| **Execution state** | Where does the work stand? | Temporal |
| **Effect state** | Did the refund actually commit? | Stripe |
| **Authorization state** | May the agent act? | The authorization system |
| **Domain state** | What are the business facts? | The application database |

When the Worker disappears after the agent chooses the refund, Stripe proves
the payment is still paid with no refund, but it never owned the answers or the
loop's position, and recalled memory would not prove that `issue refund` is
the next unfinished action. Temporal supplies that execution state here; a durable job
table or a careful state machine can too. The stage leads with this case
because its customer cost is visible; the [manual walkthrough](docs/REFUND_DEMO.md)
covers the later loss, after Stripe commits. Read
[Memory, state, and authority](docs/CONCEPTS.md) for the complete model,
including how one fact can play several roles, working and long-term memory,
the lifespan framing, and the exactly-once misconception.

## What this demo proves

- The durable agent is a visible loop. On the stage path, two intake questions
  are asked by code; a deterministic policy or a live model then chooses the
  lookups and the decision.
- Process-local working memory disappears when its process is killed.
- Persisted memory can restore facts without owning the loop's progress.
- Stripe proves that the payment is paid and no refund exists in the naive run.
- Without execution state, recovery requires restarting the loop or building a
  custom durable state machine.
- A durable Workflow records where the work stands across Worker restarts.
- An application that keeps or derives the Workflow ID can report running or
  completed work instead of starting a new operation. In the stage, the runner
  holds that Workflow handle for you.
- Stripe remains authoritative about whether the refund exists.
- One Workflow run identity becomes one effect idempotency key. The key is
  `durable-refund-` plus the SHA-256 of `<workflow_id>:<run_id>`, so it stays
  the same across retries in one run and changes for a new run.
- Durable execution does not make effects exactly once; it lets a retry ask the
  effect owner instead of guessing.

## How it works

```mermaid
flowchart LR
    accTitle: How the guided stage demo is wired
    accDescr: The refund-demo stage command drives both demos. Demo 1 is a scripted naive agent process that keeps its answers in memory, and after it is killed a new process only reads the effect owner. Demo 2 starts a Temporal Workflow on a local dev server. A separate Worker process polls a private task queue on that server and runs the Workflow loop and its Activities. The stage kills that Worker and starts a replacement, which replays Event History to rebuild the loop and then issues one refund to the offline effect ledger, or to Stripe test mode with --real.
    stage["refund-demo stage<br/>stage.py"]
    subgraph demo1["Demo 1: naive agent process"]
        naive["naive_refund.py<br/>scripted steps<br/>answers in a local dict"]
    end
    subgraph server["Temporal dev server: gRPC 7233, Web UI 8233"]
        queue["Private task queue<br/>refund-stage-token"]
        history[("Event History<br/>RefundApprovalAgent")]
    end
    subgraph worker["Worker process: worker.py, killed then replaced"]
        wf["Workflow loop<br/>workflow.py"]
        acts["Activities<br/>agent_step, 3 fixture lookups,<br/>issue_refund"]
    end
    naiveLedger[("Naive ledger, offline<br/>naive-ledger.json")]
    effectLedger[("Effect ledger, offline<br/>effect-ledger.json")]
    stripe[("Stripe test mode<br/>--real only")]
    stage -->|"stdin and stdout"| naive
    naive -->|"read-only check, offline"| naiveLedger
    naive -->|"read-only check, --real"| stripe
    stage -->|"start, Signals, Queries, history reads"| server
    worker -->|"polls"| queue
    history -.->|"replayed after a restart"| wf
    wf --> acts
    acts -->|"one refund per idempotency key"| effectLedger
    acts -->|"same, with --real"| stripe
    stage -.->|"SIGKILL, then a replacement"| worker
```

`uv run refund-demo stage` ([`stage.py`](src/refund_agent/stage.py)) drives a
scripted naive subprocess ([`naive_refund.py`](src/refund_agent/naive_refund.py))
for Demo 1 and the `RefundApprovalAgent` Workflow for Demo 2. A separate Worker
([`worker.py`](src/refund_agent/worker.py)) polls a private
`refund-stage-<token>` task queue and runs the loop
([`workflow.py`](src/refund_agent/workflow.py)) and its Activities. The stage
SIGKILLs it at `ready_to_refund`; a replacement replays Event History and
issues one refund ([full walkthrough](docs/ARCHITECTURE.md#how-the-stage-is-wired)).

### The agent loop is ordinary Python

Condensed from [`workflow.py`](src/refund_agent/workflow.py):

```python
for _turn in range(MAX_TURNS):  # MAX_TURNS = 10
    step = await workflow.execute_activity(agent_step, args=[request, self.working_memory], ...)
    if step.action == "decide":
        decision = RefundDecision(...)
        break
    if step.action == "ask_customer":
        await workflow.wait_condition(answer_arrived)  # answer_question Signal
        self.working_memory.append(customer_answer)
        continue
    result = await self._run_tool(step.tool, request)
    self.working_memory.append({"tool": step.tool, "result": result})
return await workflow.execute_activity(issue_refund, ...)  # after approval and release waits
```

Answers arrive as Signals, every external call is an Activity, and a
replacement Worker rebuilds `working_memory` by replaying Event History. The
[full sketch](docs/ARCHITECTURE.md#the-agent-loop-is-ordinary-python) adds
timeouts, retry policies, and a side-by-side with a plain in-process loop.

## Run the guided demo

Prerequisites: Python 3.11 or newer, the
[Temporal CLI](https://docs.temporal.io/cli), and [uv](https://docs.astral.sh/uv/).
Install the project, test tools, and Rich terminal UI, then create `.env` from
the example without overwriting one you already have:

```bash
uv sync --extra dev --extra tui
test -e .env || cp .env.example .env
```

The default run needs no keys. Fill in `.env` only for `--real` or
`--real-model`. Exported shell variables take precedence over `.env`.

Run the complete comparison in one fullscreen terminal, pressing Enter at each
prompt:

```bash
uv run refund-demo stage
```

### Choose the stage path

| Goal | Command | Model tokens and dollars per pass |
| --- | --- | --- |
| Rehearse safely with deterministic responses and an offline ledger | `uv run refund-demo stage` | 0 tokens, $0 |
| Run the same story against Stripe test mode | `uv run refund-demo stage --real` | 0 tokens, $0 |
| Show a real Activity retry after a simulated Stripe timeout | `uv run refund-demo stage --real --simulate-stripe-timeout` | 0 tokens, $0 |
| Let a live model choose the lookups and the decision | `uv run refund-demo stage --real-model --model-provider anthropic` (or `openai`) | GPT-5.6 Luna, measured 2026-09-30: 4 calls, 2,845 tokens (reasoning included), $0.0009. Claude Sonnet 4.6, estimated (not run): about 4 calls, 5,600-7,300 tokens, about $0.02. See [Cost to run](#cost-to-run) |

A live model needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`, or
`OPENAI_API_KEY` and `OPENAI_MODEL`. `--real` needs a Stripe `sk_test_` or
`rk_test_` key; live Stripe keys are rejected. If a `--real` take ends before
the refund, run `uv run refund-demo cleanup`. The
[guided stage runner](docs/STAGE_GUIDE.md) covers each step, the timeout and
`--simulate-stripe-retry` paths, and live-model tips.

### Watch it in Temporal Web

Start `temporal server start-dev` in another terminal first. The stage reuses
it, so Temporal Web at <http://localhost:8233> stays up after the stage exits; a
server the stage starts shuts down with it. Pass a new `--workflow-id` for each
take, such as `nyghtowl-take-01`. The [Temporal Web guide](docs/TEMPORAL_WEB.md)
covers what to check at each frame, the port variant when 7233 or 8233 is
taken, CLI commands, and resetting between takes.

## The money moment

Both agents hit the same failure at the same point in the loop, with two
different outcomes. The naive agent process is killed after choosing
`issue refund` (`PROCESS GONE`). The new agent process tells Nyghtowl: "No
refund request reached Stripe. I lost your return answers. Please start the
return again."

The durable Worker is killed at the same next action. With nothing running,
Temporal still has both answers, both lookups, and
`Next action: issue refund`, and the stage reads them back from Event History
on the `WORKER GONE` frame. The new Worker finishes with
`NO REPEATED QUESTIONS`, `NO LOOP RESTART`, and "Your refund is complete."

In the video: "The Worker is disposable; the loop is not."

![The durable demo right after its Worker was killed. The left pane, Temporal Worker, reads WORKER GONE: its in-memory loop is gone, and Temporal still has the saved loop. The right pane, What Survives, shows Temporal, read from Temporal just now: customer answers 2, completed lookups 2, next action issue refund; and the offline ledger (Stripe stand-in): payment paid, refund none.](assets/durable-saved.png)

For proof beyond the stage screen, [Temporal Web](docs/TEMPORAL_WEB.md#what-to-check-at-each-frame)
shows the Workflow still Running during `WORKER GONE` and no repeated
`agent_step`, lookup, or `answer_question` event after the restart.

The naive answer is not wrong: memory and Stripe are both useful. The contrast
is whether the autonomous work itself still has a position:

| Process-local loop | Durable execution |
| --- | --- |
| The answers and active loop disappear; Stripe only says paid with no refund. | Temporal retains completed observations and `Next action: issue refund`; the new Worker continues without repeating questions. |
| ![The new agent process has lost the return answers and asks the customer to start over](assets/naive-loop-restarts.png) | ![The new Temporal Worker completes the refund without repeating questions or restarting the loop](assets/durable-recovered.png) |

## What you should see

Key lines from a default run, in order (box drawing and most lines removed):

```text
Demo 1: Without Temporal, the agent loses its place
    → Next: issue refund
  AGENT PROCESS  PROCESS GONE
  AGENT  No refund request reached Stripe.
         Please start the return again.
Demo 2: With Temporal, the agent keeps its place
  TEMPORAL WORKER  WORKER GONE
  WHAT SURVIVES    TEMPORAL  Read from Temporal just now:
                             Next action: issue refund
  NEW TEMPORAL WORKER  NO REPEATED QUESTIONS
                       NO LOOP RESTART
                         Your refund is complete.
```

The [expected output](docs/EXPECTED_OUTPUT.md) has the full transcript, the
pane text when the history read fails, and the Worker log showing the resume.

## Cost to run

The default run costs $0 and uses 0 model tokens. A live-model pass on
GPT-5.6 Luna was measured on 2026-09-30: 4 model calls, 2,492 input and 353
output tokens (114 of them reasoning), 2,845 tokens in all, $0.0009. Claude
Sonnet 4.6 has not been run; it is an estimated 4 model calls, about
5,400-6,900 input and 200-400 output tokens, about $0.02. Killing the Worker
adds no model calls: the replacement replays the recorded model turns from
Event History, and the kill + replay in the measured pass added 0 calls.

| Run | Model and settings | Model calls per pass | Tokens per pass | Dollars per pass | Basis |
| --- | --- | --- | --- | --- | --- |
| `uv run refund-demo stage` | None: deterministic policy, offline ledger, local dev server | 0 | 0 | $0.00 | From the code path |
| `uv run refund-demo stage --real` | None: deterministic policy, Stripe test mode | 0 | 0 | $0.00 (Stripe test mode moves no money) | From the code path |
| `stage --real-model --model-provider anthropic` | `claude-sonnet-4-6`, `max_tokens=512`, forced tool choice, no extended thinking, no prompt caching | about 4 (the 2 intake questions don't call the model) | about 5,400-6,900 input + 200-400 output | about $0.019-$0.027 | **Estimated**, 2026-09-29. Not run: no Claude pass has been logged |
| `stage --real-model --model-provider openai` | `gpt-5.6-luna`, Responses API, reasoning effort left at the model default, no output cap | 4 (all before the kill; the kill + replay added 0) | 2,845: 2,492 input (0 cached) + 353 output (239 visible + 114 reasoning, billed as output) | $0.0009 | **Measured**, 2026-09-30, one pass with `LOG_MODEL_USAGE=1`, summed by `refund-demo usage` |
| Worst case, stage with Claude | 8 model turns x 5 Temporal attempts; assumes about 2,000 input tokens per call (default request text) and every call billed at the 512-token cap | 40 | about 80,000 input + 20,480 output | about $0.55 | Modeled from the code. Not a hard ceiling: your request text is resent on every call |
| Worst case, manual `refund-demo start` with Claude | 10 model turns x 5 attempts (no code-driven intake turns); same assumptions | 50 | about 100,000 input + 25,600 output | about $0.68 | Modeled from the code, same caveat |
| Worst case, stage with GPT-5.6 Luna | 8 turns x 5 attempts; assumes about 2,000 input and about 2,100 output plus reasoning tokens per call | 40 | about 80,000 input + 84,000 output | about $0.12 | Modeled. No fixed ceiling: the code sets no output cap |

List prices as of 2026-09-29, per million tokens: Claude Sonnet 4.6 $3 input
and $15 output; GPT-5.6 Luna $0.20 input and $1.20 output. Stripe test mode and
the local dev server cost $0; on Temporal Cloud a pass is an estimated 20-165
Actions, under one cent. Retries (up to 5 attempts per model turn), more turns,
a longer request resent on every call, and reasoning tokens raise the cost.
[Cost methodology](docs/COST.md) has the price sources, each cost driver, how
the measurement and estimates were made, and how to log and sum a pass's
tokens and dollars with `LOG_MODEL_USAGE=1` and `refund-demo usage`.

<!-- After a measured Claude pass, replace the "Estimated" Claude row with the
measured calls, tokens, dollars, and date. -->

## When Event History grows: claim check and continue-as-new

Event History records every Activity's input and result; that record is how
the replacement Worker resumes. This loop resends all of `working_memory` to
`agent_step` each turn, so recorded bytes grow with the square of the turn
count. The demo stays under 7 KB of payloads (it stops at `MAX_TURNS = 10`),
but a payload-only model with 20 KiB tool results and no turn cap crosses 4 MiB
around turn 20. Keep small observations in Workflow state, large records in a
memory store behind a key (a claim check; the Python SDK's External Storage),
and roll a long loop over with continue-as-new.

| Threshold | History size | Events | What happens |
| --- | --- | --- | --- |
| Continue-as-new suggested | 4 MiB | 4,096 | `workflow.info().is_continue_as_new_suggested()` returns `True`. Nothing is enforced. Python Workflow code gets only a yes/no, not a reason. |
| Warning | 10 MB | 10,240 | The server logs warnings. |
| Limit | 50 MB | 51,200 | The Workflow Execution is terminated. |
| One payload | 2 MB. The warning comes at a few hundred KB; the docs list both 256 KB and 512 KB | n/a | A payload the Workflow produces fails the Workflow Task, and on Python SDK 1.23+ the run stays open until you deploy a fix. An oversized Activity result fails that Activity attempt instead. The SDK enforces this only when the server reports its limits at Worker start. |

Temporal server defaults, per the
[Event History limits](https://docs.temporal.io/workflow-execution/event#event-history-limits).
The [deep dive](docs/HISTORY_GROWTH.md) covers seeing growth in Temporal Web,
both fixes and their pitfalls, Temporal Cloud limits, and all sources.

## How other products approach it

| Kind | Examples | After a crash |
| --- | --- | --- |
| Memory layers and transcript stores | Mem0, Letta, Anthropic memory tool, OpenAI Agents SDK Sessions | Restore what the agent knows; a new process decides again |
| Execution state inside one agent runtime | LangGraph checkpointers, LangSmith Deployment, OpenAI Agents SDK `RunState`, Google ADK Resume | Resume within that runtime; some re-run a step, so effects still need idempotency keys |
| Execution state you build | Postgres job table with a recovery point | A completer process you write |
| Durable execution, not tied to an agent framework | Temporal (this demo), DBOS | Resume from recorded steps: any Temporal Worker polling the task queue, or the DBOS app from its last completed step |

Persisted chat history lets a new process decide again. Durable execution
resumes the decision the agent already made. And Stripe, not either of them,
says whether money moved. The [full comparison](docs/COMPARISON.md) has each
product's details and sources as read on 2026-09-29, and when you don't need
Temporal.

## What it is not

- **Not a production refund service.** No authentication, production database,
  web application, multi-agent orchestration, or operational hardening.
- **Not LLM-driven by default.** Without `--real-model`, a deterministic policy
  decides. With it, code still asks the two intake questions, the model chooses
  the lookups and the decision, and the stage approves if the model escalates.
- **The naive side is not a model or a Temporal Worker.** It is a scripted
  process with hard-coded questions and lookups: the same steps as the durable
  half, not the same code. The screens call it the agent process
  (`PROCESS GONE`, `NEW AGENT PROCESS`) and keep "Worker" for the Temporal
  side (`WORKER GONE`, `NEW TEMPORAL WORKER`).
- **The lookups return fixtures.** `lookup_order`, `lookup_customer_history`,
  and `check_refund_policy` return fixed records.
- **It does not show an application recovering its own Workflow ID.** The stage
  runner replays your Demo 1 answers as Signals and holds the Workflow handle
  throughout, so what you see is a Worker being replaced. A real application
  must keep or derive the Workflow ID and surface the Workflow's status.
- **The pause before the refund is staged.** On the default path, the Workflow
  waits on a stage-only `release` Signal at `ready_to_refund`, so the kill lands
  at the same point every time; a real Worker dies wherever it dies.
  `--simulate-stripe-timeout` kills it while `issue_refund` is in flight.
- **Not every Stripe line is a live Stripe read.** `Payment: PAID` in the
  durable pane, and in the naive pane before the kill, is a fixed label. The
  durable refund line reads a local mirror of Stripe's response. Only the new
  agent process's status check reads Stripe directly, and only with `--real`;
  offline, it reads its own naive ledger. In the default mode the pane heading
  says `OFFLINE LEDGER (Stripe stand-in)` (with `--real`, `STRIPE (test mode)`),
  but the agent's lines and the Worker log still say "Stripe" as the story's
  name for the effect owner.
- **Not a memory system.** Temporal holds execution state, not the agent's
  memory, and [Event History is bounded](#when-event-history-grows-claim-check-and-continue-as-new).
  The demo doesn't prescribe how agent memory should be stored or managed;
  where durable execution and long-term memory best fit together is an open
  design question.
- **Not exactly-once.** One request can mean two calls and still one refund,
  because both calls share one idempotency key.
- **Not Temporal Cloud.** The clients connect to a local dev server, with no TLS
  or API-key options.

## Troubleshooting

Stage errors are printed as `STAGE | <message>`. Workflow and Activity failures
show up in Temporal Web and in `.demo-state/stage-<token>/worker.log`. The five
most likely errors are below; the [full troubleshooting table](docs/TROUBLESHOOTING.md)
covers live-model, Stripe, timeout, usage-log, and Temporal Web errors.

| You see | Cause | Fix |
| --- | --- | --- |
| ``STAGE \| Temporal is not reachable and the `temporal` CLI is not on PATH`` | Nothing answers at `TEMPORAL_ADDRESS`, and the stage can't start a server | Install the Temporal CLI, or run `temporal server start-dev` first |
| `STAGE \| Temporal dev server exited while starting:` plus a log tail | Usually port 7233 or 8233 is already in use | Use the [port variant](docs/TEMPORAL_WEB.md#start-your-own-dev-server) |
| `STAGE \| Worker exited while starting:` plus a log tail | Often a live or malformed `STRIPE_API_KEY` in `.env`, rejected even offline | Read the tail. Use a `sk_test_` or `rk_test_` key, or remove it |
| `The stage view needs rich. Install it with: uv sync --extra tui` | A plain `uv sync` removed the optional Rich extra | Run `uv sync --extra dev --extra tui` |
| `WorkflowAlreadyStartedError` traceback | You reused a running take's `--workflow-id` | Use a new ID, or run `uv run refund-demo stop <id>` |

## Explore the demos

| Guide | Use it for |
| --- | --- |
| [Ten-minute talk run of show](docs/TALK_10_MIN.md) | Timed speaker notes, stage cues, fallbacks, and a rehearsal scorecard |
| [Memory, state, and authority](docs/CONCEPTS.md) | The conceptual boundary and system-of-record model |
| [Manual refund demo](docs/REFUND_DEMO.md) | Multi-terminal setup, uncertain-effect beat, replay case, Stripe mode, and event history |
| [Permission state demo](docs/PERMISSION_DEMO.md) | Why remembered authorization is not current authorization |
| [Guided stage runner](docs/STAGE_GUIDE.md) | Each stage step, the simulation flags, live models, and `--real` cleanup |
| [Watch it in Temporal Web](docs/TEMPORAL_WEB.md) | Your own dev server, the port variant, what to check at each frame, and resetting between takes |
| [Expected output](docs/EXPECTED_OUTPUT.md) | The full stage transcript and Worker log |
| [Cost methodology](docs/COST.md) | Price basis, cost drivers, estimation method, and measuring tokens and dollars yourself |
| [When Event History grows](docs/HISTORY_GROWTH.md) | History growth, limits, claim check, External Storage, and continue-as-new |
| [How other products approach it](docs/COMPARISON.md) | The full product comparison with sources, and when you don't need Temporal |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Every error string, its cause, and its fix |
| [Architecture and code tour](docs/ARCHITECTURE.md) | The diagram walkthrough, full loop sketch, useful commands, repository map, and tests |

Every command entry point is in [Useful commands](docs/ARCHITECTURE.md#useful-commands);
run the tests with `uv run --extra dev pytest -q`.

## Acknowledgments

Thanks to Cecil for the review that shaped how this repository frames memory
and state.

## License

Released under the [MIT License](LICENSE).
