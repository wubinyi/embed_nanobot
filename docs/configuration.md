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
    "siliconflow": {
      "apiKey": "xxx",
      "apiBase": ""                  // Default: https://api.siliconflow.cn/v1
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
    },
    "githubCopilot": {               // OAuth-based (use `nanobot provider login github-copilot`)
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
| `siliconflow` | siliconflow |
| `codex`, `openai-codex` | openai_codex (OAuth) |
| `copilot`, `github_copilot` | github_copilot (OAuth) |
| `moonshot`, `kimi` | moonshot |
| `llama`, `mistral` | groq (or openrouter) |

If you use **OpenRouter** or **AiHubMix**, any model name works — these are gateway providers that route to all models.

### Gateway Auto-Detection

Gateway providers (OpenRouter, AiHubMix, SiliconFlow) are detected automatically by:
- **API key prefix**: `sk-or-` → OpenRouter
- **API base URL**: URL containing `openrouter`, `aihubmix`, or `siliconflow`

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
      "allowFrom": ["123456789"],      // Telegram user IDs (get from @userinfobot)
      "proxy": "socks5://host:port"    // Optional: SOCKS5 proxy for restricted networks
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
      "replyInThread": true,            // Reply in threads (default: true)
      "reactEmoji": "eyes",              // React to messages with this emoji (default: "eyes")
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

### Mochat

Mochat is an open-source IM platform. nanobot connects via Socket.IO with support for session/panel watching, per-group mention rules, and reconnect with backoff.

```jsonc
{
  "channels": {
    "mochat": {
      "enabled": true,
      "baseUrl": "https://mochat.io",
      "socketUrl": "",                    // Socket.IO server URL (defaults to baseUrl)
      "socketPath": "/socket.io",
      "socketDisableMsgpack": false,      // Disable msgpack encoding
      "socketReconnectDelayMs": 1000,
      "socketMaxReconnectDelayMs": 10000,
      "socketConnectTimeoutMs": 10000,
      "refreshIntervalMs": 30000,
      "watchTimeoutMs": 25000,
      "watchLimit": 100,
      "retryDelayMs": 500,
      "maxRetryAttempts": 0,              // 0 = unlimited retries
      "clawToken": "YOUR_CLAW_TOKEN",
      "agentUserId": "YOUR_AGENT_USER_ID",
      "sessions": [],                     // Session IDs to watch
      "panels": [],                       // Panel IDs to watch
      "allowFrom": [],                    // Allowed user IDs
      "mention": {
        "requireInGroups": false          // Require @mention in group chats
      },
      "groups": {                         // Per-group mention overrides
        "group-id-1": { "requireMention": true }
      },
      "replyDelayMode": "non-mention",    // "off" or "non-mention"
      "replyDelayMs": 120000
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
      "allowFrom": [],                   // Allowed node IDs (empty = allow all)
      "pskAuthEnabled": true,            // Enable HMAC-PSK authentication for mesh messages
      "keyStorePath": "",                // Path to mesh_keys.json (default: <workspace>/mesh_keys.json)
      "allowUnauthenticated": false,     // If true, log warning but still process unsigned messages
      \"nonceWindow\": 60,                 // Seconds; reject messages with ts outside this window
      \"enrollmentPinLength\": 6,          // Number of digits in enrollment PIN
      \"enrollmentPinTimeout\": 300,       // Seconds before PIN expires (default 5 min)
      "enrollmentMaxAttempts": 3,        // Max failed PIN attempts before lockout
      "encryptionEnabled": true,          // Enable AES-256-GCM payload encryption (requires cryptography package)
      "registryPath": "",                    // Path to device_registry.json (default: <workspace>/device_registry.json)
      "automationRulesPath": "",             // Path to automation_rules.json (default: <workspace>/automation_rules.json)
      "mtlsEnabled": false,                  // Enable mTLS with local CA for device authentication
      "caDir": "",                           // Path to CA directory (default: <workspace>/mesh_ca/)
      "deviceCertValidityDays": 365,          // Validity period for device certificates in days
      "firmwareDir": "",                      // Directory for firmware images (empty = OTA disabled)
      "otaChunkSize": 4096,                   // Bytes per OTA transfer chunk (default 4KB)
      "otaChunkTimeout": 30,                  // Seconds to wait for chunk ACK
      "groupsPath": "",                       // Path to groups.json (default: <workspace>/groups.json)
      "scenesPath": "",                       // Path to scenes.json (default: <workspace>/scenes.json)
      "dashboardPort": 0                        // HTTP port for monitoring dashboard (0 = disabled)
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
| `pskAuthEnabled` | bool | `true` | Enable HMAC-SHA256 authentication using per-device PSKs |
| `keyStorePath` | string | `""` | Path to key store file. Empty = `<workspace>/mesh_keys.json` |
| `allowUnauthenticated` | bool | `false` | Process unsigned messages with warning (dev only) |
| `nonceWindow` | int | `60` | Seconds; reject messages with timestamps outside this window |
| `enrollmentPinLength` | int | `6` | Number of digits in enrollment PIN |
| `enrollmentPinTimeout` | int | `300` | Seconds before PIN expires (default 5 min) |
| `enrollmentMaxAttempts` | int | `3` | Max failed PIN attempts before lockout |
| `encryptionEnabled` | bool | `true` | Enable AES-256-GCM payload encryption. Requires `cryptography` package. |
| `registryPath` | string | `""` | Path to device registry file. Empty = `<workspace>/device_registry.json` |
| `automationRulesPath` | string | `""` | Path to automation rules file. Empty = `<workspace>/automation_rules.json` |
| `mtlsEnabled` | bool | `false` | Enable mutual TLS with a local Certificate Authority. When enabled, the Hub generates a self-signed root CA and issues per-device X.509 certificates. TLS replaces HMAC/AES-GCM at the transport layer. Requires `cryptography`. |
| `caDir` | string | `""` | Path to directory storing CA key, cert, and device certificates. Empty = `<workspace>/mesh_ca/` |
| `deviceCertValidityDays` | int | `365` | Validity period for newly issued device certificates (days). CA cert is always 10 years. |
| `firmwareDir` | string | `""` | Directory for OTA firmware images and manifest. Empty = OTA disabled. When set, the Hub can push firmware updates to mesh devices. |
| `otaChunkSize` | int | `4096` | Bytes per OTA transfer chunk. Default 4KB is suitable for ESP32 SRAM. |
| `otaChunkTimeout` | int | `30` | Seconds to wait for a device to acknowledge a firmware chunk before considering it lost. |
| `groupsPath` | string | `""` | Path to device groups JSON file. Empty = `<workspace>/groups.json`. Groups are named collections of device node_ids (e.g., "living_room"). |
| `scenesPath` | string | `""` | Path to scenes JSON file. Empty = `<workspace>/scenes.json`. Scenes are named batches of device commands (e.g., "good_night"). |
| `dashboardPort` | int | `0` | HTTP port for the monitoring dashboard. When > 0, an embedded web dashboard starts at `http://<host>:<port>/` with JSON API at `/api/*`. Set to `0` (default) to disable. |

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

- **PSK authentication (default: enabled)**: Every mesh message is signed with HMAC-SHA256 using a per-device Pre-Shared Key. Unauthenticated messages are rejected unless `allowUnauthenticated` is set to `true`.
- **Key store**: Device PSKs are stored in `mesh_keys.json` with `0600` file permissions. Use `keyStorePath` to customise the location.
- **Replay protection**: Each message includes a random nonce and timestamp. Duplicate nonces and messages outside the `nonceWindow` are rejected.
- **`allowFrom` whitelist**: Restrict which nodes can send messages to prevent unauthorized access.
- **LAN-only**: The mesh uses UDP/TCP on the local network and never touches the internet.
- **`allowUnauthenticated` (dev only)**: Set to `true` during development to accept unsigned messages with a warning. **Never enable in production.**
- **Encryption (default: enabled)**: Message payloads are encrypted with AES-256-GCM using a key derived from the device's PSK (`HMAC-SHA256(PSK, "mesh-encrypt-v1")`). Only CHAT, COMMAND, and RESPONSE payloads are encrypted; heartbeats and enrollment messages are plaintext. Requires the `cryptography` package (`pip install cryptography`). Set `encryptionEnabled` to `false` to disable.
- **mTLS (optional)**: When `mtlsEnabled` is `true`, the Hub runs a local Certificate Authority and wraps all TCP connections with mutual TLS (EC P-256 certs). Devices receive certificates during enrollment. TLS provides both authentication and encryption at the transport layer, so HMAC and AES-GCM layers are automatically skipped (redundant). CA and device private keys are stored with `0600` permissions.

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
    "difficultyThreshold": 0.5,                  // 0-1; higher = more local (default: 0.5)
    "fallbackToLocal": true,                      // Fall back to local when API is unreachable (default: true)
    "circuitBreakerThreshold": 3,                 // Consecutive API failures before circuit opens (default: 3)
    "circuitBreakerTimeout": 300                  // Seconds to route all to local after circuit opens (default: 300)
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
5. **Fallback**: If the API call fails (network error, timeout), the router falls back to the local model using the original (unsanitised) messages
6. **Circuit breaker**: After N consecutive API failures, the router routes ALL traffic to local for M seconds, then retries

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
