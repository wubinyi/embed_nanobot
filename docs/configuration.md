# Configuration Reference

This document provides a complete reference for all configuration options in `~/.nanobot/config.json`.

## Config File Location

```
~/.nanobot/config.json
```

Created automatically by `nanobot onboard`. All fields are optional — only set what you need.

## Environment Variable Overrides

Any config value can be overridden with environment variables using the `NANOBOT_` prefix:

```bash
export NANOBOT_AGENTS__DEFAULTS__MODEL="anthropic/claude-opus-4-5"
```

(Double underscores `__` represent nested keys.)

---

## Full Config Structure

```jsonc
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",  // Agent workspace directory
      "model": "anthropic/claude-opus-4-5",         // Default LLM model
      "maxTokens": 16384,                   // Max tokens in LLM response
      "temperature": 0.7,                   // LLM temperature (0.0–2.0)
      "maxToolIterations": 30,              // Max tool call rounds per message
      "memoryWindow": 50                    // Messages to keep before consolidation
    }
  },
  "providers": { ... },     // See Providers section
  "hybridRouter": { ... },  // See Hybrid Router section
  "channels": { ... },      // See Channels section
  "gateway": { ... },       // See Gateway section
  "tools": { ... }          // See Tools section
}
```

---

## Providers

Each provider has an `apiKey` and optional `apiBase`. Only configure the providers you use.

### Provider Fields

| Field | Type | Description |
|-------|------|-------------|
| `apiKey` | string | API key for the provider |
| `apiBase` | string | Custom API base URL (for self-hosted or proxy setups) |
| `extraHeaders` | object | Optional custom HTTP headers (e.g., APP-Code for AiHubMix) |

### Available Providers

```jsonc
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx",
      "apiBase": ""                  // Default: https://openrouter.ai/api/v1
    },
    "anthropic": {
      "apiKey": "sk-ant-xxx"
    },
    "openai": {
      "apiKey": "sk-xxx"
    },
    "deepseek": {
      "apiKey": "sk-xxx"
    },
    "gemini": {
      "apiKey": "xxx"
    },
    "groq": {
      "apiKey": "gsk_xxx"           // Also enables voice transcription
    },
    "zhipu": {
      "apiKey": "xxx"
    },
    "dashscope": {
      "apiKey": "sk-xxx"            // For Qwen models
    },
    "moonshot": {
      "apiKey": "sk-xxx"            // For Moonshot/Kimi models
    },
    "aihubmix": {
      "apiKey": "xxx",
      "apiBase": "",                 // Default: https://aihubmix.com/v1
      "extraHeaders": {              // Optional: custom headers
        "APP-Code": "your-app-code"
      }
    },
    "vllm": {
      "apiKey": "dummy",            // Any non-empty string for local servers
      "apiBase": "http://localhost:8000/v1"
    },
    "ollama": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:11434/v1"
    },
    "minimax": {
      "apiKey": "xxx"
    },
    "custom": {                      // Any OpenAI-compatible endpoint
      "apiKey": "your-key",
      "apiBase": "https://your-endpoint.com/v1"
    },
    "openaiCodex": {                 // OAuth-based (use `nanobot provider login openai-codex`)
      "apiKey": "",                  // Managed automatically via OAuth
      "apiBase": ""
    }
  }
}
```

### Model Selection

Set the default model in `agents.defaults.model`. The provider is auto-detected by keyword matching:

| Model Name Contains | Provider Used |
|---------------------|--------------|
| `claude` | anthropic (or openrouter if no anthropic key) |
| `gpt` | openai |
| `deepseek` | deepseek |
| `gemini` | gemini |
| `qwen` | dashscope |
| `glm`, `zhipu` | zhipu |
| `ollama` | ollama |
| `minimax` | minimax |
| `codex`, `openai-codex` | openai_codex (OAuth) |
| `moonshot`, `kimi` | moonshot |
| `llama`, `mistral` | groq (or openrouter) |

If you use **OpenRouter** or **AiHubMix**, any model name works — these are gateway providers that route to all models.

### Gateway Auto-Detection

Gateway providers (OpenRouter, AiHubMix) are detected automatically by:
- **API key prefix**: `sk-or-` → OpenRouter
- **API base URL**: URL containing `openrouter` or `aihubmix`

---

## Channels

Each channel has an `enabled` flag and an `allowFrom` list for access control.

### Common Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable this channel |
| `allowFrom` | string[] | `[]` | User IDs allowed to interact. Empty = allow all |

### Telegram

```jsonc
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC-xxx",       // Bot token from @BotFather
      "allowFrom": ["123456789"]       // Telegram user IDs (get from @userinfobot)
    }
  }
}
```

### Discord

```jsonc
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",       // Bot token from Discord Developer Portal
      "allowFrom": ["123456789012"]    // Discord user IDs (enable Developer Mode to copy)
    }
  }
}
```

### WhatsApp

```jsonc
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]     // Phone numbers with country code
    }
  }
}
```

Requires Node.js ≥18 and `nanobot channels login` to scan QR code.

