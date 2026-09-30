# Cost to run: prices and methodology

Back to the [README](../README.md). The per-pass tokens-and-dollars table is
in the README's [Cost to run](../README.md#cost-to-run). This page holds the
price basis, what raises the cost, how the measured and estimated numbers
were produced, and how to measure a pass yourself.

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

## What raises the cost

- **Retries.** Temporal is the only retry layer (the provider SDK retries are
  off), and each model turn can run up to 5 attempts. Most retries follow a
  429, a 5xx, or a connection error, which usually return no billable
  response. A turn is billed twice when the provider generated a response the
  Worker never received: the 45 s client timeout fired first, or the Worker
  was lost mid-call.
- **More turns.** The loop allows 10 turns. On the stage path, 2 of them are
  code-driven intake questions.
- **Context growth.** Every call resends the full request and all
  observations.
- **Reasoning tokens.** The code sets no reasoning effort or output cap for
  OpenAI models.
- **A different model.** `claude-sonnet-5-5`, `claude-opus-5-5`, and
  `claude-fable-5-1` reject the forced tool choice this code sends, so the run
  fails on its first model turn.
- **Takes.** Each live take is another pass.
- **The manual path.** `refund-demo start --dry-run` is free only when no model
  key is configured. With a key in `.env`, it calls the live model.

## How these numbers were produced

- **GPT-5.6 Luna: measured**, 2026-09-30. One
  `stage --real-model --model-provider openai` pass on `gpt-5.6-luna`
  (Responses API, reasoning effort left at the model default, no output cap)
  with `LOG_MODEL_USAGE=1`, summed by `refund-demo usage`: 4 model calls,
  2,492 input tokens (0 cached) and 353 output tokens (114 of them reasoning),
  2,845 tokens in all, $0.0009 at the 2026-09-29 list prices. The kill +
  replay added 0 model calls: all 4 calls happen before the Worker is killed,
  and Temporal replays their recorded results. Earlier, 31 local live
  rehearsals each made the same four model calls with no retries.
- **Claude Sonnet 4.6: estimated**, 2026-09-29. Not run: no Claude pass has
  been logged. The call count comes from the code. The token counts were made
  by rebuilding the exact prompts with the repo's own code and converting at
  2.5-4 characters per token; no tokenizer or paid call was used.
- **Default and `--real` stage runs: 0 model calls, 0 tokens, $0**, by design
  (deterministic policy; the code path makes no model calls).
- Prices were read from the providers' pricing pages on 2026-09-29.

## Measure it yourself

The token log (opt-in) writes one JSON line per live model call: provider,
model, input, cached input, cache writes, output, reasoning, and timestamp.
Prompt text and API keys are never written. Export `LOG_MODEL_USAGE=1`, or put
it in `.env`; the stage's Worker inherits it.

```bash
LOG_MODEL_USAGE=1 uv run refund-demo stage --real-model --model-provider anthropic --workflow-id cost-claude-01
# The stage ends with a line such as:
#   Stage logs: .demo-state/stage-1a2b3c4d
# Summarize that folder (use your own stage-<token> folder name):
uv run refund-demo usage --state-dir .demo-state/stage-1a2b3c4d
```

Each stage run writes to its own `stage-<token>` folder, so one file is one
pass. With no `--state-dir`, `refund-demo usage` reads `DEMO_STATE_DIR`
(`.demo-state` by default); if no log is there, it prints the newest stage
folder as a ready-to-run command.

The summary prints calls; uncached input, cached input, cache writes, and
output tokens with dollars at list prices as of 2026-09-29; reasoning tokens
(already inside output, so never added twice); and the total. It labels the
tokens as measured, since they are what each API reported. For a model without
a list price, pass `--input-price` and `--output-price` (USD per million
tokens) together; they price cached input and cache writes at the input price.

Only calls that returned a response are logged. Rate-limit, server, timeout,
and connection errors are raised before a response exists. If a Worker is
killed after the provider responds but before the line is written, that call
is missing from the file, so check a kill take against the provider's usage
console. Record the model, the settings listed in the README's cost table, and
the date with any measured figure.
