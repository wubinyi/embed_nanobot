# Call Hierarchy & Reference Hierarchy

This document maps how every module in the `nanobot/` package relates to every other — what imports what, who calls whom, and how data flows between them.

> **Generated**: 2026-02-11  
> **Scope**: All Python modules under `nanobot/`

---

## 1. Module Dependency Graph

Arrows point from **importer → imported module**.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          __main__.py                                 │
│                               │                                      │
│                               ▼                                      │
│                     cli/commands.py                                   │
│                 ┌──────┬───┬───┬──────┬───────┐                      │
│                 ▼      ▼   ▼   ▼      ▼       ▼                      │
│            config/  bus/  agent/ channels/ cron/ heartbeat/           │
│           loader   queue  loop  manager  service service             │
│             │       │      │      │       │                          │
│             ▼       │      │      │       ▼                          │
│          config/    │      │      │    cron/types                    │
│          schema     │      │      │                                  │
│                     │      │      │                                  │
│                     │      │      ├───► base.py                      │
│                     │      │      ├───► telegram.py                  │
│                     │      │      ├───► discord.py                   │
│                     │      │      ├───► whatsapp.py                  │
│                     │      │      ├───► feishu.py                    │
│                     │      │      ├───► dingtalk.py                  │
│                     │      │      ├───► email.py                     │
│                     │      │      ├───► slack.py                     │
│                     │      │      ├───► qq.py                        │
│                     │      │      └───► mochat.py                    │
│                     │      │                                         │
│                     │      ├───► context.py                          │
│                     │      │       ├───► memory.py                   │
│                     │      │       └───► skills.py                   │
│                     │      ├───► subagent.py                         │
│                     │      └───► tools/                              │
│                     │            ├─ registry.py ◄── base.py          │
│                     │            ├─ filesystem.py                    │
│                     │            ├─ shell.py                         │
│                     │            ├─ web.py                           │
│                     │            ├─ message.py ──► bus/events        │
│                     │            ├─ spawn.py ──► subagent.py         │
│                     │            └─ cron.py ──► cron/service         │
│                     │                                                │
│                     └──────────► bus/events.py                       │
│                                  (InboundMessage, OutboundMessage)   │
│                                                                      │
│                     providers/                                        │
│                     ├─ base.py (LLMProvider, LLMResponse)            │
│                     ├─ litellm_provider.py ──► registry.py           │
│                     ├─ registry.py (ProviderSpec, PROVIDERS)          │
│                     └─ transcription.py                               │
│                                                                      │
│                     session/manager.py ──► utils/helpers              │
│                     utils/helpers.py                                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Per-Module Import Map

### Entry & CLI

| Module | Imports From (nanobot) |
|--------|----------------------|
| `__main__.py` | `cli.commands.app` |
| `cli/commands.py` | `config.loader.load_config`, `config.loader.save_config`, `bus.queue.MessageBus`, `agent.loop.AgentLoop`, `channels.manager.ChannelManager`, `session.manager.SessionManager`, `cron.service.CronService`, `cron.types.CronJob`, `heartbeat.service.HeartbeatService`, `providers.litellm_provider.LiteLLMProvider` |

### Agent Core

| Module | Imports From (nanobot) |
|--------|----------------------|
| `agent/loop.py` | `bus.events.{InboundMessage, OutboundMessage}`, `bus.queue.MessageBus`, `providers.base.LLMProvider`, `agent.context.ContextBuilder`, `agent.tools.registry.ToolRegistry`, `agent.tools.filesystem.{ReadFileTool, WriteFileTool, EditFileTool, ListDirTool}`, `agent.tools.shell.ExecTool`, `agent.tools.web.{WebSearchTool, WebFetchTool}`, `agent.tools.message.MessageTool`, `agent.tools.spawn.SpawnTool`, `agent.tools.cron.CronTool`, `agent.subagent.SubagentManager`, `session.manager.SessionManager` |
| `agent/context.py` | `agent.memory.MemoryStore`, `agent.skills.SkillsLoader` |
| `agent/memory.py` | *(stdlib only)* |
| `agent/skills.py` | *(stdlib only)* |
| `agent/subagent.py` | `bus.events.InboundMessage`, `bus.queue.MessageBus`, `providers.base.LLMProvider`, `agent.tools.registry.ToolRegistry`, `agent.tools.filesystem.*`, `agent.tools.shell.ExecTool`, `agent.tools.web.*` |

