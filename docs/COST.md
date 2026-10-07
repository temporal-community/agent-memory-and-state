# Cost to run: prices and methodology

Back to the [README](../README.md). The per-pass tokens-and-dollars table is
in the README's [Cost to run](../README.md#cost-to-run). This page holds the
price basis, the model settings, how the measured and estimated numbers were
produced, what starting over and replay cost, an estimate at scale, the worst
case, what raises the cost, and how to measure a pass yourself.

## Prices

Prices are list prices, checked on 2026-09-29:

- Claude Sonnet 4.6: $3 per million input tokens and $15 per million output
  tokens ($0.30 cache read, $3.75 cache write; this code sets no cache
  control). [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- GPT-5.6 Luna: $0.20 per million input tokens ($0.02 cached, $0.25 cache
  write) and $1.20 per million output tokens. Reasoning tokens are billed as
  output. Prompt caching is automatic for prompts of at least 1,024 tokens.
  [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- Stripe test mode: $0. [Stripe test mode](https://docs.stripe.com/test-mode)
- Temporal: the local dev server is free. On Temporal Cloud, a pass is an
  estimated 20-165 billable Actions (1 start, 8-10 Activity starts, 2-3
  Signals, and 10-150 polled `stage_progress` Queries), which is under one cent
  at $50 per million Actions. This is counted from the code, not measured.
  [Temporal pricing](https://temporal.io/pricing)

## Model settings

With `--real-model`, both demos call the model through the same step
(`decide_next_step`; Demo 2 runs it inside the `agent_decide_next_step`
Activity), with the same settings:

- GPT-5.6 Luna (`gpt-5.6-luna`): Responses API, a required tool call,
  reasoning effort left at the model default, no output cap.
- Claude Sonnet 4.6 (`claude-sonnet-4-6`): `max_tokens=512`, forced tool
  choice, no extended thinking, no prompt caching.
- Both: provider SDK retries off and a 45 s client timeout. In Demo 2, Temporal
  retries each model turn up to 5 attempts, each with a 60 s Activity timeout.
  Demo 1 has no retry layer.

The default stage run and `--real` use a fixed policy in both demos instead of
a model.

## How these numbers were produced

- **GPT-5.6 Luna: measured**, 2026-10-02. One
  `stage --real --real-model --model-provider openai` take on `gpt-5.6-luna`,
  with the settings above and `LOG_MODEL_USAGE=1`, summed by
  `refund-demo usage`, which reports each demo apart:
  - Demo 1 (naive agent process): 4 model calls, 2,619 input tokens (0 cached)
    and 343 output tokens (87 of them reasoning), 2,962 tokens, $0.0009.
  - Demo 2 (Temporal Workflow): 4 model calls, 2,611 input and 335 output
    tokens (84 reasoning), 2,946 tokens, $0.0009.
  - The whole take: 8 model calls, 5,230 input and 678 output tokens, 5,908
    tokens, $0.0019.

  All at the 2026-09-29 list prices. The model sees amounts as dollars
  (`"$80.00"`), never cents. An earlier pass, on 2026-09-30, before Demo 1
  used the model and while prompts still showed cents, made the same 4 calls
  in Demo 2 (2,845 tokens, $0.0009).
- **Claude Sonnet 4.6: estimated**, 2026-09-29. Not run: no Claude pass has
  been logged. About 4 model calls per demo (the 2 intake questions don't call
  the model), about 5,400-6,900 input and 200-400 output tokens per demo, about
  $0.02-$0.03 per demo and $0.04-$0.05 per take. The call count comes from the
  code. The token counts were made by rebuilding the exact prompts with the
  repo's own code and converting at 2.5-4 characters per token; no tokenizer
  or paid call was used.
- **Default and `--real` stage runs: 0 model calls, 0 tokens, $0**, by design
  (deterministic policy in both demos; the code path makes no model calls).
- Prices were read from the providers' pricing pages on 2026-09-29.

<!-- After a measured Claude pass, replace the Claude estimates here and in
the README's cost table with the measured calls, tokens, dollars, and date. -->

## Starting over pays again; replay doesn't

An agent spends tokens on every pass. What durable execution changes is what a
crash costs.

- **Demo 1 start-over: measured**, 2026-10-02. The naive agent's live loop,
  run once more outside the stage with the same answers to the same point
  before Stripe, as the customer must after the process is gone: 4 more model
  calls, 2,623 input and 349 output tokens (97 reasoning), 2,972 tokens,
  $0.0009 more. On Claude, a start-over is an estimated 4 more calls, about
  5,600-7,300 more tokens, about $0.02-$0.03 more.
- **Demo 2 replay: measured**, same take. The new Worker read the 4 recorded
  model turns from Event History and made 0 model calls. All 4 calls happen
  before the Worker is killed, no usage record follows the kill, and Event
  History shows each agent turn once.
- **A call in flight is different.** A model call still running when a Worker
  dies runs again after its 60 s Activity timeout and can be billed again. On
  the stage path the kill lands after the last model call, so no call is in
  flight.

## At scale (estimate)

An agent serving 1M requests a month at the measured Demo 1 pass size uses
about 3B tokens (2,962 × 1M) and about $900 in model calls (1M × $0.0009, list
prices as of 2026-09-29). Every request that starts over pays its share again.

## Worst case (modeled)

Modeled from the code, not measured. None of these is a hard ceiling: your
request text is resent on every call, and the code sets no output cap for
OpenAI models.

| Run | Assumptions | Model calls | Tokens | Dollars |
| --- | --- | --- | --- | --- |
| Stage with Claude | Demo 2: 8 model turns × 5 Temporal attempts. Demo 1: 8 turns, 1 attempt each (no retry layer). About 2,000 input tokens per call (default request text), every call billed at the 512-token cap | 48 | about 96,000 input + 24,576 output | about $0.66 |
| Manual `refund-demo start` with Claude | 10 model turns × 5 attempts (no code-driven intake turns, no Demo 1); same assumptions | 50 | about 100,000 input + 25,600 output | about $0.68 |
| Stage with GPT-5.6 Luna | The same 48 calls; about 2,000 input and about 2,100 output plus reasoning tokens per call | 48 | about 96,000 input + 100,800 output | about $0.14 |

## What raises the cost

- **Retries.** In Demo 2, Temporal is the only retry layer (the provider SDK
  retries are off), and each model turn can run up to 5 attempts. Demo 1 has no
  retry layer, so a failed model call ends Demo 1 instead. Most retries follow a
  429, a 5xx, or a connection error, which usually return no billable
  response. A turn is billed twice when the provider generated a response the
  Worker never received: the 45 s client timeout fired first, or the Worker
  was lost mid-call.
- **More turns.** The loop allows 10 turns. On the stage path, 2 of them are
  code-driven intake questions.
- **Context growth.** Every call resends the full request and all
  observations. [When Event History grows](HISTORY_GROWTH.md) shows how fast
  that adds up in a long loop.
- **Reasoning tokens.** The code sets no reasoning effort or output cap for
  OpenAI models.
- **A different model.** `claude-sonnet-5-5`, `claude-opus-5-5`, and
  `claude-fable-5-1` reject the forced tool choice this code sends, so the run
  fails on its first model turn.
- **Takes.** Each live take runs the model in both demos, so it costs two
  passes; a Demo 1 start-over is one more.
- **The manual path.** `refund-demo start --dry-run` is free only when no model
  key is configured. With a key in `.env`, it calls the live model.

## Measure it yourself

The token log (opt-in) writes one JSON line per live model call: which agent
made it (`naive` for Demo 1, `temporal` for Demo 2), provider, model, input,
cached input, cache writes, output, reasoning, and timestamp. Prompt text and
API keys are never written. Export `LOG_MODEL_USAGE=1`, or put it in `.env`;
the stage's Worker and Demo 1's agent process inherit it.

```bash
LOG_MODEL_USAGE=1 uv run refund-demo stage --real-model --model-provider anthropic --workflow-id cost-claude-01
# The stage ends with a line such as:
#   Stage logs: .demo-state/stage-1a2b3c4d
# Summarize that folder (use your own stage-<token> folder name):
uv run refund-demo usage --state-dir .demo-state/stage-1a2b3c4d
```

Each stage run writes to its own `stage-<token>` folder, so one file is one
take: a Demo 1 pass and a Demo 2 pass. With no `--state-dir`,
`refund-demo usage` reads `DEMO_STATE_DIR` (`.demo-state` by default); if no
log is there, it prints the newest stage folder as a ready-to-run command.

The summary reports Demo 1 and Demo 2 apart. For each, it prints calls;
uncached input, cached input, cache writes, and output tokens with dollars at
list prices as of 2026-09-29; reasoning tokens (already inside output, so never
added twice); and the total. It labels the tokens as measured, since they are
what each API reported. For a model without a list price, pass `--input-price`
and `--output-price` (USD per million tokens) together; they price cached input
and cache writes at the input price.

Only calls that returned a response are logged. Rate-limit, server, timeout,
and connection errors are raised before a response exists. If a Worker is
killed after the provider responds but before the line is written, that call
is missing from the file, so check a kill take against the provider's usage
console. Record the model, the [model settings](#model-settings), and the date
with any measured figure.
