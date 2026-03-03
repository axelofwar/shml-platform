# OpenClaw Command Sheet (SHML)

## Core Status

```bash
openclaw status --all
openclaw gateway status
openclaw sessions --all-agents
openclaw skills list
openclaw skills check
```

## Autonomous Ops (5-minute loop)

```bash
scripts/openclaw/openclaw_autonomous_manager.sh
scripts/openclaw/install_autonomous_manager_timer.sh
systemctl --user status openclaw-autonomous-manager.timer
journalctl --user -u openclaw-autonomous-manager.service -n 100 --no-pager

# Optional tuning (demote only after N degraded polls)
CONSECUTIVE_DEGRADE_THRESHOLD=2
MAX_NEMOTRON_HEALTH_LATENCY_MS=2500
```

## Agent Execution

```bash
openclaw agent --agent main --message "Run platform-health skill and summarize issues"
openclaw agent --agent local --message "Scaffold minimal patch and tests"
openclaw agent --agent main --session-id <session_id> --message "continue"
```

## Model/Provider Controls

```bash
openclaw models --help
openclaw channels list --json
openclaw config --help
```

## Governance Controls (Local)

```bash
scripts/openclaw/openclaw_governor.sh status
scripts/openclaw/openclaw_governor.sh budget
scripts/openclaw/openclaw_governor.sh override remote-balanced "normal implementation"
scripts/openclaw/openclaw_governor.sh cancel "operator manual stop"
scripts/openclaw/openclaw_governor.sh learn success "local-fast handled planning"
```

## Discord Controls (Admin Channel)

```bash
openclaw message send --channel discord --target channel:platform-admin --message "!oc status"
openclaw message send --channel discord --target channel:platform-admin --message "!oc budget"
openclaw message send --channel discord --target channel:platform-admin --message "!oc cancel stuck-run"
openclaw message send --channel discord --target channel:platform-admin --message "!oc override remote-premium security-hotfix"
```

## Emergency Recovery

```bash
openclaw gateway restart
openclaw gateway probe
openclaw sessions cleanup
```

## Native Skill Operations

```bash
openclaw skills info platform-health
openclaw skills info openclaw-governor
```

## Notes

- Default routing policy is defined in `.openclaw/governance.policy.yaml`.
- Keep premium use behind budget thresholds and override logging.
- Keep admin and Discord controls constrained to authenticated operators.
