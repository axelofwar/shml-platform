# Cursor Integration Guide

**Last Updated:** 2025-12-04

Complete guide for integrating SHML Platform's AI models with Cursor IDE, including model switching, native features, and best practices.

---

## Overview

The SHML Platform provides an **OpenAI-compatible API** that seamlessly integrates with Cursor's AI features:

- **Chat** - Ask questions about code
- **Edit** - AI-powered code modifications  
- **Composer** - Multi-file generation and refactoring
- **Tab Completion** - Inline code suggestions
- **CMD+K** - Quick inline edits

This guide covers setting up the SHML endpoint as an additional model option in Cursor, allowing you to switch between SHML and other providers (Anthropic Claude, OpenAI GPT-4, etc.) based on your needs.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Cursor IDE                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Models Dropdown:                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │ Claude 3.5  │  │   GPT-4o    │  │ SHML Coder  │ ← Your Model    │
│  │  (Sonnet)   │  │  (OpenAI)   │  │   (Local)   │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         │                │                │                         │
│         ▼                ▼                ▼                         │
│    api.anthropic.com  api.openai.com   SHML Platform               │
└─────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                              ┌───────────────────────────────┐
                              │     SHML Platform             │
                              │  ┌─────────────────────────┐  │
                              │  │  Chat API (FastAPI)     │  │
                              │  │  - OpenAI-compatible    │  │
                              │  │  - Auto model selection │  │
                              │  └───────────┬─────────────┘  │
                              │              │                │
                              │    ┌─────────┴─────────┐      │
                              │    ▼                   ▼      │
                              │ ┌──────────┐  ┌──────────┐    │
                              │ │ Primary  │  │ Fallback │    │
                              │ │ 30B (GPU)│  │ 3B (GPU) │    │
                              │ │ RTX 3090 │  │ RTX 2070 │    │
                              │ └──────────┘  └──────────┘    │
                              └───────────────────────────────┘
```

---

## Prerequisites

- SHML Platform running with Chat API service healthy
- FusionAuth account with `developer` or `admin` role
- Cursor installed ([cursor.sh](https://cursor.sh))
- Network access to SHML Platform (Tailscale, LAN, or Funnel)

---

## Step 1: Generate an API Key

### Via Web Interface

1. Navigate to: `https://shml-platform.tail38b60a.ts.net/chat-ui/`
2. Log in with your FusionAuth credentials
3. Click **Settings** (gear icon in header)
4. Go to **API Keys** tab
5. Click **Generate New Key**
6. Name it descriptively: `Cursor - <device name>`
7. **Copy the key immediately** - it won't be shown again

### Via cURL

```bash
# First, get your OAuth cookie from browser DevTools after logging in
# Network tab → Request to /chat-ui → Copy Cookie header value

curl -X POST "https://shml-platform.tail38b60a.ts.net/chat/api-keys" \
  -H "Content-Type: application/json" \
  -H "Cookie: _sfml_oauth2=<your-oauth-cookie>" \
  -d '{"name": "Cursor - MacBook Pro"}'
```

Response:
```json
{
  "id": "key_abc123",
  "name": "Cursor - MacBook Pro",
  "key": "shml_sk_xxxxxxxxxxxxx",  // ← Save this!
  "created_at": "2025-12-04T12:00:00Z"
}
```

---

## Step 2: Configure Cursor

### Method 1: Cursor Settings UI (Recommended)

1. Open Cursor
2. Press `Cmd+,` (Mac) or `Ctrl+,` (Windows/Linux) for Settings
3. Navigate to **Models** section
4. Click **+ Add Model**
5. Fill in:

| Field | Value |
|-------|-------|
| **Name** | `SHML Coder` |
| **Provider** | `OpenAI Compatible` |
| **API Base URL** | `https://shml-platform.tail38b60a.ts.net/api/chat/v1` |
| **API Key** | `shml_sk_xxxxxxxxxxxxx` |
| **Model ID** | `auto` |

6. Click **Save**

### Method 2: settings.json (Manual)

Open Cursor settings JSON (`Cmd+Shift+P` → "Preferences: Open Settings (JSON)"):

```jsonc
{
  // ... existing settings ...

  // SHML Platform Configuration
  "cursor.aiModels": [
    {
      "name": "SHML Coder",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxxxxxxxxxxxx",
      "model": "auto",
      "enabled": true
    }
  ]
}
```

---

## Step 3: Select SHML in Cursor

