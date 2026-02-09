# Architecture

This document describes the internal architecture of nanobot — how the modules work together, the data flow, and the design patterns used throughout the codebase.

## High-Level Overview

nanobot is built around an **agentic loop** pattern: a user message flows in through a channel, the agent loop calls an LLM, the LLM may request tool executions, and the loop repeats until a final text response is produced.

```
┌─────────────────────────────────────────────────────────────┐
│                        User Message                         │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Channels (Telegram, Discord, WhatsApp, Feishu, DingTalk)   │
│  nanobot/channels/                                           │
└────────────────────────────┬─────────────────────────────────┘
                             │ publish_inbound()
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Message Bus     nanobot/bus/queue.py                        │
│  (async queues decoupling channels from agent)               │
└────────────────────────────┬─────────────────────────────────┘
                             │ consume_inbound()
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent Loop      nanobot/agent/loop.py                       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  1. Build context (system prompt + history + message)  │  │
│  │     └─ ContextBuilder  (nanobot/agent/context.py)      │  │
│  │        ├─ Bootstrap: AGENTS.md, SOUL.md, USER.md, etc. │  │
│  │        ├─ Memory: MEMORY.md + daily notes              │  │
│  │        └─ Skills: metadata + loaded skill content      │  │
│  │                                                        │  │
│  │  2. Call LLM                                           │  │
│  │     └─ LiteLLMProvider (nanobot/providers/)            │  │
│  │        └─ Provider Registry → env vars → litellm       │  │
│  │                                                        │  │
│  │  3. If tool_calls → execute tools → add results → go 2│  │
│  │     └─ ToolRegistry  (nanobot/agent/tools/)            │  │
│  │                                                        │  │
│  │  4. Return final text response                         │  │
│  └────────────────────────────────────────────────────────┘  │
└────────────────────────────┬─────────────────────────────────┘
                             │ publish_outbound()
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Message Bus → dispatch to channel subscriber                │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Channel sends response back to user                         │
└──────────────────────────────────────────────────────────────┘
```

## Module Breakdown

### Agent Core (`nanobot/agent/`)

The agent core is the brain of nanobot.

#### `loop.py` — Agent Loop

The `AgentLoop` class orchestrates message processing:

- **`run()`** — Infinite loop that consumes messages from the bus.
- **`_process_message(msg)`** — Processes a single message through the agentic loop:
  1. Retrieves or creates a session for the user.
  2. Calls `ContextBuilder.build_messages()` to assemble the full prompt.
  3. Calls `LiteLLMProvider.chat()` to get an LLM response.
  4. If the response contains `tool_calls`, executes each tool via `ToolRegistry` and feeds results back to the LLM.
  5. Repeats steps 3–4 until no more tool calls (or `max_tool_iterations` is reached).
  6. Publishes the final text response to the outbound bus.
- **`process_direct(message)`** — Bypasses the bus for CLI and cron invocations.

#### `context.py` — Context Builder

`ContextBuilder` assembles the system prompt and message history:

- **System prompt** is built from (in order):
  1. Identity string ("You are nanobot...")
  2. Bootstrap files from workspace: `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`
  3. Memory context: long-term `MEMORY.md` + recent daily notes
  4. Skills: always-loaded skills (full content) + available skills (metadata summary)
- **Messages** combine the system prompt with session history and the current user message.
- **Media handling**: Images are base64-encoded and sent as vision content blocks.

#### `memory.py` — Memory Store

File-based persistence for agent memory:

- **Daily notes**: `workspace/memory/YYYY-MM-DD.md` — append-only daily log.
- **Long-term memory**: `workspace/memory/MEMORY.md` — persistent knowledge.
- **`get_memory_context()`** returns formatted memory for the system prompt.

#### `skills.py` — Skills Loader

Loads modular skill packages that teach the agent specific procedures:

