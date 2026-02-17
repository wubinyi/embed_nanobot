# Customization Guide

This guide explains how to extend and customize nanobot. Each section covers a different extension point with step-by-step instructions.

## Table of Contents

- [Adding a New Tool](#adding-a-new-tool)
- [Adding a New LLM Provider](#adding-a-new-llm-provider)
- [Adding a New Channel](#adding-a-new-channel)
- [Creating a Custom Skill](#creating-a-custom-skill)
- [Customizing Agent Behavior](#customizing-agent-behavior)
- [Customizing the System Prompt](#customizing-the-system-prompt)
- [Adding Heartbeat Tasks](#adding-heartbeat-tasks)

---

## Adding a New Tool

Tools give the agent new capabilities (e.g., database queries, API calls, image generation).

### Step 1: Create the Tool Class

Create a new file in `nanobot/agent/tools/`. Every tool extends the `Tool` base class:

```python
# nanobot/agent/tools/my_tool.py

from nanobot.agent.tools.base import Tool


class MyTool(Tool):
    name = "my_tool"
    description = "A brief description of what this tool does (shown to the LLM)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The query to process",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        # Your tool logic here
        result = f"Processed: {query}"
        return result
```

**Key points:**
- `name` — Unique identifier. The LLM uses this to call your tool.
- `description` — Explains what the tool does. Write it clearly — the LLM reads this to decide when to use your tool.
- `parameters` — JSON Schema defining the tool's inputs. The LLM generates arguments matching this schema.
- `execute(**kwargs)` — Async method that runs the tool and returns a string result.

### Step 2: Register the Tool

Open `nanobot/agent/loop.py` and add your tool to `_register_default_tools()`:

```python
from nanobot.agent.tools.my_tool import MyTool

class AgentLoop:
    def _register_default_tools(self):
        # ... existing tools ...
        self.tool_registry.register(MyTool())
```

That's it. The tool will now appear in the LLM's function definitions and can be called by the agent.

### Tips

- Return clear, concise strings — the LLM reads the output.
- Include error information in the return value rather than raising exceptions.
- Use `self.config` if your tool needs access to configuration.
- The `parameters` schema supports all JSON Schema features (`enum`, `default`, `oneOf`, etc.).

---

## Adding a New LLM Provider

nanobot uses a registry-driven approach — adding a provider requires only 2 changes.

### Step 1: Add a ProviderSpec

Open `nanobot/providers/registry.py` and add a `ProviderSpec` to the `PROVIDERS` list:

```python
ProviderSpec(
    name="myprovider",                   # Config field name (in providers section)
    keywords=("myprovider", "mymodel"),  # Keywords in model names that match this provider
    env_key="MYPROVIDER_API_KEY",        # Environment variable LiteLLM reads
    display_name="My Provider",          # Shown in `nanobot status`
    litellm_prefix="myprovider",         # Prefix added to model: model → myprovider/model
    skip_prefixes=("myprovider/",),      # Don't double-prefix these
)
```

### Step 2: Add Config Field

Open `nanobot/config/schema.py` and add a field to `ProvidersConfig`:

```python
class ProvidersConfig(BaseModel):
    # ... existing providers ...
    myprovider: ProviderConfig = ProviderConfig()
```

### ProviderSpec Options Reference

| Field | Description | Example |
|-------|-------------|---------|
| `name` | Config key and internal identifier | `"myprovider"` |
| `keywords` | Tuple of strings to match in model names | `("mymodel", "myprovider")` |
| `env_key` | Env var for the API key | `"MYPROVIDER_API_KEY"` |
| `display_name` | Human-readable name | `"My Provider"` |
| `litellm_prefix` | Prefix for LiteLLM model routing | `"myprovider"` |
| `skip_prefixes` | Don't prefix if model starts with these | `("myprovider/",)` |
| `env_extras` | Additional env vars to set | `(("OTHER_KEY", "{api_key}"),)` |
| `model_overrides` | Per-model parameter overrides | `(("model-v1", {"temperature": 1.0}),)` |
| `is_gateway` | Can route any model (like OpenRouter) | `True` |
| `detect_by_key_prefix` | Detect gateway by API key prefix | `"sk-my-"` |
| `detect_by_base_keyword` | Detect gateway by base URL keyword | `"myprovider"` |
| `strip_model_prefix` | Strip existing prefix before re-prefixing | `True` |
| `is_oauth` | Uses OAuth flow instead of API key (e.g., Codex) | `False` |

### How Auto-Detection Works

When the agent processes a message:
1. The model name (e.g., `deepseek-chat`) is checked against each provider's `keywords`.
2. The first matching provider is selected.
3. If no keyword matches but a gateway (OpenRouter/AiHubMix) is configured, the gateway is used.
4. The provider's `litellm_prefix` is prepended to the model name for LiteLLM routing.

---

## Adding a New Channel

Channels connect nanobot to chat platforms.

### Step 1: Create the Channel Class

Create a new file in `nanobot/channels/`:

```python
# nanobot/channels/mychannel.py

from nanobot.channels.base import BaseChannel


class MyChannel(BaseChannel):
    def __init__(self, config, bus):
        self.config = config
        self.bus = bus

    async def start(self):
        """Connect to the platform and start listening for messages."""
        # Set up your connection (WebSocket, polling, etc.)
        # When a message arrives:
        #   await self.bus.publish_inbound({
        #       "channel": "mychannel",
        #       "chat_id": "user_123",
        #       "content": "Hello!",
        #   })
        pass

    async def stop(self):
        """Graceful shutdown."""
        pass

    async def send(self, chat_id: str, content: str):
        """Send a response back to the user."""
        # Use your platform's API to send the message
        pass
```

### Step 2: Add Config Schema

In `nanobot/config/schema.py`, add a config model:

```python
class MyChannelConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list, alias="allowFrom")
```

Add it to `ChannelsConfig`:

```python
class ChannelsConfig(BaseModel):
    # ... existing channels ...
    mychannel: MyChannelConfig = MyChannelConfig()
```

### Step 3: Register in ChannelManager

In `nanobot/channels/manager.py`, add initialization logic:

```python
if config.channels.mychannel.enabled:
    from nanobot.channels.mychannel import MyChannel
    channel = MyChannel(config.channels.mychannel, bus)
    self.channels["mychannel"] = channel
```

### Inbound/Outbound Flow

- **Inbound**: Your channel calls `bus.publish_inbound(msg)` when a user message arrives.
- **Outbound**: The channel manager calls your `send(chat_id, content)` when the agent responds.
- **Session key**: Format as `mychannel:chat_id` so sessions are unique per user.

---

## Creating a Custom Skill

Skills teach the agent procedures without modifying core code.

### Step 1: Create Skill Directory

```bash
mkdir -p ~/.nanobot/workspace/skills/my-skill
```

### Step 2: Write SKILL.md

```markdown
---
name: my-skill
description: Short description of what this skill does
version: 1.0.0
always: false
requirements:
  commands: []
---

# My Skill

Instructions for the agent on how to use this skill.

## When to Use

Use this skill when the user asks about X.

## Steps

1. Do this first
2. Then do this
3. Return the result
```

### Skill Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique skill identifier |
| `description` | string | Shown in skill summary (keep concise) |
| `version` | string | Semantic version |
| `always` | bool | `true` = always loaded in system prompt; `false` = loaded on demand |
| `requirements.commands` | string[] | Required CLI tools (checked at load time) |

### Adding Scripts

Place executable scripts in `my-skill/scripts/`:

```bash
# my-skill/scripts/run.sh
#!/bin/bash
echo "Hello from my skill!"
```

The agent can execute these via the `exec` tool.

### Adding References

Place reference documents in `my-skill/references/`:

```
my-skill/references/api-docs.md
```

The agent reads these when it needs detailed information.

### Bundled vs. User Skills

| Location | Scope |
|----------|-------|
| `nanobot/skills/` | Bundled with nanobot (shared across all users) |
| `~/.nanobot/workspace/skills/` | User-defined (personal customizations) |

User skills in the workspace directory take priority.

---

## Customizing Agent Behavior

### Personality (SOUL.md)

Edit `~/.nanobot/workspace/SOUL.md` to change the agent's personality:

```markdown
# Soul

I am nanobot 🐈, a personal AI assistant.

## Personality

- Professional and detail-oriented
- Prefers structured responses with headers
- Always provides code examples

## Communication Style

- Use technical language
- Include citations when possible
```

### Agent Instructions (AGENTS.md)

Edit `~/.nanobot/workspace/AGENTS.md` to change how the agent behaves:

```markdown
# Agent Instructions

You are a coding assistant specializing in Python.

## Guidelines

- Always write type hints
- Suggest tests for any code you write
- Explain trade-offs in your recommendations
```

### User Profile (USER.md)

Edit `~/.nanobot/workspace/USER.md` to provide personal context:

```markdown
# User Profile

## Basic Information

- **Name**: Alice
- **Timezone**: UTC-5
- **Language**: English

## Work Context

- **Primary Role**: Backend Developer
- **Main Projects**: Microservices in Python, data pipelines
- **Tools You Use**: VS Code, PostgreSQL, Docker
```

---

## Customizing the System Prompt

The system prompt is assembled from multiple files in order:

1. **Identity** — Built-in identity string
2. **AGENTS.md** — Agent behavior instructions
3. **SOUL.md** — Personality definition
4. **USER.md** — User profile
5. **TOOLS.md** — Available tools documentation
6. **Memory** — Long-term memory (`MEMORY.md`) from two-layer memory system
7. **Skills** — Always-loaded skill content + available skill metadata

To customize, edit any of these files in `~/.nanobot/workspace/`. Changes take effect on the next message.

---

## Adding Heartbeat Tasks

Heartbeat tasks run every 30 minutes. Edit `~/.nanobot/workspace/HEARTBEAT.md`:

```markdown
# Heartbeat Tasks

## Active Tasks

- [ ] Check weather forecast and send morning summary
- [ ] Monitor GitHub notifications for my repositories
- [ ] Scan RSS feeds for AI news
```

The agent reads this file periodically and acts on unchecked tasks. Remove or check off tasks to stop them.

---

## Summary of Extension Points

| What to Customize | Where to Change | Restart Required? |
|-------------------|----------------|-------------------|
| Agent personality | `workspace/SOUL.md` | No |
| Agent instructions | `workspace/AGENTS.md` | No |
| User context | `workspace/USER.md` | No |
| Heartbeat tasks | `workspace/HEARTBEAT.md` | No |
| New skill | `workspace/skills/my-skill/SKILL.md` | No |
| New tool | `nanobot/agent/tools/` + `loop.py` | Yes |
| MCP tool server | `config.json` (`tools.mcpServers`) | Yes |
| New provider | `providers/registry.py` + `config/schema.py` | Yes |
| New channel | `nanobot/channels/` + `config/schema.py` + `manager.py` | Yes |
| Model/temperature | `~/.nanobot/config.json` | Yes |
| Security settings | `~/.nanobot/config.json` | Yes |