### Agent Tools

| Module | Imports From (nanobot) |
|--------|----------------------|
| `agent/tools/base.py` | *(stdlib only)* |
| `agent/tools/registry.py` | `agent.tools.base.Tool` |
| `agent/tools/filesystem.py` | `agent.tools.base.Tool` |
| `agent/tools/shell.py` | `agent.tools.base.Tool` |
| `agent/tools/web.py` | `agent.tools.base.Tool` |
| `agent/tools/message.py` | `agent.tools.base.Tool`, `bus.events.OutboundMessage` |
| `agent/tools/spawn.py` | `agent.tools.base.Tool`, *(lazy)* `agent.subagent.SubagentManager` |
| `agent/tools/cron.py` | `agent.tools.base.Tool`, `cron.service.CronService`, `cron.types.CronSchedule` |

### Providers

| Module | Imports From (nanobot) |
|--------|----------------------|
| `providers/base.py` | *(stdlib only)* |
| `providers/registry.py` | *(stdlib only — defines ProviderSpec dataclass)* |
| `providers/litellm_provider.py` | `providers.base.{LLMProvider, LLMResponse, ToolCallRequest}`, `providers.registry.{PROVIDERS, find_by_model, find_gateway, find_by_name}` |
| `providers/transcription.py` | *(external: groq)* |

### Channels

| Module | Imports From (nanobot) |
|--------|----------------------|
| `channels/base.py` | `bus.events.{InboundMessage, OutboundMessage}`, `bus.queue.MessageBus` |
| `channels/manager.py` | `bus.events.OutboundMessage`, `bus.queue.MessageBus`, `channels.base.BaseChannel`, `config.schema.Config`, *(lazy)* all channel classes |
| `channels/telegram.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.TelegramConfig`, `providers.transcription.GroqTranscriptionProvider` |
| `channels/discord.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.DiscordConfig` |
| `channels/whatsapp.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.WhatsAppConfig` |
| `channels/feishu.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.FeishuConfig` |
| `channels/dingtalk.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.DingTalkConfig` |
| `channels/email.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.EmailConfig` |
| `channels/slack.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.SlackConfig` |
| `channels/qq.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.QQConfig` |
| `channels/mochat.py` | `channels.base.BaseChannel`, `bus.queue.MessageBus`, `bus.events.OutboundMessage`, `config.schema.MochatConfig`, `utils.helpers.get_data_path` |

### Bus, Config, Session, Cron, Heartbeat, Utils

| Module | Imports From (nanobot) |
|--------|----------------------|
| `bus/events.py` | *(stdlib only — dataclasses)* |
| `bus/queue.py` | `bus.events.{InboundMessage, OutboundMessage}` |
| `config/schema.py` | *(pydantic only)* |
| `config/loader.py` | `config.schema.Config` |
| `session/manager.py` | `utils.helpers.{ensure_dir, safe_filename}` |
| `cron/types.py` | *(stdlib only — dataclasses)* |
| `cron/service.py` | `cron.types.*` |
| `heartbeat/service.py` | *(standalone)* |
| `utils/helpers.py` | *(stdlib only)* |

---

## 3. Reverse Reference Map (Who Uses This Module?)

