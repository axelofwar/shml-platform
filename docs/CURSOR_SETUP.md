# Cursor Setup Guide

Configure Cursor to use the SHML Platform's AI models for code completion, chat, and editing.

## Overview

The SHML Platform provides an OpenAI-compatible API that works with Cursor and other AI-powered editors. This guide shows you how to:

1. Generate an API key
2. Configure Cursor to use the SHML endpoint
3. Set up persistent instructions (optional)

## Prerequisites

- SHML Platform running with Chat API service
- Developer or Admin role in FusionAuth
- Cursor installed ([download here](https://cursor.sh))

## Step 1: Generate an API Key

### Option A: Web Interface

1. Navigate to `https://shml-platform.tail38b60a.ts.net/chat-ui/`
2. Log in with your FusionAuth credentials
3. Go to **Settings** → **API Keys**
4. Click **Generate New Key**
5. Give it a descriptive name (e.g., "Cursor - Work Laptop")
6. Copy the key (starts with `shml_`)

### Option B: API Request

```bash
# Authenticate first (get your OAuth token from browser DevTools)
curl -X POST "https://shml-platform.tail38b60a.ts.net/chat/api-keys" \
  -H "Content-Type: application/json" \
  -H "Cookie: _sfml_oauth2=<your-cookie>" \
  -d '{"name": "Cursor - Work Laptop"}'
```

## Step 2: Configure Cursor

### Settings (UI)

1. Open Cursor
2. Go to **Settings** → **Models**
3. Click **+ Add Model**
4. Configure:
   - **Name**: `SHML Coder`
   - **API Base**: `https://shml-platform.tail38b60a.ts.net/api/chat/v1`
   - **API Key**: `shml_<your-key>`
   - **Model ID**: `auto` (or `primary` for 30B, `fallback` for 3B)

### settings.json (Manual)

Add to your Cursor settings:

```json
{
  "openai.apiBase": "https://shml-platform.tail38b60a.ts.net/api/chat/v1",
  "openai.apiKey": "shml_<your-key>",
  "openai.model": "auto"
}
```

## Model Selection

| Model | Description | Best For |
|-------|-------------|----------|
| `auto` | Automatically selects based on query complexity | General use |
| `primary` / `qwen3-coder-30b` | 30B parameter model (RTX 3090 Ti) | Complex refactoring, architecture |
| `fallback` / `qwen2.5-coder-3b` | 3B parameter model (RTX 2070) | Quick completions, simple edits |

## Rate Limits

| Role | Requests/Minute |
|------|-----------------|
| Developer | 100 |
| Admin | Unlimited |
| Viewer | 20 |

## Persistent Instructions

You can set instructions that persist across sessions and sync across devices.

### Create Instructions

```bash
curl -X POST "https://shml-platform.tail38b60a.ts.net/chat/instructions" \
  -H "Authorization: Bearer shml_<your-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Style",
    "content": "Use TypeScript for all JavaScript code. Follow the Airbnb style guide. Add JSDoc comments to all functions."
  }'
```

### List Instructions

```bash
curl "https://shml-platform.tail38b60a.ts.net/chat/instructions" \
  -H "Authorization: Bearer shml_<your-key>"
```

## Conversation History Sync

All conversations are synced across devices. To access from the API:

```bash
# List conversations
curl "https://shml-platform.tail38b60a.ts.net/chat/conversations" \
  -H "Authorization: Bearer shml_<your-key>"

# Get specific conversation
curl "https://shml-platform.tail38b60a.ts.net/chat/conversations/<id>" \
  -H "Authorization: Bearer shml_<your-key>"
```

## Troubleshooting

### "Rate limited" error

You've exceeded your role's rate limit. Wait 60 seconds or ask an admin to upgrade your role.

### "Model unavailable" error

The primary 30B model may be yielded to training. The API will automatically fall back to the 3B model. If both are unavailable, check the Ray dashboard for training status.

### Authentication errors

1. Ensure your API key is valid
2. Check the key hasn't expired
3. Try regenerating a new key

### Slow responses

- Use `model: "fallback"` for faster responses
- The 30B model takes longer but produces better results for complex queries

## API Reference

See [API_REFERENCE.md](./API_REFERENCE.md) for full API documentation.

### Quick Reference

```
POST /v1/chat/completions - Chat completion (OpenAI-compatible)
GET  /v1/models           - List available models
POST /api-keys            - Create API key
GET  /api-keys            - List your API keys
DELETE /api-keys/:id      - Revoke API key
GET  /rate-limit          - Check your rate limit status
GET  /conversations       - List conversations
POST /conversations       - Create conversation
GET  /conversations/:id   - Get conversation with messages
DELETE /conversations/:id - Delete conversation
POST /instructions        - Create instruction
GET  /instructions        - List instructions
PUT  /instructions/:id    - Update instruction
DELETE /instructions/:id  - Delete instruction
```

## Security Notes

- API keys are scoped to your user account
- Keys inherit your FusionAuth role (developer/admin/viewer)
- Revoke keys immediately if compromised
- Keys can be set to expire automatically

## Differences from Web Chat

The web chat at `/chat-ui/` operates in **Ask Mode Only** - it can answer questions but cannot edit files or execute commands. This is intentional for security.

When using Cursor with the API:
- Full editing capabilities are available
- The AI can suggest and apply code changes
- No ask-only restrictions apply

This allows developers to safely share the web chat with non-developers while maintaining full editing capabilities in their development environment.
