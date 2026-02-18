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
│  Channels (Telegram, Discord, WhatsApp, Feishu, DingTalk,   │
│  Email, Slack, QQ, MoChat, LAN Mesh)                        │
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
  3. Memory context: long-term `MEMORY.md` (two-layer memory system)
  4. Skills: always-loaded skills (full content) + available skills (metadata summary)
- **Messages** combine the system prompt with session history and the current user message.
- **Media handling**: Images are base64-encoded and sent as vision content blocks. Telegram supports voice/audio (transcribed via Groq), photos, and documents.

#### `memory.py` — Memory Store

Two-layer file-based persistence for agent memory:

- **Long-term memory**: `workspace/memory/MEMORY.md` — persistent knowledge and distilled facts.
- **Conversation history log**: `workspace/memory/HISTORY.md` — grep-searchable log of past conversations.
- **Memory consolidation**: The agent loop periodically summarizes old session messages via LLM, writes distilled facts to `MEMORY.md` and a searchable log to `HISTORY.md`, then trims the session.
- **`get_memory_context()`** returns formatted `MEMORY.md` content for the system prompt.

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
| `read_file` | `filesystem.py` | Read file contents |
| `write_file` | `filesystem.py` | Write/create files |
| `edit_file` | `filesystem.py` | Search-and-replace in files |
| `list_dir` | `filesystem.py` | List directory contents |
| `exec` | `shell.py` | Execute shell commands (with safety checks) |
| `web_search` | `web.py` | Search the web (Brave API) |
| `web_fetch` | `web.py` | Fetch and extract URL content |
| `message` | `message.py` | Send message to user |
| `spawn` | `spawn.py` | Spawn background subagent |
| `cron` | `cron.py` | Schedule tasks |
| MCP tools | `mcp.py` | Dynamic tools from external MCP servers (stdio/HTTP) |
| `device_control` | `device.py` | Control IoT devices via mesh: list, command, state, describe (registered when mesh enabled) |

Tools are registered in `AgentLoop._register_default_tools()` and presented to the LLM as OpenAI-format function definitions via `ToolRegistry.to_schemas()`. MCP tools are connected dynamically via `AgentLoop._connect_mcp()` at startup. The `device_control` tool is registered conditionally in `nanobot/cli/commands.py` when the mesh channel is active.

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
    is_oauth=False,                       # If True, uses OAuth flow (e.g., Codex)
)
```

Key lookup functions:
- **`find_by_model(model)`** — Matches a provider by checking if any keyword appears in the model name.
- **`find_gateway(api_key, api_base)`** — Detects gateway providers (OpenRouter, AiHubMix) by key prefix or URL.
- **`find_by_name(name)`** — Direct lookup by config field name.

#### `openai_codex_provider.py` — OpenAI Codex Provider

OAuth-based provider for OpenAI Codex:

- Uses `oauth-cli-kit` for OAuth token management.
- Registered with `is_oauth=True` in the provider spec — uses OAuth flow instead of API key.
- Supports `nanobot provider login openai-codex` for authentication.

#### GitHub Copilot Provider

- Uses the same OAuth mechanism as Codex (`is_oauth=True`).
- Registered as `github_copilot` in the provider registry with `litellm_prefix="github_copilot"`.
- Supports `nanobot provider login github-copilot` for authentication.

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
| Telegram | `telegram.py` | Long polling via `python-telegram-bot`; media support (voice, audio, photos, documents) |
| Discord | `discord.py` | WebSocket gateway |
| WhatsApp | `whatsapp.py` | WebSocket to Node.js bridge |
| Feishu | `feishu.py` | WebSocket long connection (lark-oapi) |
| DingTalk | `dingtalk.py` | Stream mode (dingtalk-stream) |
| Email | `email.py` | IMAP polling + SMTP replies |
| Slack | `slack.py` | Socket Mode (slack-sdk) |
| QQ | `qq.py` | WebSocket via botpy SDK |
| MoChat | `mochat.py` | HTTP webhook |
| LAN Mesh | `mesh/channel.py` | UDP discovery + TCP transport |

---

### LAN Mesh (`nanobot/mesh/`)

The LAN Mesh enables **device-to-device communication** on the same local network without requiring internet. This is ideal for smart home scenarios where nanobot acts as an AI hub controlling household appliances, or for nanobot-to-nanobot communication across multiple instances.

**Architecture** — Five-layer design:

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 5: MeshChannel (nanobot/mesh/channel.py)             │
│  ↓ Bridges mesh transport into nanobot's message bus        │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│  Layer 4b: CommandSchema (nanobot/mesh/commands.py)          │
│  ↓ Command/response models, validation, LLM context         │
├──────────────────────────────────────────────────────────────┤
│  Layer 4a: DeviceRegistry (nanobot/mesh/registry.py)        │
│  ↓ Device capabilities, state tracking, online/offline      │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│  Layer 3c: Encryption (nanobot/mesh/encryption.py)          │
│  ↓ AES-256-GCM payload encryption, PSK-derived keys         │
├─────────────────────────────────────────────────────────────-┤
│  Layer 3b: Enrollment (nanobot/mesh/enrollment.py)          │
│  ↓ PIN-based device pairing, PBKDF2 key derivation          │
├─────────────────────────────────────────────────────────────-┤
│  Layer 3a: PSK Security (nanobot/mesh/security.py)          │
│  ↓ HMAC-SHA256 signing/verification, key store, nonce guard │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│  Layer 2: MeshTransport (nanobot/mesh/transport.py)         │
│  ↓ TCP connections for reliable message delivery            │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│  Layer 1: UDPDiscovery (nanobot/mesh/discovery.py)          │
│  ↓ Broadcast beacons for peer discovery                     │
└──────────────────────────────────────────────────────────────┘
```