| Module | Used By |
|--------|---------|
| `bus.queue.MessageBus` | `cli/commands`, `agent/loop`, `agent/subagent`, `channels/manager`, `channels/base`, all channel implementations |
| `bus.events.InboundMessage` | `channels/base`, `agent/loop`, `agent/subagent` |
| `bus.events.OutboundMessage` | `agent/loop`, `agent/tools/message`, `channels/manager`, `channels/base`, all channel implementations |
| `agent.loop.AgentLoop` | `cli/commands` |
| `agent.context.ContextBuilder` | `agent/loop` |
| `agent.memory.MemoryStore` | `agent/context` |
| `agent.skills.SkillsLoader` | `agent/context` |
| `agent.subagent.SubagentManager` | `agent/loop`, `agent/tools/spawn` |
| `agent.tools.base.Tool` | All tool implementations, `agent/tools/registry` |
| `agent.tools.registry.ToolRegistry` | `agent/loop`, `agent/subagent` |
| `agent.tools.filesystem.*` | `agent/loop`, `agent/subagent` |
| `agent.tools.shell.ExecTool` | `agent/loop`, `agent/subagent` |
| `agent.tools.web.*` | `agent/loop`, `agent/subagent` |
| `agent.tools.message.MessageTool` | `agent/loop` |
| `agent.tools.spawn.SpawnTool` | `agent/loop` |
| `agent.tools.cron.CronTool` | `agent/loop` |
| `channels.base.BaseChannel` | `channels/manager`, all channel implementations |
| `channels.manager.ChannelManager` | `cli/commands` |
| `config.schema.Config` | `config/loader`, `channels/manager` |
| `config.loader.load_config` | `cli/commands` |
| `providers.base.LLMProvider` | `agent/loop`, `agent/subagent`, `providers/litellm_provider` |
| `providers.litellm_provider.LiteLLMProvider` | `cli/commands` |
| `providers.registry` | `providers/litellm_provider` |
| `session.manager.SessionManager` | `agent/loop`, `cli/commands` |
| `cron.service.CronService` | `agent/tools/cron`, `cli/commands` |
| `cron.types` | `cron/service`, `agent/tools/cron` |
| `heartbeat.service.HeartbeatService` | `cli/commands` |
| `utils.helpers` | `session/manager`, `channels/mochat` |

---

## 4. Calling Hierarchy — Key Execution Flows

### 4.1 Application Startup (`nanobot gateway`)

```
cli/commands.py :: gateway()
├── config/loader.py :: load_config() → Config
├── providers/litellm_provider.py :: LiteLLMProvider.__init__(config)
│   └── providers/registry.py :: find_by_name(), find_by_model(), find_gateway()
├── bus/queue.py :: MessageBus()
├── session/manager.py :: SessionManager()
├── cron/service.py :: CronService()
├── agent/loop.py :: AgentLoop.__init__(bus, provider, session_mgr, workspace, ...)
│   ├── agent/context.py :: ContextBuilder.__init__(workspace)
│   │   ├── agent/memory.py :: MemoryStore.__init__(workspace)
│   │   └── agent/skills.py :: SkillsLoader.__init__(workspace)
│   ├── agent/tools/registry.py :: ToolRegistry()
│   └── AgentLoop._register_default_tools()
│       ├── agent/tools/filesystem.py :: ReadFileTool(), WriteFileTool(), EditFileTool(), ListDirTool()
│       ├── agent/tools/shell.py :: ExecTool()
│       ├── agent/tools/web.py :: WebSearchTool(), WebFetchTool()
│       ├── agent/tools/message.py :: MessageTool()
│       ├── agent/tools/spawn.py :: SpawnTool()
│       └── agent/tools/cron.py :: CronTool()
├── heartbeat/service.py :: HeartbeatService.start()
├── channels/manager.py :: ChannelManager.__init__(config, bus)
│   └── ChannelManager._init_channels()
│       ├── channels/telegram.py :: TelegramChannel(config, bus)  [if enabled]
│       ├── channels/discord.py :: DiscordChannel(config, bus)    [if enabled]
│       ├── channels/whatsapp.py :: WhatsAppChannel(config, bus)  [if enabled]
│       ├── channels/feishu.py :: FeishuChannel(config, bus)      [if enabled]
│       ├── channels/mochat.py :: MochatChannel(config, bus)      [if enabled]
│       ├── channels/dingtalk.py :: DingTalkChannel(config, bus)  [if enabled]
│       ├── channels/email.py :: EmailChannel(config, bus)        [if enabled]
│       ├── channels/slack.py :: SlackChannel(config, bus)        [if enabled]
│       └── channels/qq.py :: QQChannel(config, bus)              [if enabled]
├── ChannelManager.start_all()
│   ├── [each channel].start()          ← async infinite loop per channel
│   └── ChannelManager._dispatch_outbound()  ← routes outbound msgs to channels
├── CronService.start()
└── AgentLoop.run()                     ← consumes from inbound bus
```

