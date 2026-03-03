# Job Management

Commands for monitoring, inspecting, and cancelling training jobs.

---

## shml status

Get the current status of a job.

```
shml status JOB_ID
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `JOB_ID` | `TEXT` | Job ID to check (required) |

### Example

```bash
shml status abc123def456
```

With Rich installed, output is rendered as a table:

```
┌──────────────────────────┐
│      Job abc123def456    │
├─────────┬────────────────┤
│ Field   │ Value          │
├─────────┼────────────────┤
│ Name    │ balanced-run-7 │
│ Status  │ RUNNING        │
│ epoch   │ 4/10           │
└─────────┴────────────────┘
```

Without Rich, plain text is printed: `balanced-run-7: RUNNING`

---

## shml logs

Retrieve logs from a job.

```
shml logs JOB_ID [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `JOB_ID` | `TEXT` | Job ID to get logs for (required) |

### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--follow` | `-f` | `BOOL` | `False` | Follow log output |

### Example

```bash
# Print logs
shml logs abc123def456

# Follow (stream) logs
shml logs abc123def456 --follow
```

---

## shml cancel

Cancel a running job.

```
shml cancel JOB_ID [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `JOB_ID` | `TEXT` | Job ID to cancel (required) |

### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--reason` | `-r` | `TEXT` | *None* | Cancellation reason |

### Example

```bash
shml cancel abc123def456 --reason "wrong dataset"
```

!!! warning
    Cancelling a job is **irreversible**. The job's status will be set to `CANCELLED`.

---

## shml list

List recent jobs.

```
shml list [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--status` | `-s` | `TEXT` | *None* | Filter by status (e.g. `RUNNING`, `SUCCEEDED`, `FAILED`) |
| `--limit` | `-n` | `INT` | `20` | Number of jobs to show |

### Example

```bash
# List last 20 jobs
shml list

# Show only running jobs
shml list --status RUNNING

# Show last 5 failed jobs
shml list --status FAILED --limit 5
```

Sample Rich output:

```
           Jobs
┌──────────────┬────────────┬───────────┐
│ ID           │ Name       │ Status    │
├──────────────┼────────────┼───────────┤
│ abc123def456 │ balanced-7 │ SUCCEEDED │
│ def789ghi012 │ quick-3    │ RUNNING   │
│ jkl345mno678 │ balanced-8 │ FAILED    │
└──────────────┴────────────┴───────────┘
```

!!! info "Status colors"
    With Rich, statuses are color-coded: **green** for `SUCCEEDED`, **yellow** for `RUNNING`, **red** for `FAILED`.