**Discovery → Connection flow:**

```
Device A (nanobot)                    Device B (IoT device)
       │                                      │
       │←─── UDP beacon (port 18799) ────────│  "I'm here!"
       │                                      │
       ├──── UDP beacon ─────────────────────→  "I'm here too!"
       │                                      │
       │                                      │
       │──── TCP connect (port 18800) ───────→  Establish link
       │                                      │
       │←──── TCP ACK ────────────────────────│
       │                                      │
       │──── CHAT envelope ───────────────────→
       │      { type: "chat",                 │
       │        source: "nanobot-main",       │
       │        target: "device-b",           │
       │        payload: {...} }              │
       │                                      │
       │←──── RESPONSE envelope ───────────────│
```

**Protocol envelope format** (`nanobot/mesh/protocol.py`):

Every mesh message is a JSON envelope with a **4-byte big-endian length prefix** so the receiver knows exactly how many bytes to read:

```
┌──────────────────┬────────────────────────────────────────┐
│  4 bytes         │  N bytes                               │
│  (big-endian)    │  (JSON)                                │
│  Length = N      │  { "type": "...", "source": "...", ... }│
└──────────────────┴────────────────────────────────────────┘
```

JSON structure:

```json
{
  "type": "chat",                 // Message type: CHAT, COMMAND, RESPONSE, PING, PONG
  "source": "nanobot-main",       // Sender node ID
  "target": "device-abc",         // Receiver node ID ("*" = broadcast)
  "payload": {                    // Type-specific content
    "text": "Turn on the lights"
  },
  "ts": 1700000000.0,             // Unix timestamp
  "nonce": "a1b2c3d4e5f6a7b8",   // Random 16-hex-char nonce (PSK auth)
  "hmac": "hex-sha256-digest"     // HMAC-SHA256 signature (PSK auth)
}
```

**Message types:**

| Type | Purpose |
|------|---------|
| `CHAT` | Chat messages between nodes (e.g., user → nanobot via IoT device) |
| `COMMAND` | Commands directed at a device (e.g., "turn on AC") |
| `RESPONSE` | Acknowledgements / responses from devices |
| `PING` / `PONG` | Heartbeat for presence tracking |
| `ENROLL_REQUEST` | New device requests PSK enrollment (PIN-based) |
| `ENROLL_RESPONSE` | Hub responds with encrypted PSK or error |
| `STATE_REPORT` | Device pushes state changes to the hub |

**Key components:**

- **`protocol.py`**: Wire format, `MeshEnvelope` serialisation/deserialisation, `read_envelope()` / `write_envelope()`, canonical bytes for HMAC
- **`commands.py`**: `DeviceCommand`, `CommandResponse`, `BatchCommand` — standardized command/response schema, `validate_command()` validates against registry (action/capability/type/range), envelope conversion helpers, `describe_device_commands()` LLM context generator
- **`registry.py`**: `DeviceRegistry` — CRUD for device records, capability/state tracking, online/offline status, JSON persistence, event callbacks, LLM context helpers
- **`security.py`**: `KeyStore` — per-device PSK management, HMAC-SHA256 sign/verify, nonce replay tracking, timestamp validation
- **`enrollment.py`**: `EnrollmentService` — PIN lifecycle (create/cancel/expire/lock), PIN proof verification, PBKDF2 key derivation, XOR-encrypted PSK transfer
- **`encryption.py`**: AES-256-GCM payload encrypt/decrypt, HMAC-SHA256-based key derivation from PSK, AAD binding to envelope metadata. Requires `cryptography` library.
- **`discovery.py`**: UDP broadcast beacons advertising node presence on port 18799
- **`transport.py`**: TCP server (port 18800) + client connections, handles envelope routing, auto-sign outbound / verify inbound
- **`channel.py`**: `MeshChannel` implements `BaseChannel` interface, publishes inbound messages to the bus and subscribes to outbound messages