### Feishu (飞书)

```jsonc
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",             // From Feishu Open Platform
      "appSecret": "xxx",
      "encryptKey": "",               // Optional for Long Connection mode
      "verificationToken": "",        // Optional for Long Connection mode
      "allowFrom": []                 // Feishu user IDs (ou_xxx)
    }
  }
}
```

### DingTalk (钉钉)

```jsonc
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",      // AppKey from DingTalk Open Platform
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": []                  // DingTalk staff IDs
    }
  }
}
```

### Email

```jsonc
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,          // Explicit consent to access mailbox
      
      // IMAP (receive)
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "your-email@gmail.com",
      "imapPassword": "your-app-password",
      "imapMailbox": "INBOX",
      "imapUseSsl": true,
      
      // SMTP (send)
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "your-email@gmail.com",
      "smtpPassword": "your-app-password",
      "smtpUseTls": true,
      "smtpUseSsl": false,
      "fromAddress": "your-email@gmail.com",
      
      // Behavior
      "autoReplyEnabled": true,        // Automatically reply to emails
      "pollIntervalSeconds": 30,       // Check for new emails every 30 seconds
      "markSeen": true,                // Mark emails as read after processing
      "maxBodyChars": 12000,           // Max email body length to process
      "subjectPrefix": "Re: ",         // Prefix for reply subjects
      "allowFrom": []                  // Allowed sender email addresses (empty = allow all)
    }
  }
}
```

### Slack

```jsonc
{
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",                // "socket" mode (Socket Mode)
      "webhookPath": "/slack/events",  // Webhook path (if not using socket mode)
      "botToken": "xoxb-YOUR-BOT-TOKEN",     // Bot User OAuth Token
      "appToken": "xapp-YOUR-APP-TOKEN",     // App-Level Token (for Socket Mode)
      "userTokenReadOnly": true,       // User token is read-only
      "groupPolicy": "mention",        // "mention" (respond when @mentioned), "open" (all messages), "allowlist" (specific channels)
      "groupAllowFrom": [],            // Allowed channel IDs (if groupPolicy is "allowlist")
      "dm": {
        "enabled": true,               // Enable DM support
        "policy": "open",              // "open" (all DMs) or "allowlist" (specific users)
        "allowFrom": []                // Allowed Slack user IDs (if policy is "allowlist")
      }
    }
  }
}
```

### QQ (QQ单聊)

```jsonc
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",          // 机器人 ID (AppID) from q.qq.com
      "secret": "YOUR_APP_SECRET",     // 机器人密钥 (AppSecret) from q.qq.com
      "allowFrom": []                  // Allowed user openids (empty = public access)
    }
  }
}
```

---

## LAN Mesh

The LAN Mesh enables **device-to-device communication** on the same local network without requiring internet. Use cases include:

- **Smart home hub**: nanobot controls IoT devices (lights, AC, sensors) via local commands
- **Nanobot-to-nanobot**: Multiple nanobot instances communicate with each other on the same network
- **Private device commands**: Appliances can query nanobot for decisions without internet access

### Configuration Fields

