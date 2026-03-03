---
name: openclaw-governor
description: Govern OpenClaw model routing, budget guardrails, emergency cancellation, and override auditing for SHML platform operations.
---

# OpenClaw Governor

## Overview

Use this skill to enforce cost-aware routing and provide a single control plane for:
- model tier selection
- run cancellation
- budget governance
- override auditing
- learning updates

## Policy Source of Truth

- `/home/axelofwar/Projects/shml-platform/.openclaw/governance.policy.yaml`

## Operator Script

- `/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh`

## Workflow

### 1) Check current status

```bash
/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh status
```

### 2) Validate budget state

```bash
/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh budget
```

### 3) Apply manual override (requires reason)

```bash
/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh override remote-premium "security hotfix"
```

### 4) Cancel active run (emergency)

```bash
/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh cancel "operator requested"
```

### 5) Record outcome for adaptive memory

```bash
/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh learn success "balanced tier solved issue in one pass"
```

## Discord Control Contract

Use OpenClaw channel messaging and keep control commands in the admin channel only.

### Suggested Admin Commands

- `!oc status`
- `!oc budget`
- `!oc cancel <reason>`
- `!oc override <tier> <reason>`
- `!oc resume`

### Transport Examples

```bash
openclaw message send --channel discord --target channel:platform-admin --message "!oc status"
openclaw message send --channel discord --target channel:platform-admin --message "!oc budget"
```

## Safety Rules

1. Do not run premium tier when hard budget threshold is reached unless override is logged.
2. Never expose secrets in channel responses.
3. Keep all override and cancellation actions in audit logs.
4. Keep OAuth/Tailscale constraints unchanged.