The mesh is registered in `nanobot/channels/manager.py` like any other channel and activated via `channels.mesh.enabled: true` in config.

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
- **History retrieval**: `get_history(max_messages=500)` returns recent messages for LLM context.
- **Consolidation tracking**: `last_consolidated` field tracks how many messages have been summarized to memory files.
- **`/new` command**: Clears session and triggers full memory consolidation.

---

### Cron/Scheduling (`nanobot/cron/`)

The cron service manages scheduled agent tasks:

- **Job types**: `at` (one-time), `every` (interval), `cron` (cron expression via `croniter`).
- **Timezone support**: Jobs respect timezone configuration; defaults to system timezone.
- **Persistence**: Jobs stored in `~/.nanobot/cron/jobs.json`.
- **Execution**: Timer-based (`asyncio.sleep`); when a job is due, calls the agent's `process_direct()`.
- **Delivery**: Jobs can optionally deliver responses to a specific channel/chat via the bus.

---

### CLI (`nanobot/cli/commands.py`)

Built with `typer`, the CLI provides these entry points:

| Command | What It Does |
|---------|-------------|
| `nanobot onboard` | Creates/merges `~/.nanobot/config.json` and `~/.nanobot/workspace/` (non-destructive) |
| `nanobot agent -m "..."` | Single-message mode — process and exit |
| `nanobot agent` | Interactive REPL mode with `prompt_toolkit` (history, multi-line) |
| `nanobot gateway` | Starts all enabled channels + cron + heartbeat |
| `nanobot status` | Displays config, providers, and channel status |
| `nanobot provider login <name>` | OAuth login for providers (e.g., `openai-codex`) |
| `nanobot channels login` | Links WhatsApp device (QR scan) |
| `nanobot channels status` | Shows channel connection status |
| `nanobot cron add/list/remove/enable/run` | Manage and execute scheduled jobs |

**Slash commands** (available in interactive mode and all channels):
- `/new` — Start a new conversation (consolidates memory, clears session)
- `/help` — Show available commands

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
│       ├── max_tool_iterations (int)
│       └── memory_window (int)            # Messages to keep before consolidation
├── providers
│   ├── custom: {apiKey, apiBase, extraHeaders}  # User-defined OpenAI-compatible
│   ├── anthropic: {apiKey, apiBase, extraHeaders}
│   ├── openai: {apiKey, apiBase, extraHeaders}
│   ├── openrouter: {apiKey, apiBase, extraHeaders}
│   ├── deepseek: {apiKey, apiBase, extraHeaders}
│   ├── groq, zhipu, dashscope, vllm, ollama, gemini, moonshot
│   ├── minimax, aihubmix: {apiKey, apiBase, extraHeaders}
│   ├── openai_codex: {apiKey, apiBase}    # OAuth-based (is_oauth=True)
│   └── github_copilot: {apiKey, apiBase}  # OAuth-based (is_oauth=True)
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
│   ├── dingtalk: {enabled, clientId, clientSecret, ...}
│   ├── email: {enabled, imapHost, smtpHost, ...}
│   ├── slack: {enabled, botToken, appToken, mode, dm, ...}
│   ├── qq: {enabled, appId, secret, ...}
│   └── mesh: {enabled, nodeId, tcpPort, udpPort, roles, ...}
├── gateway: {host, port}
└── tools
    ├── restrictToWorkspace (bool)
    ├── web.search: {apiKey, maxResults}
    ├── exec: {timeout}
    └── mcp_servers: {name: {command, args, env, url}}  # MCP server connections
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

**embed_nanobot skills:**
- **`device-control`** (`always: true`): Teaches the agent to translate natural language device requests into `device_control` tool calls. Covers set/get/toggle/execute patterns, NL→command workflow, and validation notes.

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

1. **User sends message** via Telegram/Discord/WhatsApp/Feishu/DingTalk/Email/Slack/QQ/MoChat/LAN Mesh.
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