### 4.2 Message Processing (Agentic Loop)

```
agent/loop.py :: AgentLoop.run()
└── bus/queue.py :: MessageBus.consume_inbound() → InboundMessage
    └── AgentLoop._process_message(msg)
        ├── session/manager.py :: SessionManager.get_or_create(key) → Session
        ├── agent/context.py :: ContextBuilder.build_messages(session, msg)
        │   ├── agent/memory.py :: MemoryStore.get_memory_context()
        │   └── agent/skills.py :: SkillsLoader.get_skills_context()
        ├── providers/litellm_provider.py :: LiteLLMProvider.chat(messages, tools)
        │   ├── LiteLLMProvider._resolve_model(model)
        │   │   └── providers/registry.py :: find_by_model(), find_gateway()
        │   ├── LiteLLMProvider._setup_env()
        │   │   └── providers/registry.py :: ProviderSpec (env_key, env_extras)
        │   ├── LiteLLMProvider._apply_model_overrides(model, kwargs)
        │   │   └── providers/registry.py :: ProviderSpec.model_overrides
        │   └── litellm.acompletion() → LLMResponse
        ├── [if tool_calls in response]:
        │   └── agent/tools/registry.py :: ToolRegistry.execute(name, args)
        │       ├── agent/tools/filesystem.py :: ReadFileTool.execute()
        │       ├── agent/tools/filesystem.py :: WriteFileTool.execute()
        │       ├── agent/tools/filesystem.py :: EditFileTool.execute()
        │       ├── agent/tools/filesystem.py :: ListDirTool.execute()
        │       ├── agent/tools/shell.py :: ExecTool.execute()
        │       │   └── ExecTool._guard_command(cmd, cwd)
        │       ├── agent/tools/web.py :: WebSearchTool.execute()
        │       ├── agent/tools/web.py :: WebFetchTool.execute()
        │       ├── agent/tools/message.py :: MessageTool.execute()
        │       │   └── bus/queue.py :: MessageBus.publish_outbound(OutboundMessage)
        │       ├── agent/tools/spawn.py :: SpawnTool.execute()
        │       │   └── agent/subagent.py :: SubagentManager.spawn(task, ...)
        │       │       └── [spawns isolated AgentLoop with subset of tools]
        │       └── agent/tools/cron.py :: CronTool.execute()
        │           └── cron/service.py :: CronService.add_job() / remove_job()
        │               └── cron/types.py :: CronJob, CronSchedule
        ├── [repeat LLM call with tool results until no more tool_calls]
        ├── session/manager.py :: Session.add_message(...)
        └── bus/queue.py :: MessageBus.publish_outbound(OutboundMessage)
```

### 4.3 Channel Inbound Message Flow

```
[External platform] → message arrives

channels/<channel>.py :: <Channel>.start()    ← async listener
└── channels/base.py :: BaseChannel._handle_message(sender_id, chat_id, content, media, metadata)
    ├── BaseChannel.is_allowed(sender_id)     ← check allowFrom list
    └── bus/queue.py :: MessageBus.publish_inbound(InboundMessage)
        └── → consumed by AgentLoop.run() (see §4.2)
```

### 4.4 Channel Outbound Message Flow

