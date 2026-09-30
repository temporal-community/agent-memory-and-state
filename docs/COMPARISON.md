# How other products approach it

Back to the [README](../README.md#how-other-products-approach-it).

Most of the products below are memory products (what the agent knows) or
transcript stores. Several also ship execution state for their own runtime.
This demo is about that execution-state layer, with no framework. Each row is
scoped to the linked pages as read on 2026-09-29.

| Product and feature | What it keeps | Who resumes after a crash | Compared with this demo |
| --- | --- | --- | --- |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/checkpointers) (open source): checkpointers and Store | Graph state per `thread_id` at every super-step, including the next node; the Store holds long-term memory across threads | Your code re-invokes the graph with the same `thread_id` | The closest open-source analogue. With a durable checkpointer such as Postgres, a crash after the decision can resume at the next node. The [interrupts docs](https://docs.langchain.com/oss/python/langgraph/interrupts) say a resumed node runs again from its start, so side effects before the interrupt should be idempotent. `InMemorySaver` loses its checkpoints on restart, like the naive agent. |
| [LangSmith Deployment](https://docs.langchain.com/langsmith/agent-server) (Agent Server) | Runs on a durable task queue, with checkpoints in Postgres | Per [LangChain](https://www.langchain.com/blog/runtime-behind-production-deep-agents), another queue worker picks the run up from its latest checkpoint | For a LangGraph graph deployed there, this covers the crash-and-resume step shown here. Temporal also works without a framework, sets retry and heartbeat policy per Activity, and has a [LangGraph plugin](https://temporal.io/blog/temporal-langgraph-plugin-durable-execution). |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/sessions/): Sessions and RunState | Conversation items per session; a serialized `RunState` for a run paused at an [approval interruption](https://openai.github.io/openai-agents-python/human_in_the_loop/) | Your code restores the `RunState` and runs it again | A Session restores the customer's answers. Resuming at an already-chosen action uses a `RunState` saved at an interruption you design, or a durable-execution integration such as [Temporal's](https://docs.temporal.io/develop/python/integrations/openai-agents). |
| [Letta](https://docs.letta.com/guides/core-concepts/stateful-agents) | Stateful agents on the Letta server, with core, recall, and archival memory in its database | A client reconnects to a [background run](https://docs.letta.com/v1-sdk/messages/long-running) by run and sequence ID | Keeps what the agent knows on the server, across client crashes. An external effect such as a Stripe refund still needs its own idempotency key inside the tool, as in this demo. |
| [Mem0](https://docs.mem0.ai/core-concepts/memory-types) | Memories that an LLM extracts and reconciles, searchable by relevance and scoped by user, agent, or run | n/a (a memory layer) | Suited to facts that carry across sessions, such as a customer's preferences. It stores extracted memories, not an execution position, so here it would sit beside the loop, called from an Activity. |
| [Google ADK](https://adk.dev/runtime/resume/): Sessions, State, Memory, and Resume | A session event log with scoped state, a MemoryService, and Resume's log of completed agent steps | The client re-invokes with the `invocation_id` | Draws nearly the same line between state and memory. The Resume docs say tools may run more than once on resume, the same reason this demo uses an idempotency key. |
| [Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool): memory tool, context editing, and compaction | Client-side `/memories` files that the model writes and your app stores; context-window management | Your app, from the files the model wrote | A good fit for coding agents, where git owns the effects. For a refund, a crash between Stripe accepting it and the model writing its note is the "lone done marker" gap in [CONCEPTS.md](CONCEPTS.md). Context editing and compaction manage what fits in the window. |
| [Postgres job table](https://brandur.org/idempotency-keys) (idempotency-key pattern) | One row per request with a `recovery_point` | A completer process you write | Legitimate execution state. You build the leases, retries, timeouts, durable waits, and inspection. Fixed recovery points suit a fixed pipeline; this loop's steps are chosen by a policy or model at run time. |
| [DBOS](https://docs.dbos.dev/integrations/openai-agents) | Checkpointed steps in Postgres or SQLite | The app resumes from the last completed step | The same category as Temporal. DBOS runs as a library in your app, with no separate orchestration server. |
| Temporal (this demo) | Event History of Signals and Activity inputs and results; Workflow fields rebuilt by replay | Any Worker polling the task queue | Framework-agnostic, with per-Activity retry and heartbeat policies, durable waits, and a history UI. The costs: you run a service, Workflow code must be deterministic and versioned, and history is bounded. |

One line to remember: persisted chat history lets a new process decide again.
Durable execution resumes the decision the agent already made. And Stripe, not
either of them, says whether money moved.

## When you don't need Temporal

- **Only the conversation matters.** If there is no irreversible side effect, a
  session store is enough.
- **You need personalization.** That is a memory problem.
- **There is one irreversible call, retried synchronously with the same
  idempotency key.** The effect owner already makes the retry safe.
- **The agent is a coding agent.** Git owns the effects, and redoing a step is
  cheap.
- **Your runtime already provides execution state.** LangSmith Deployment, ADK
  Resume, and DBOS are examples.
- **It's a short, fixed pipeline on Postgres.** A job table works if you are
  willing to own the completer.
