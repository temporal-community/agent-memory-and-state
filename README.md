# Agent Memory and State

<div align="center">

[![MIT License](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Temporal Python SDK](https://img.shields.io/badge/Temporal_Python_SDK-1.30%2B-635bff)](https://github.com/temporalio/sdk-python)
[![Stripe](https://img.shields.io/badge/Stripe-test_mode_only-635bff?logo=stripe&logoColor=white)](https://docs.stripe.com/test-mode)
[![uv](https://img.shields.io/badge/run_with-uv-de5fe9)](https://docs.astral.sh/uv/)

</div>

This repo shows what memory and execution state each do for an AI agent, and
Temporal's role: it keeps track of the execution state outside the agent's process. The
agent is a plain Python loop with no agent framework, so the boundary between
the two stays visible.

**What's covered:**

- [The demo](#see-the-idea-in-15-seconds): both agents, side by side.
- [Run the guided demo](#run-the-guided-demo): `uv run refund-demo stage`
  after setup; no keys by default.
- [Same crash, two outcomes](#same-crash-two-outcomes): the video's key moment.
- [Memory and execution state](#memory-and-execution-state): what each holds.
- [Temporal's role and limits](#what-this-demo-proves): Temporal keeps where
  the work stands; Stripe, not Temporal, says whether money moved.
- [Cost to run](#cost-to-run): a measured Demo 1 pass on GPT-5.6 Luna is 4 model
  calls, 2,962 tokens, $0.0009. Starting over pays it again; replay makes 0 calls.
- [Gotchas](#when-event-history-grows-claim-check-and-continue-as-new): Event
  History grows every turn; a claim check and continue-as-new keep it in bounds.
- [Takeaways](#takeaways): the three lines the demo ends on.
- [Explore the demos](#explore-the-demos): a page in `docs/` for each topic.

**What happens to an AI agent's in-flight work when its process dies?**

The demo kills a customer-support refund agent one step before it refunds
the customer. The failure mode is **lost loop position**. By then the agent has
asked the customer two questions, looked up the order and the customer's
refund history, and chosen `issue refund`. When the naive agent's process dies,
that progress is lost, and the new process has no way to get it back, so the
customer has to start the return again. The durable agent runs the same steps
as a Temporal Workflow. A new Worker rebuilds the loop from Event History and
resumes at `issue refund` without repeating a question.

![The durable demo's stage screen right after its Temporal Worker was killed. The left pane, Temporal Worker, reads WORKER GONE: its in-memory loop is gone, and Temporal still has the saved loop. A dim note says the demo stops the Worker here, before the refund reaches Stripe. The right pane, What Survives, shows what was read from Temporal just now: customer answers 2, completed lookups 2, next action issue refund. Below it, the offline ledger (Stripe stand-in) shows payment PAID and refund none.](assets/durable-saved.png)

**Last verified: 2026-10-02:** offline `stage` (the new Worker completed the
refund in the ledger), `stage --real --real-model --model-provider openai` on
GPT-5.6 Luna (the new Worker's refund returned `succeeded` from Stripe test
mode), tests, and lint. In both runs, Demo 1 told the customer to start over and
Demo 2 resumed at `issue refund` without repeating a question ([expected output](docs/EXPECTED_OUTPUT.md)).
Not re-run: `--real` alone and `--simulate-stripe-*` (last verified 2026-10-01).
The Claude path has not been run.

**What is real and what is staged:**

- **Real:** each kill is a SIGKILL. **Stand-ins by default:** one fixed policy
  and an offline ledger (0 tokens, $0); `--real` and `--real-model` swap in
  Stripe test mode and a live Claude or OpenAI model.
- **Staged:** the runner keeps its own copy of your Demo 1 answers for display
  and replays them into the durable run as Signals, and says so on screen. The
  new agent process never gets them.
- **Staged:** a stage-only `release` Signal holds the Workflow before the
  refund, so the kill lands at the same point in every default take. A real
  Worker dies wherever it dies, and a real app must keep or derive the Workflow
  ID that the runner holds for you.

## See the idea in 15 seconds

![Animated comparison: the naive agent loses its answers and restarts, while the Temporal-backed agent resumes the saved loop](assets/demo-reel.gif)

[Watch or download the MP4 version](assets/demo-reel.mp4), or
[view the presentation deck: *Agentic Memory and State*, August 2026 version (PDF)](docs/agentic-memory-and-state.pdf).
Each step, side by side: [what the runner does](docs/STAGE_GUIDE.md#what-the-runner-does).

## Run the guided demo

You need Python 3.11+, the [Temporal CLI](https://docs.temporal.io/cli)
(tested 1.6.2), and [uv](https://docs.astral.sh/uv/) (tested 0.11.8). The
default run needs no keys; fill in `.env` only for `--real` or `--real-model`
(exported shell variables win). Expected output: [Same crash, two outcomes](#same-crash-two-outcomes).

```bash
git clone https://github.com/temporal-community/temporal-ai-agent-memory-state-stripe.git
cd temporal-ai-agent-memory-state-stripe
uv sync --extra dev --extra tui
test -e .env || cp .env.example .env   # keeps an .env you already have
uv run refund-demo stage               # fullscreen; press Enter at each prompt
```

### Make targets

| Target (`make` lists them; `make -n <target>` prints one) | Runs | Notes |
| --- | --- | --- |
| `make setup` | `uv sync --extra dev --extra tui` | Keeps both extras; a plain `uv sync` removes the Rich stage view |
| `make run` | `uv run refund-demo stage` | The key-free path: fixed policy, offline ledger, 0 model calls |
| `make run-real` | `uv run refund-demo stage --real` | Needs a Stripe `sk_test_` or `rk_test_` key; creates Stripe test objects |
| `make failure` | `uv run refund-demo stage --simulate-stripe-timeout` | Offline. The Worker is killed while `issue_refund` is in flight, and a new Worker runs attempt 2 |
| `make reset` | `uv run refund-demo cleanup`, then prints the manual reset steps | Refunds only leftover demo test payments, and only with a Stripe test key. Deletes and stops nothing |
| `make test` | `uv run --extra dev pytest -q` | Offline. Passing ends with `N passed` and exit code 0 |
| `make lint` | `uv run --extra dev ruff check .` and `uv run --extra dev ruff format --check .` | Offline. Passing prints `All checks passed!` and `N files already formatted` |
| `make usage` | `uv run refund-demo usage` | Sums a pass logged with `LOG_MODEL_USAGE=1`, or names the newest stage log |

### Choose the stage path

| Goal | Command | Model tokens and dollars per take (both demos) |
| --- | --- | --- |
| Rehearse offline, or against Stripe test mode | `uv run refund-demo stage`, or add `--real` | 0 tokens, $0 |
| Show a real Activity retry after a simulated Stripe timeout | `uv run refund-demo stage --real --simulate-stripe-timeout` | 0 tokens, $0 |
| Let a live model choose the lookups and the decision in both demos | `uv run refund-demo stage --real-model --model-provider anthropic` (or `openai`) | GPT-5.6 Luna: 8 calls, 5,908 tokens, $0.0019, measured 2026-10-02. Claude Sonnet 4.6: about 8 calls, 11,200-14,600 tokens, $0.04-$0.05, estimated |

A live model needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`, or `OPENAI_API_KEY`
and `OPENAI_MODEL` (`gpt-5.6-luna` for the measured pass). `--real` rejects live
Stripe keys; the [stage guide](docs/STAGE_GUIDE.md) covers cleanup.

**Watch it in Temporal Web.** Start `temporal server start-dev` in another
terminal first, so Temporal Web (<http://localhost:8233>) outlives the stage,
and use a new `--workflow-id` per take. After the kill, the Workflow is
`Running` with no Worker, which is normal. See
[what to check at each frame](docs/TEMPORAL_WEB.md#what-to-check-at-each-frame).

## Same crash, two outcomes

Both agents are stopped right after choosing `issue refund`. Only the durable
one resumes: the new Worker "picks up from the next step it was supposed to
take in that loop, which is to issue the refund," as the video puts it. Key
lines from a default run, in order ([full transcript](docs/EXPECTED_OUTPUT.md)):

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

The naive answer is not wrong: memory and Stripe are both useful. The contrast
is whether the autonomous work itself still has a position.

| Process-local loop | Durable execution |
| --- | --- |
| The answers and active loop disappear; Stripe only says paid with no refund. | Temporal retains completed observations and `Next action: issue refund`; the new Worker continues without repeating questions. |
| ![The new agent process has lost the return answers and asks the customer to start over](assets/naive-loop-restarts.png) | ![The new Temporal Worker completes the refund without repeating questions or restarting the loop](assets/durable-recovered.png) |

## Videos

**Temporal & AI Series: Agent Memory & State** (video and playlist links added
after publish) ran `uv run refund-demo stage --real --real-model
--model-provider openai` (OpenAI and Stripe test keys; `make run` is the
key-free version). Chapters (timestamps after the final cut): Hook and Demo 1
(the agent loses the refund) · What just happened · The agent loop and agency
levels · Context, memory, and state · Memory kinds · Facts have owners · What
Temporal is · Demo 2 (the same crash, with Temporal) · Replay, not redo ·
History growth: claim check and continue-as-new · The trade-off · Cost to run ·
Memory vs execution state · Run it yourself.

## Memory and execution state

An agent needs all of these, and they do different jobs. Only context lives
inside the loop. Long-term memory and state live outside it.

| | What it helps with | In this demo | Where to find it |
| --- | --- | --- | --- |
| **Context** (working memory) | What the model sees for this one decision. The loop sends it again on every turn | The refund request, the customer's two answers, and the lookups so far: order 1234 and the refund history of the demo customer, Nyghtowl | `working_memory`: a list in the naive agent's process (`naive_refund.py`), or a Workflow field (`workflow.py`) that replay rebuilds. It is the input of each `agent_decide_next_step` Activity in Event History |
| **Long-term memory** (a memory store) | What the agent carries across runs: past cases (episodic), facts it looks up (semantic), and how-to such as skill files (procedural) | None, on purpose. On screen, lookups are tagged `(memory)` because they stand in for retrieval, but they read fixture records, and nothing is saved across runs | Your store: a vector store, a knowledge base, or memory files |
| **Execution state** | Where the work stands: which steps finished and what runs next, so the work can continue after a crash without redoing it | 2 answers, 2 lookups (3 when a live model also checks the refund policy), next action `issue refund` | Temporal: the Workflow's Event History in the Temporal UI (http://localhost:8233), or `uv run refund-demo inspect <workflow-id>` |
| **Effect state** | Whether the side effect really happened | Whether Stripe holds a refund for the payment | Stripe: the Dashboard in test mode, where the refund's metadata carries `temporal_workflow_id` and `temporal_idempotency_key` (offline: the ledger) |

**Facts have owners.** A memory store could bring back the answers, but not
which step runs next or whether the refund went out: memory says what the agent
believed; the owner's record says what happened, and wins when they disagree.
An agent that trusts a remembered "not refunded yet" can refund twice. See
[Memory, state, and authority](docs/CONCEPTS.md). The stage leads with the crash
before the refund because the customer's cost is visible; the
[manual walkthrough](docs/REFUND_DEMO.md) covers a crash after Stripe commits.

**How it works.** The stage runner ([`stage.py`](src/refund_agent/stage.py))
drives the naive process ([`naive_refund.py`](src/refund_agent/naive_refund.py)),
then a Workflow ([`workflow.py`](src/refund_agent/workflow.py)), and kills and
replaces its Worker ([`worker.py`](src/refund_agent/worker.py)). No client
retries on its own, so Temporal owns every retry. [Architecture](docs/ARCHITECTURE.md)
has the diagram, the [loop](docs/ARCHITECTURE.md#the-agent-loop-is-ordinary-python), and [retries](docs/ARCHITECTURE.md#temporal-owns-retries).

## What this demo proves

1. **The agent is a plain loop:** two questions, the lookups, one decision.
2. **Without execution state, a crash sends the customer back to the start.**
3. **With Temporal, the work picks up where it stopped.** A new Worker replays
   Event History (answers as `customer_answer` Signals, model turns and lookups
   as Activities), rebuilds `working_memory`, and continues at `issue refund`
   without calling the finished steps again. Replay, not redo; in the video:
   "It didn't redo all those steps. It just replayed it."
4. **Temporal records the attempt; Stripe owns the outcome.** Every retry in a
   run sends one idempotency key (`durable-refund-` plus the SHA-256 of
   `<workflow_id>:<run_id>`), so Stripe makes one refund. Temporal doesn't
   decide what the agent does or make the model right; evals and guardrails do.

## Cost to run

The default run and `--real` use a fixed policy: 0 calls, 0 tokens, $0. With
`--real-model`, both demos call the model through the same step, priced at list
prices as of 2026-09-29. **Starting over pays again; replay doesn't.**

| Run | Model and settings | Calls | Tokens | Dollars | Basis |
| --- | --- | --- | --- | --- | --- |
| Demo 1 pass | `gpt-5.6-luna`, Responses API, default reasoning, no output cap | 4 | 2,962: 2,619 in + 343 out (87 reasoning) | $0.0009 | **Measured**, 2026-10-02 |
| Demo 1 start-over | Same | 4 more | 2,972: 2,623 in + 349 out | $0.0009 more | **Measured**, 2026-10-02 |
| Demo 2 pass | Same | 4, before the kill | 2,946: 2,611 in + 335 out | $0.0009 | **Measured**, 2026-10-02 |
| Demo 2 replay after the kill | Same | 0 | 0 | $0.00 | **Measured**, 2026-10-02 |
| Each demo on Claude | `claude-sonnet-4-6`, `max_tokens=512`, forced tool choice, no extended thinking, no caching | about 4 | about 5,400-6,900 in + 200-400 out | about $0.02-$0.03 | **Estimated**, 2026-09-29; not run |

Retries (up to 5 attempts per turn), more turns, longer requests, reasoning
tokens, and a call in flight at a crash raise the cost. [Cost methodology](docs/COST.md)
has the sources, an [estimate at 1M requests a month](docs/COST.md#at-scale-estimate),
the [worst case](docs/COST.md#worst-case-modeled), and how to log a pass.

## When Event History grows: claim check and continue-as-new

Each turn sends all of `working_memory` to the model step again, and each send
is saved, so history grows with the square of the turn count. Server defaults
allow 2 MB per payload and 50 MB per run. This demo stops at `MAX_TURNS = 10`,
under 7 KB of payloads.

- **Claim check, for one big result:** keep the data in your store and only a
  small key in Event History.
- **Continue-as-new, for a long run:** a fresh history, same Workflow ID. Roll
  over only before the refund here: its idempotency key uses the Run ID.

[Deep dive](docs/HISTORY_GROWTH.md): limits, a [measured example](docs/HISTORY_GROWTH.md#measured-in-the-fleet-demo),
and a [continue-as-new sketch](docs/HISTORY_GROWTH.md#what-continue-as-new-looks-like-sketch).

## What it is not

- **Not a production refund service.** No authentication, production database,
  web application, multi-agent orchestration, or hardening; fixture lookups.
  It runs on a local dev server with no TLS or API-key options, not Temporal Cloud.
- **Not exactly-once.** One request can mean two calls and still one refund,
  because both calls share one idempotency key.
- **The naive side is not a Temporal Worker.** It runs the same decision step
  with no Temporal and no retry layer, so the screens call it the agent process.
  Not every Stripe line on screen reads Stripe: see [which lines do](docs/STAGE_GUIDE.md#which-lines-read-stripe).
- **Not a memory store.** Long-term memory is a store you own, and [Event History is bounded](#when-event-history-grows-claim-check-and-continue-as-new);
  see [how a store can work with Temporal](docs/CONCEPTS.md#temporal-is-not-a-memory-store).

**Trade-offs.** Temporal earns its place when work outlives a process or a
deploy, waits a long time on people or systems, or retries real side effects.
Its costs: Event History holds customer data (plan retention, add an encryption
codec), someone runs the service or pays for Temporal Cloud, and Workflow code
must be deterministic and versioned. See
[other approaches](docs/COMPARISON.md#four-approaches) and [when you don't need Temporal](docs/COMPARISON.md#when-you-dont-need-temporal).

## Troubleshooting

Stage errors print as `STAGE | <message>`; other failures show in Temporal Web
and `.demo-state/stage-<token>/worker.log`. Most often, Temporal is not
reachable (install the Temporal CLI, or run `temporal server start-dev`), port
7233 or 8233 is taken (use the [port variant](docs/TEMPORAL_WEB.md#start-your-own-dev-server)),
or a live or malformed `STRIPE_API_KEY` in `.env` stops the Worker, even
offline. The [full table](docs/TROUBLESHOOTING.md) has every error, its cause,
and its fix.

## Explore the demos

| Use it for | Docs |
| --- | --- |
| Presenting: timed notes, each stage step and flag, what to check in the UI | [Ten-minute talk](docs/TALK_10_MIN.md), [stage guide](docs/STAGE_GUIDE.md), [Temporal Web](docs/TEMPORAL_WEB.md) |
| The ideas: memory and state, remembered vs current authorization, other products | [Concepts](docs/CONCEPTS.md), [permission demo](docs/PERMISSION_DEMO.md), [comparison](docs/COMPARISON.md) |
| The code: diagram, code tour, commands, tests, multi-terminal walkthrough | [Architecture](docs/ARCHITECTURE.md), [manual refund demo](docs/REFUND_DEMO.md) |
| Checking a run: full transcript, Worker log, errors, tokens and dollars, history limits | [Expected output](docs/EXPECTED_OUTPUT.md), [troubleshooting](docs/TROUBLESHOOTING.md), [cost](docs/COST.md), [history growth](docs/HISTORY_GROWTH.md) |

## Takeaways

The demo ends on these, in the stage's closing frame; the third is also the
video's closing slide:

- **Without Temporal, the customer had to start over.** The agent's answers
  and next step lived only in its process, and they died with it.
- **With Temporal, a new Worker picked up at the saved next action,**
  `issue refund`, without asking the customer again.
- **Memory helps reasoning continue. Temporal helps the operation continue.**
  Stripe, not either of them, knows whether money moved.

And two things to keep in mind when you build your own:

- **Durable execution can run a step more than once.** Give every side effect
  an idempotency key that the receiving system checks, as the refund does here.
- **A crash that starts over pays for the model calls again.** Replaying from
  Event History doesn't; only a call in flight at the crash can bill twice.

## Resources

- **As presented.** The September 2026 talk ran the code tagged
  [`as-presented-2026-09`](https://github.com/temporal-community/temporal-ai-agent-memory-state-stripe/tree/as-presented-2026-09).
  `main` keeps moving; link the tag when you cite the talk.
- **Further reading:** [Temporal docs](https://docs.temporal.io), the
  [Python SDK](https://github.com/temporalio/sdk-python),
  [continue-as-new](https://docs.temporal.io/workflow-execution/continue-as-new),
  [External Storage](https://docs.temporal.io/external-storage), and
  [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests).
- **For your coding agent:** the [Temporal developer skill](https://github.com/temporalio/skill-temporal-developer):
  `npx skills add temporalio/skill-temporal-developer`.

<!-- TODO before publishing: video URL with UTM and the Temporal & AI Series
playlist URL (in Videos), related videos (human-in-the-loop, multi-agent
handoffs), the blog post URL if there is one, and Temporal Cloud credits
when available. -->

## Acknowledgments

Thanks to Cecil for the review that shaped how this repository frames memory
and state.

## License

Released under the [MIT License](LICENSE).

---

**Ready to try this in your own agent?** [Get started here](https://t.mp/ai-video-cta-004).