- Scans `nanobot/skills/` (bundled) and `workspace/skills/` (user-defined).
- Each skill has a `SKILL.md` with YAML frontmatter (name, description, always flag) and markdown instructions.
- **Progressive disclosure**: Only metadata goes in the system prompt; full content is loaded on demand.

#### `subagent.py` — Subagent Manager

Manages background task execution via the `spawn` tool:

- Spawns a separate agent loop to handle a task independently.
- Reports back to the user when done.

#### `tools/` — Built-in Tools

All tools extend an abstract `Tool` base class:

```python
class Tool(ABC):
    name: str               # Tool identifier
    description: str        # Description for the LLM
    parameters: dict        # JSON Schema for parameters
    async execute(**kwargs)  # Tool implementation
```

**Registered tools:**

| Tool | File | Description |
|------|------|-------------|
| `read_file` | `file_tools.py` | Read file contents |
| `write_file` | `file_tools.py` | Write/create files |
| `edit_file` | `file_tools.py` | Search-and-replace in files |
| `list_dir` | `file_tools.py` | List directory contents |
| `exec` | `exec_tool.py` | Execute shell commands (with safety checks) |
| `web_search` | `web_tools.py` | Search the web (Brave API) |
| `web_fetch` | `web_tools.py` | Fetch and extract URL content |
| `message` | `message_tool.py` | Send message to user |
| `spawn` | `spawn_tool.py` | Spawn background subagent |
| `cron` | `cron_tool.py` | Schedule tasks |

Tools are registered in `AgentLoop._register_default_tools()` and presented to the LLM as OpenAI-format function definitions via `ToolRegistry.to_schemas()`.

---

### Providers (`nanobot/providers/`)

#### `registry.py` — Provider Registry

The single source of truth for LLM provider metadata. Each provider is a `ProviderSpec`:

```python
ProviderSpec(
    name="deepseek",                     # Config field name
    keywords=("deepseek",),              # Model name keywords for auto-matching
    env_key="DEEPSEEK_API_KEY",          # Environment variable for LiteLLM
    display_name="DeepSeek",             # Shown in status output
    litellm_prefix="deepseek",           # Model prefix: model → deepseek/model
    skip_prefixes=("deepseek/",),        # Don't double-prefix
)
```

Key lookup functions:
- **`find_by_model(model)`** — Matches a provider by checking if any keyword appears in the model name.
- **`find_gateway(api_key, api_base)`** — Detects gateway providers (OpenRouter, AiHubMix) by key prefix or URL.
- **`find_by_name(name)`** — Direct lookup by config field name.

#### `litellm_provider.py` — LLM Provider

`LiteLLMProvider` wraps the `litellm` library:

1. **`_setup_env()`** — Sets environment variables from the registry spec and config.
2. **`_resolve_model(model)`** — Applies prefix logic (e.g., `deepseek-chat` → `deepseek/deepseek-chat`).
3. **`chat(messages, tools)`** — Calls `litellm.acompletion()` with the resolved model and tools.
4. **`_parse_response()`** — Extracts text, tool calls, reasoning content, and token usage.

#### `hybrid_router.py` — Hybrid Router

`HybridRouterProvider` intelligently routes requests between a local model (vLLM/Ollama) and a remote API model:

**Workflow:**

```
User Message
      │
      ▼
┌───────────────────────────────────────┐
│   1. Local model judges difficulty   │
│      (returns score 0.0–1.0)          │
└────────────┬──────────────────────────┘
             │
             ├─ score ≤ threshold ────► Local model handles task
             │
             └─ score > threshold ────► ┌────────────────────────────┐
                                         │ 2. Local model sanitises   │
                                         │    PII (remove names,      │
                                         │    emails, phone numbers)  │
                                         └──────────┬─────────────────┘
                                                    │
                                                    ▼
                                         ┌────────────────────────────┐
                                         │ 3. API model processes     │
                                         │    sanitised request       │
                                         └────────────────────────────┘
```

