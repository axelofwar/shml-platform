---
description: "Deploy or restart a platform stack. Usage: /project:deploy <stack>"
---

# Deploy Stack

Deploy or restart the specified platform stack: **$ARGUMENTS**

## Safety Check First

```bash
./start_all_safe.sh status
```

Review the above status before proceeding.

## Restart the Stack

Based on `$ARGUMENTS`, run the appropriate command:

| Stack | Command |
|-------|---------|
| `ray` | `task restart:ray` |
| `mlflow` | `task restart:mlflow` |
| `infra` | `task restart:infra` |
| `inference` | `task restart:inference` |
| `all` | `task start` |

**⚠️ WARNING before proceeding:**
- Active Ray training jobs will be interrupted if restarting `ray`
- MLflow logging will be briefly interrupted if restarting `mlflow`
- Inference models will need to reload if restarting `inference`

Confirm the stack name from `$ARGUMENTS` is correct, then execute the restart command.

After restart, verify:
```bash
./start_all_safe.sh status
```

All services should show healthy within 60-120 seconds.