```
bus/queue.py :: MessageBus.publish_outbound(OutboundMessage)
└── channels/manager.py :: ChannelManager._dispatch_outbound()
    └── bus/queue.py :: MessageBus.consume_outbound() → OutboundMessage
        └── channels/<channel>.py :: <Channel>.send(msg)
            └── [External platform API call to deliver response]
```

### 4.5 CLI Direct Mode (`nanobot agent -m "..."`)

```
cli/commands.py :: agent(message="...")
├── config/loader.py :: load_config()
├── providers/litellm_provider.py :: LiteLLMProvider(config)
├── bus/queue.py :: MessageBus()
├── agent/loop.py :: AgentLoop.__init__(bus, provider, ...)
└── AgentLoop.process_direct(message, session_id)
    └── [same processing as §4.2, but bypasses bus for return value]
```

### 4.6 Cron Job Execution

```
cron/service.py :: CronService._timer_loop()
└── [job is due]
    └── on_job callback → cli/commands.py :: gateway._on_cron
        └── agent/loop.py :: AgentLoop.process_direct(job.payload.message, session_key)
            └── [same processing as §4.2]
                └── [if job has deliver target]:
                    bus/queue.py :: MessageBus.publish_outbound(OutboundMessage)
```

### 4.7 Subagent Spawning

```
agent/tools/spawn.py :: SpawnTool.execute(task, label, ...)
└── agent/subagent.py :: SubagentManager.spawn(task, ...)
    ├── agent/loop.py :: AgentLoop.__init__(...)  [isolated instance]
    │   └── _register_default_tools()  [subset: file, shell, web tools only]
    ├── AgentLoop.process_direct(task)
    │   └── [same agentic loop as §4.2]
    └── bus/queue.py :: MessageBus.publish_inbound(InboundMessage)
        └── [system message announcing subagent completion]
```

---

## 5. Class Hierarchy

```
ABC
├── Tool (agent/tools/base.py)
│   ├── ReadFileTool      (agent/tools/filesystem.py)
│   ├── WriteFileTool     (agent/tools/filesystem.py)
│   ├── EditFileTool      (agent/tools/filesystem.py)
│   ├── ListDirTool       (agent/tools/filesystem.py)
│   ├── ExecTool          (agent/tools/shell.py)
│   ├── WebSearchTool     (agent/tools/web.py)
│   ├── WebFetchTool      (agent/tools/web.py)
│   ├── MessageTool       (agent/tools/message.py)
│   ├── SpawnTool         (agent/tools/spawn.py)
│   └── CronTool          (agent/tools/cron.py)
│
├── LLMProvider (providers/base.py)
│   └── LiteLLMProvider   (providers/litellm_provider.py)
│
└── BaseChannel (channels/base.py)
    ├── TelegramChannel   (channels/telegram.py)
    ├── DiscordChannel    (channels/discord.py)
    ├── WhatsAppChannel   (channels/whatsapp.py)
    ├── FeishuChannel     (channels/feishu.py)
    ├── DingTalkChannel   (channels/dingtalk.py)
    ├── EmailChannel      (channels/email.py)
    ├── SlackChannel      (channels/slack.py)
    ├── QQChannel         (channels/qq.py)
    └── MochatChannel     (channels/mochat.py)

BaseModel (pydantic)
├── Config                (config/schema.py)
├── AgentsConfig          (config/schema.py)
│   └── AgentDefaults
├── ProvidersConfig       (config/schema.py)
│   └── ProviderConfig
├── ChannelsConfig        (config/schema.py)
│   ├── TelegramConfig
│   ├── DiscordConfig
│   ├── WhatsAppConfig
│   ├── FeishuConfig
│   ├── DingTalkConfig
│   ├── EmailConfig
│   ├── SlackConfig
│   │   └── SlackDMConfig
│   ├── QQConfig
│   └── MochatConfig
│       ├── MochatMentionConfig
│       └── MochatGroupRule
├── GatewayConfig         (config/schema.py)
└── ToolsConfig           (config/schema.py)
    ├── WebToolsConfig
    │   └── WebSearchConfig
    └── ExecToolsConfig

@dataclass
├── InboundMessage        (bus/events.py)
├── OutboundMessage       (bus/events.py)
├── ProviderSpec          (providers/registry.py)
├── CronJob               (cron/types.py)
├── CronSchedule          (cron/types.py)
├── CronPayload           (cron/types.py)
├── MochatBufferedEntry   (channels/mochat.py)
├── DelayState            (channels/mochat.py)
└── MochatTarget          (channels/mochat.py)
```

