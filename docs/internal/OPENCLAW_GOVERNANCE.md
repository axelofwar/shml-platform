# OpenClaw Governance (Cost, Control, Learning)

This document defines SHML's OpenClaw-first governance for model routing, admin controls, and adaptive memory.

## Scope

- Cost-aware tiered routing
- Cancel and override controls
- Homer + Discord operator surfaces
- Security boundaries (OAuth2, Tailscale, role-gated admin)
- Learning loop from outcomes

## Runtime Policy

Policy file: `/home/axelofwar/Projects/shml-platform/.openclaw/governance.policy.yaml`

Routing tiers:
1. `local-fast` → `nemotron-local/nemotron-coding`
2. `remote-balanced` → `github-copilot/claude-sonnet-4.6`
3. `remote-premium` → `github-copilot/claude-opus-4.6`

Escalation is failure-driven and complexity-aware; downgrade triggers when work returns to low complexity or budget pressure increases.

## Admin Control Plane

Operator script:
`/home/axelofwar/Projects/shml-platform/scripts/openclaw/openclaw_governor.sh`

Capabilities:
- `status`: gateway + sessions view
- `budget`: show active budget guardrails
- `cancel`: emergency cancel via gateway restart
- `override`: tier override with mandatory reason and audit
- `learn`: append success/failure outcomes for memory evolution

Audit logs:
- `.openclaw/logs/governance-decisions.jsonl`
- `.openclaw/logs/governance-overrides.jsonl`

## Homer Surface

Homer provides control entry points in the admin section:
- OpenClaw Dashboard
- OpenClaw Governance Runbook
- OpenClaw Command Sheet

## Discord Surface

Discord command contract is routed through OpenClaw messaging and restricted to the admin channel.

Suggested command namespace: `!oc`

Examples:
- `!oc status`
- `!oc budget`
- `!oc cancel <reason>`
- `!oc override <tier> <reason>`
- `!oc resume`

## Security Requirements

- Keep Traefik OAuth middleware on all exposed admin routes.
- Keep Tailscale/Funnel as primary remote access boundary.
- Never post secrets/tokens in chat responses.
- Log all cancel/override actions.

## Adaptive Learning Loop

Every incident or override should be logged via:

```bash
scripts/openclaw/openclaw_governor.sh learn <success|failure|partial> "<short outcome>"
```

Weekly process:
1. Review governance logs.
2. Promote reliable patterns into `.openclaw/CONTEXT.md`.
3. Tighten escalation/downgrade criteria in `governance.policy.yaml`.
