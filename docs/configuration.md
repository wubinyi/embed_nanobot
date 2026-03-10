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
      "maxToolIterations": 30               // Max tool call rounds per message
    }
  },
  "providers": { ... },   // See Providers section
  "channels": { ... },    // See Channels section
  "gateway": { ... },     // See Gateway section
  "tools": { ... }        // See Tools section
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
    "minimax": {
      "apiKey": "xxx"               // For MiniMax models (e.g., MiniMax-M2.1)
                                    // Default apiBase: https://api.minimax.io/v1
    },
    "aihubmix": {
      "apiKey": "xxx",
      "apiBase": ""                  // Default: https://aihubmix.com/v1
    },
    "vllm": {
      "apiKey": "dummy",            // Any non-empty string for local servers
      "apiBase": "http://localhost:8000/v1"
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
| `moonshot`, `kimi` | moonshot |
| `minimax` | minimax |
| `llama`, `mistral` | groq (or openrouter) |

If you use **OpenRouter** or **AiHubMix**, any model name works — these are gateway providers that route to all models.

### Gateway Auto-Detection

Gateway providers (OpenRouter, AiHubMix) are detected automatically by:
- **API key prefix**: `sk-or-` → OpenRouter
- **API base URL**: URL containing `openrouter` or `aihubmix`

---

## Channels

Each channel has an `enabled` flag and channel-specific configuration.

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
      "consentGranted": true,            // Must be true to activate (privacy gate)

      // IMAP (receive)
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "you@gmail.com",
      "imapPassword": "app-password",
      "imapMailbox": "INBOX",
      "imapUseSsl": true,

      // SMTP (send)
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "you@gmail.com",
      "smtpPassword": "app-password",
      "smtpUseTls": true,
      "smtpUseSsl": false,
      "fromAddress": "you@gmail.com",

      // Behavior
      "autoReplyEnabled": true,          // false = read-only (no auto-replies)
      "pollIntervalSeconds": 30,
      "markSeen": true,
      "maxBodyChars": 12000,
      "subjectPrefix": "Re: ",
      "allowFrom": ["friend@example.com"]  // Allowed sender emails (empty = all)
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
      "mode": "socket",                   // "socket" is the supported mode
      "botToken": "xoxb-...",             // Bot token from Slack App settings
      "appToken": "xapp-...",             // App-level token (Socket Mode)

      // Group channel policy
      "groupPolicy": "mention",           // "mention" | "open" | "allowlist"
      "groupAllowFrom": [],               // Channel IDs (if groupPolicy = allowlist)

      // DM policy
      "dm": {
        "enabled": true,
        "policy": "open",                 // "open" | "allowlist"
        "allowFrom": []                   // User IDs (if policy = allowlist)
      }
    }
  }
}
```

**Group policy options:**
| Policy | Behavior |
|--------|----------|
| `mention` | Only responds when @mentioned in channels |
| `open` | Responds to all messages in all channels |
| `allowlist` | Only responds in channels listed in `groupAllowFrom` |

### QQ

```jsonc
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_BOT_APP_ID",        // From q.qq.com developer console
      "secret": "YOUR_BOT_APP_SECRET",
      "allowFrom": []                     // Allowed user openids (empty = public)
    }
  }
}
```

### MoChat

```jsonc
{
  "channels": {
    "mochat": {
      "enabled": true,
      "baseUrl": "https://mochat.io",
      "socketUrl": "",                     // Socket.IO URL (falls back to HTTP if empty)
      "socketPath": "/socket.io",
      "clawToken": "YOUR_TOKEN",
      "agentUserId": "AGENT_USER_ID",

      // Target sessions/panels
      "sessions": ["session-id-1"],
      "panels": ["panel-id-1"],

      // Access control
      "allowFrom": [],                     // Allowed user IDs (empty = all)

      // Mention behavior
      "mention": {
        "requireInGroups": false
      },
      "groups": {
        "group-id": { "requireMention": false }
      },

      // Reply delay for non-mention messages
      "replyDelayMode": "non-mention",     // "off" | "non-mention"
      "replyDelayMs": 120000
    }
  }
}
```

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
| Relative path safety | The safety guard correctly handles relative paths (e.g., `.venv/bin/python`) without false-positive blocking. |

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
    },
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
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