**Key methods:**
- **`chat()`** — Routes the request based on difficulty score.
- **`_judge_difficulty()`** — Calls local model with a classification prompt to get a difficulty score.
- **`_sanitise_messages()`** — Strips PII from all user messages using the local model.

**Benefits:**
- **Cost efficiency**: Easy tasks (greetings, simple questions) stay local.
- **Privacy protection**: PII is removed before sending to external APIs.
- **Quality**: Complex tasks leverage powerful API models.

**Configuration fields** (see `HybridRouterConfig` in `config/schema.py`):
- `enabled`: Enable/disable hybrid routing
- `localProvider`: Config key of local provider (e.g., "vllm", "ollama")
- `localModel`: Model name for local inference
- `apiProvider`: Config key of API provider (e.g., "anthropic", "openrouter")
- `apiModel`: Model name for API inference
- `difficultyThreshold`: Float 0.0–1.0; higher = more tasks stay local (default: 0.5)

---

### Channels (`nanobot/channels/`)

Each channel implements a `BaseChannel` interface:

```python
class BaseChannel(ABC):
    async start()           # Connect and begin listening
    async stop()            # Graceful shutdown
    async send(chat_id, text)  # Send message to user
```

**`ChannelManager`** coordinates all enabled channels:
- Initializes channels based on config (`enabled: true`).
- Routes outbound messages to the correct channel based on session key format (`telegram:123456`, `discord:789`).
- Publishes inbound messages to the bus.

| Channel | File | Transport |
|---------|------|-----------|
| Telegram | `telegram.py` | Long polling via `python-telegram-bot` |
| Discord | `discord.py` | WebSocket gateway |
| WhatsApp | `whatsapp.py` | WebSocket to Node.js bridge |
| Feishu | `feishu.py` | WebSocket long connection (lark-oapi) |
| DingTalk | `dingtalk.py` | Stream mode (dingtalk-stream) |

---

### Message Bus (`nanobot/bus/queue.py`)

Two async queues decouple channels from the agent:

- **Inbound queue**: Channels → Agent. Messages carry `channel`, `chat_id`, `content`, and optional `media`.
- **Outbound queue**: Agent → Channels. Responses carry `channel`, `chat_id`, and `content`.
- **Subscriber pattern**: Channels register callbacks via `subscribe_outbound()` and the bus dispatches responses.

---

### Sessions (`nanobot/session/manager.py`)

Persistent conversation history per user:

- **Session key**: `channel:chat_id` (e.g., `telegram:123456789`).
- **Storage**: JSONL files in `~/.nanobot/sessions/` — one file per session.
- **In-memory cache**: Sessions are loaded once and cached for fast access.
- **History retrieval**: `get_history(n)` returns the last N messages for LLM context.

---

### Cron/Scheduling (`nanobot/cron/`)

The cron service manages scheduled agent tasks:

- **Job types**: `at` (one-time), `every` (interval), `cron` (cron expression via `croniter`).
- **Persistence**: Jobs stored in `~/.nanobot/cron/jobs.json`.
- **Execution**: Timer-based (`asyncio.sleep`); when a job is due, calls the agent's `process_direct()`.
- **Delivery**: Jobs can optionally deliver responses to a specific channel/chat via the bus.

---

### CLI (`nanobot/cli/commands.py`)

Built with `typer`, the CLI provides these entry points:

| Command | What It Does |
|---------|-------------|
| `nanobot onboard` | Creates `~/.nanobot/config.json` and `~/.nanobot/workspace/` |
| `nanobot agent -m "..."` | Single-message mode — process and exit |
| `nanobot agent` | Interactive REPL mode with readline history |
| `nanobot gateway` | Starts all enabled channels + cron + heartbeat |
| `nanobot status` | Displays config, providers, and channel status |
| `nanobot channels login` | Links WhatsApp device (QR scan) |
| `nanobot channels status` | Shows channel connection status |
| `nanobot cron add/list/remove` | Manage scheduled jobs |