Once configured, SHML appears in Cursor's model selector:

### In Chat Panel
1. Open Chat (`Cmd+L` / `Ctrl+L`)
2. Click the model dropdown at the top
3. Select **SHML Coder**

### In Composer
1. Open Composer (`Cmd+I` / `Ctrl+I`)
2. Click model selector
3. Choose **SHML Coder**

### For Inline Edit (CMD+K)
1. Select code
2. Press `Cmd+K` / `Ctrl+K`
3. Model selection applies from your last chat/composer choice

---

## Model Selection Options

The SHML API supports different model targets:

| Model ID | Description | Best For |
|----------|-------------|----------|
| `auto` | **Recommended** - Routes to best available model | General use |
| `primary` | 30B model (Qwen3-Coder-30B) on RTX 3090 Ti | Complex refactoring, architecture decisions |
| `fallback` | 3B model (Qwen2.5-Coder-3B) on RTX 2070 | Quick completions, simple edits |
| `qwen3-coder-30b` | Explicit 30B model name | When you need the large model specifically |
| `qwen2.5-coder-3b` | Explicit 3B model name | Fast responses, lower GPU usage |

### Changing Model in Cursor

You can add multiple SHML configurations for different models:

```jsonc
{
  "cursor.aiModels": [
    {
      "name": "SHML Auto",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxx",
      "model": "auto",
      "enabled": true
    },
    {
      "name": "SHML 30B (Quality)",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxx",
      "model": "primary",
      "enabled": true
    },
    {
      "name": "SHML 3B (Fast)",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxx",
      "model": "fallback",
      "enabled": true
    }
  ]
}
```

---

## Switching Between SHML and Cloud Models

### Quick Model Switching

Cursor makes it easy to switch models mid-conversation:

1. **In Chat**: Click model name → Select different model
2. **In Composer**: Same dropdown, different context
3. **Keyboard**: No default shortcut, but you can add one

### When to Use Which Model

| Use Case | Recommended Model |
|----------|-------------------|
| Quick autocomplete | SHML 3B (Fast) or Claude |
| Code review | SHML Auto or Claude |
| Complex refactoring | SHML 30B or GPT-4 |
| Learning/explanations | Claude (better at teaching) |
| Private/sensitive code | **SHML** (local, no cloud) |
| Multi-file generation | Composer + SHML Auto |

### Privacy Considerations

**SHML Platform benefits:**
- ✅ Code stays on your local network
- ✅ No data sent to external APIs
- ✅ Full control over model and data
- ✅ No rate limits from cloud providers

**When to use cloud models:**
- Complex reasoning tasks (Claude excels here)
- When SHML models are unavailable (training)
- Need for specific cloud model capabilities

---

## Cursor Native Features with SHML

### Chat (`Cmd+L`)

Works fully with SHML:
- Context from open files ✅
- @-mentions for files ✅  
- Conversation history ✅
- Code block actions ✅

### Composer (`Cmd+I`)

Works fully:
- Multi-file editing ✅
- Step-by-step plans ✅
- Accept/reject changes ✅

### Tab Completion

Works with caveats:
- Inline suggestions ✅
- May be slower than cloud (local inference)
- Use `fallback` model for faster completions

### CMD+K Inline Edit

Works fully:
- Selection-based edits ✅
- Natural language instructions ✅
- Diff preview ✅

### @ Context References

Fully supported:
- `@file` - Reference specific files
- `@folder` - Reference directories
- `@codebase` - Semantic search
- `@docs` - Documentation search
- `@web` - Web search (if enabled)

---

## Rate Limits

| Role | Requests/Minute | Daily Limit |
|------|-----------------|-------------|
| Developer | 100 | Unlimited |
| Admin | Unlimited | Unlimited |
| Viewer | 20 | 500 |

Check your rate limit status:
```bash
curl "https://shml-platform.tail38b60a.ts.net/chat/rate-limit" \
  -H "Authorization: Bearer shml_sk_xxx"
```

---

## Persistent Instructions

Sync custom instructions across all your devices:

### Create Instruction
```bash
curl -X POST "https://shml-platform.tail38b60a.ts.net/chat/instructions" \
  -H "Authorization: Bearer shml_sk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Style",
    "content": "Always use TypeScript. Follow Airbnb style guide. Add comprehensive JSDoc comments. Prefer functional patterns over classes.",
    "enabled": true
  }'
```