---

## 6. File Listing with Roles

| File | Role | Key Exports |
|------|------|-------------|
| `__main__.py` | Entry point | runs `cli.commands.app()` |
| `__init__.py` | Package metadata | `__version__`, `__logo__` |
| `cli/commands.py` | CLI commands | `app`, `onboard`, `agent`, `gateway`, `status` |
| `config/schema.py` | Config schema | `Config`, all `*Config` models |
| `config/loader.py` | Config I/O | `load_config()`, `save_config()` |
| `bus/events.py` | Message types | `InboundMessage`, `OutboundMessage` |
| `bus/queue.py` | Message bus | `MessageBus` |
| `agent/loop.py` | Agent core | `AgentLoop` |
| `agent/context.py` | Prompt assembly | `ContextBuilder` |
| `agent/memory.py` | Memory store | `MemoryStore` |
| `agent/skills.py` | Skills loader | `SkillsLoader` |
| `agent/subagent.py` | Background agents | `SubagentManager` |
| `agent/tools/base.py` | Tool ABC | `Tool` |
| `agent/tools/registry.py` | Tool dispatch | `ToolRegistry` |
| `agent/tools/filesystem.py` | File operations | `ReadFileTool`, `WriteFileTool`, `EditFileTool`, `ListDirTool` |
| `agent/tools/shell.py` | Shell exec | `ExecTool` |
| `agent/tools/web.py` | Web tools | `WebSearchTool`, `WebFetchTool` |
| `agent/tools/message.py` | User messaging | `MessageTool` |
| `agent/tools/spawn.py` | Subagent spawn | `SpawnTool` |
| `agent/tools/cron.py` | Scheduling | `CronTool` |
| `providers/base.py` | Provider ABC | `LLMProvider`, `LLMResponse`, `ToolCallRequest` |
| `providers/registry.py` | Provider metadata | `PROVIDERS`, `ProviderSpec`, `find_by_model()`, `find_gateway()`, `find_by_name()` |
| `providers/litellm_provider.py` | LLM calls | `LiteLLMProvider` |
| `providers/transcription.py` | Voice-to-text | `GroqTranscriptionProvider` |
| `channels/base.py` | Channel ABC | `BaseChannel` |
| `channels/manager.py` | Channel orchestrator | `ChannelManager` |
| `channels/telegram.py` | Telegram | `TelegramChannel` |
| `channels/discord.py` | Discord | `DiscordChannel` |
| `channels/whatsapp.py` | WhatsApp | `WhatsAppChannel` |
| `channels/feishu.py` | Feishu | `FeishuChannel` |
| `channels/dingtalk.py` | DingTalk | `DingTalkChannel` |
| `channels/email.py` | Email | `EmailChannel` |
| `channels/slack.py` | Slack | `SlackChannel` |
| `channels/qq.py` | QQ | `QQChannel` |
| `channels/mochat.py` | MoChat | `MochatChannel` |
| `session/manager.py` | Sessions | `SessionManager`, `Session` |
| `cron/service.py` | Cron engine | `CronService` |
| `cron/types.py` | Cron types | `CronJob`, `CronSchedule`, `CronPayload` |
| `heartbeat/service.py` | Heartbeat | `HeartbeatService` |
| `utils/helpers.py` | Utilities | `ensure_dir()`, `get_workspace_path()`, `get_data_path()`, `safe_filename()` |