---

### Configuration (`nanobot/config/`)

Pydantic-based configuration with nested models:

```
Config (root)
├── agents
│   └── defaults
│       ├── workspace (str)
│       ├── model (str)
│       ├── max_tokens (int)
│       ├── temperature (float)
│       └── max_tool_iterations (int)
├── providers
│   ├── openrouter: {apiKey, apiBase}
│   ├── anthropic: {apiKey, apiBase}
│   ├── openai: {apiKey, apiBase}
│   ├── deepseek: {apiKey, apiBase}
│   ├── ... (all providers)
│   └── vllm: {apiKey, apiBase}
├── hybridRouter
│   ├── enabled (bool)
│   ├── localProvider (str)
│   ├── localModel (str)
│   ├── apiProvider (str)
│   ├── apiModel (str)
│   └── difficultyThreshold (float)
├── channels
│   ├── telegram: {enabled, token, allowFrom}
│   ├── discord: {enabled, token, allowFrom}
│   ├── whatsapp: {enabled, allowFrom}
│   ├── feishu: {enabled, appId, appSecret, ...}
│   └── dingtalk: {enabled, clientId, clientSecret, ...}
├── gateway: {host, port}
└── tools
    ├── restrictToWorkspace (bool)
    ├── web.search: {apiKey}
    └── exec: {timeout}
```

Config is loaded from `~/.nanobot/config.json` and supports environment variable overrides with the `NANOBOT_` prefix.

---

### Skills System (`nanobot/skills/`)

Skills are self-contained knowledge packages:

```
skill-name/
├── SKILL.md          # Required: YAML frontmatter + markdown instructions
├── scripts/          # Optional: executable scripts
├── references/       # Optional: reference documents
└── assets/           # Optional: templates, resources
```

**SKILL.md format:**

```markdown
---
name: my-skill
description: What this skill does
version: 1.0.0
always: false          # true = always loaded in system prompt
requirements:
  commands: [git, curl] # Required CLI tools (checked at load time)
---

# Instructions for the agent

Step-by-step instructions the agent follows when this skill is activated.
```

**Loading strategy:**
1. Skills with `always: true` have their full content included in every system prompt.
2. Other skills appear as metadata summaries; the agent loads them on demand.

---

## Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Agentic Loop** | `agent/loop.py` | LLM ↔ tool execution until done |
| **Registry** | Tools, Providers, Channels | Dynamic registration, no hardcoded conditionals |
| **Message Bus** | `bus/queue.py` | Decouples channels from agent processing |
| **Progressive Disclosure** | `agent/context.py` | Minimizes token usage by loading context on demand |
| **Async-First** | Everywhere | All I/O is async for concurrency |
| **Configuration-Driven** | `config/schema.py` | Behavior driven by Pydantic schemas and registry |
| **File-Based Persistence** | Sessions, Memory, Cron | Simple, portable, no database required |

## Data Flow: Complete Message Lifecycle

1. **User sends message** via Telegram/Discord/WhatsApp/Feishu/DingTalk.
2. **Channel** receives message and calls `bus.publish_inbound(msg)`.
3. **Agent loop** calls `bus.consume_inbound()` to get the message.
4. **Session manager** retrieves or creates a session for this `channel:chat_id`.
5. **Context builder** assembles system prompt + session history + current message.
6. **LLM provider** sends the prompt to the configured LLM (via LiteLLM).
7. **LLM responds** with text and/or tool calls.
8. If **tool calls** exist:
   - **Tool registry** executes each tool.
   - Results are appended to the conversation.
   - Go back to step 6 (up to `max_tool_iterations`).
9. **Final text response** is published to `bus.publish_outbound()`.
10. **Channel manager** dispatches the response to the correct channel.
11. **Channel** sends the response back to the user.