### List Instructions
```bash
curl "https://shml-platform.tail38b60a.ts.net/chat/instructions" \
  -H "Authorization: Bearer shml_sk_xxx"
```

---

## Troubleshooting

### "Model not available"

The 30B model may be yielded to training jobs. The API automatically falls back to 3B.

**Check model status:**
```bash
curl "https://shml-platform.tail38b60a.ts.net/chat/v1/models" \
  -H "Authorization: Bearer shml_sk_xxx"
```

### Slow Responses

1. Use `fallback` model for faster inference
2. Check Ray dashboard for GPU utilization
3. Primary model is slower but higher quality

### Authentication Failed

1. Verify API key is correct (starts with `shml_`)
2. Check key hasn't been revoked
3. Ensure your FusionAuth account has `developer` role
4. Try generating a new key

### Connection Refused

1. Verify SHML Platform is running: `docker ps | grep chat-api`
2. Check Tailscale connection if remote
3. Verify URL is correct in Cursor settings

### Cursor Can't Find Model

1. Ensure "OpenAI Compatible" provider is selected
2. API Base URL must end with `/v1`
3. Try restarting Cursor after config changes

---

## API Reference

Full endpoint documentation: [API_REFERENCE.md](./API_REFERENCE.md)

### Quick Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completion (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/api-keys` | POST | Create API key |
| `/api-keys` | GET | List your keys |
| `/api-keys/:id` | DELETE | Revoke key |
| `/rate-limit` | GET | Check rate limit status |
| `/conversations` | GET/POST | Manage conversations |
| `/instructions` | GET/POST | Manage persistent instructions |

---

## Security Best Practices

1. **Never commit API keys** - Use environment variables
2. **Rotate keys regularly** - Regenerate every 90 days
3. **Use descriptive names** - "Cursor - Work MacBook 2024"
4. **Revoke unused keys** - Delete keys for old devices
5. **Monitor usage** - Check rate limit endpoint for anomalies

---

## Web Chat vs API (Cursor)

| Feature | Web Chat (`/chat-ui/`) | API (Cursor) |
|---------|------------------------|--------------|
| Mode | Ask-only | Full editing |
| File editing | ❌ Cannot edit | ✅ Full access |
| Code execution | ❌ Cannot execute | ✅ Via Cursor |
| Security | Safe for non-devs | Dev-only access |
| Best for | Questions, learning | Active development |

The web interface intentionally restricts capabilities for security. Cursor with API access gets full editing capabilities because it's assumed to be used by developers in their own environment.

---

## Example Workflows

### 1. Code Review with SHML

```
1. Open PR diff in Cursor
2. Cmd+L to open chat
3. Select "SHML Auto"
4. Type: "Review this code for bugs and improvements"
5. SHML analyzes with full context awareness
```

### 2. Refactoring with Composer

```
1. Cmd+I for Composer
2. Select "SHML 30B (Quality)"
3. Type: "Refactor this module to use dependency injection"
4. Review multi-file plan
5. Accept changes
```

### 3. Quick Fix with CMD+K

```
1. Select broken code
2. Cmd+K
3. Type: "Fix the TypeScript error"
4. Review diff
5. Accept
```

---

## Appendix: Full settings.json Example

```jsonc
{
  // Cursor AI Models Configuration
  "cursor.aiModels": [
    // SHML Platform Models (Local)
    {
      "name": "SHML Auto",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxxxxxxxxxxxx",
      "model": "auto",
      "enabled": true
    },
    {
      "name": "SHML 30B (Quality)",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxxxxxxxxxxxx",
      "model": "primary",
      "enabled": true
    },
    {
      "name": "SHML 3B (Fast)",
      "provider": "openai-compatible",
      "apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
      "apiKey": "shml_sk_xxxxxxxxxxxxx",
      "model": "fallback",
      "enabled": true
    }
    // Cloud models (Claude, GPT-4) use Cursor's built-in config
  ],

  // Default model for new conversations
  "cursor.defaultModel": "SHML Auto",

  // Tab completion model (use fast model)
  "cursor.tabCompletionModel": "SHML 3B (Fast)"
}
```

---

## Related Documentation

- [CURSOR_SETUP.md](../CURSOR_SETUP.md) - Quick setup guide
- [API_REFERENCE.md](./API_REFERENCE.md) - Full API documentation
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Platform architecture
- [SECURITY.md](../SECURITY.md) - Security considerations