```jsonc
{
  "channels": {
    "mesh": {
      "enabled": false,                  // Enable LAN mesh communication
      "nodeId": "",                      // Unique node identifier (auto-generated from hostname if empty)
      "tcpPort": 18800,                  // TCP port for mesh message transport
      "udpPort": 18799,                  // UDP port for peer discovery beacons
      "roles": ["nanobot"],              // Node roles for discovery (e.g., ["nanobot", "controller"])
      "allowFrom": []                    // Allowed node IDs (empty = allow all)
    }
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable mesh communication |
| `nodeId` | string | `""` | Unique node identifier. Empty = auto-generated from hostname |
| `tcpPort` | int | `18800` | TCP port for reliable message delivery |
| `udpPort` | int | `18799` | UDP port for peer discovery broadcasts |
| `roles` | string[] | `["nanobot"]` | Node roles advertised in discovery beacons |
| `allowFrom` | string[] | `[]` | Whitelist of node IDs allowed to send messages. Empty = allow all |

### Example: Smart Home Setup

Nanobot controls IoT devices in your home:

```jsonc
{
  "channels": {
    "mesh": {
      "enabled": true,
      "nodeId": "nanobot-hub",           // This nanobot is the home hub
      "tcpPort": 18800,
      "udpPort": 18799,
      "roles": ["nanobot", "home-controller"],
      "allowFrom": []                    // Allow all devices on LAN
    }
  }
}
```

In this setup:
- IoT devices (lights, AC, sensors) discover the nanobot hub via UDP beacons
- Devices connect via TCP and send commands like `{"type": "chat", "payload": {"text": "Turn on bedroom lights"}}`
- Nanobot processes the command and sends back responses

### Example: Multi-Nanobot Setup

Multiple nanobot instances collaborate on the same network:

```jsonc
{
  "channels": {
    "mesh": {
      "enabled": true,
      "nodeId": "nanobot-office",        // Unique ID for this instance
      "tcpPort": 18800,
      "udpPort": 18799,
      "roles": ["nanobot"],
      "allowFrom": [                     // Only talk to other known nanobots
        "nanobot-home",
        "nanobot-lab"
      ]
    }
  }
}
```

Use cases:
- **Work distribution**: One nanobot delegates tasks to others
- **Knowledge sharing**: Nanobots exchange information without cloud roundtrip
- **Redundancy**: If one nanobot is busy, another can handle the request

### Security Notes

- **`allowFrom` whitelist**: Restrict which nodes can send messages to prevent unauthorized access
- **LAN-only**: The mesh uses UDP/TCP on the local network and never touches the internet
- **No encryption**: Messages are transmitted in plaintext on your LAN. Use trusted networks only.

---

## Hybrid Router

The hybrid router enables dual-model routing: a local model judges task difficulty, handles easy tasks, and sanitises PII before forwarding hard tasks to an API model.

### Configuration Fields

```jsonc
{
  "hybridRouter": {
    "enabled": false,                            // Enable hybrid routing
    "localProvider": "vllm",                     // Config key of local provider
    "localModel": "meta-llama/Llama-3.1-8B-Instruct",  // Local model name
    "apiProvider": "openrouter",                 // Config key of API provider
    "apiModel": "anthropic/claude-opus-4-5",     // API model name
    "difficultyThreshold": 0.5                   // 0–1; higher = more local (default: 0.5)
  }
}
```

### How It Works

1. **Local model judges difficulty**: The local model receives the user message and returns a difficulty score (0.0–1.0).
2. **Routing decision**:
   - If score ≤ threshold → Local model processes the request
   - If score > threshold → Continue to step 3
3. **PII sanitisation**: The local model removes personally identifiable information (names, emails, phone numbers, addresses, etc.)
4. **API forwarding**: The sanitised message is sent to the API model for processing

### Example Setup

Route simple tasks to a local Llama model, send complex tasks to Claude:

```jsonc
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    },
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"  // Ignored when hybrid routing is enabled
    }
  },
  "hybridRouter": {
    "enabled": true,
    "localProvider": "vllm",
    "localModel": "meta-llama/Llama-3.1-8B-Instruct",
    "apiProvider": "openrouter",
    "apiModel": "anthropic/claude-opus-4-5",
    "difficultyThreshold": 0.6  // 60% of tasks stay local
  }
}
```

### Threshold Tuning

| Threshold | Effect |
|-----------|--------|
| `0.3` | Only trivial tasks (greetings, "hello") stay local |
| `0.5` | Balanced: simple questions local, complex reasoning to API |
| `0.7` | Most tasks stay local; only very complex tasks to API |

---

## Gateway

Controls the internal WebSocket gateway used by channels like WhatsApp.

```jsonc
{
  "gateway": {
    "host": "127.0.0.1",              // Listen address
    "port": 18790                      // Listen port
  }
}
```

---

## Tools

### Tool Configuration

```jsonc
{
  "tools": {
    "restrictToWorkspace": false,      // Restrict all tools to workspace dir
    "web": {
      "search": {
        "apiKey": "BSA-xxx"            // Brave Search API key
      }
    },
    "exec": {
      "timeout": 60                    // Shell command timeout in seconds
    }
  }
}
```

### Tool Security

| Option | Effect |
|--------|--------|
| `restrictToWorkspace: true` | All file and shell operations are confined to the workspace directory. Path traversal is blocked. |
| `exec.timeout` | Commands exceeding this timeout are killed. |
| Dangerous command blocking | Commands matching destructive patterns (`rm -rf /`, fork bombs, `mkfs`, etc.) are automatically blocked. |

### MCP Server Configuration

MCP (Model Context Protocol) allows nanobot to connect to external tool servers. Tools from MCP servers are dynamically registered and available to the agent.

```jsonc
{
  "tools": {
    "mcpServers": {
      "filesystem": {                    // Server name (your choice)
        "command": "npx",               // Stdio: command to run
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
        "env": {}                        // Extra environment variables
      },
      "remote-tools": {                  // HTTP-based MCP server
        "url": "http://localhost:3000/mcp"  // Streamable HTTP endpoint
      }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Command to run for stdio transport (e.g., `npx`, `python`) |
| `args` | string[] | Command arguments |
| `env` | object | Extra environment variables passed to the process |
| `url` | string | HTTP endpoint URL for streamable HTTP transport |

Use either `command`+`args` (stdio) or `url` (HTTP), not both.

---

## Minimal Configurations

### Simplest Setup (OpenRouter)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### Local LLM (vLLM)

```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

### Full-Featured Setup

```json
{
  "providers": {
    "openrouter": { "apiKey": "sk-or-v1-xxx" },
    "groq": { "apiKey": "gsk_xxx" }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 16384,
      "temperature": 0.7,
      "maxToolIterations": 30
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC-xxx",
      "allowFrom": ["123456789"]
    }
  },
  "tools": {
    "restrictToWorkspace": true,
    "web": {
      "search": { "apiKey": "BSA-xxx" }
    }
  }
}
```
