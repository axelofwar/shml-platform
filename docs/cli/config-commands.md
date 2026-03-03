# Configuration Commands

Inspect and validate platform configuration and training profiles.

---

## shml config show

Display the current platform configuration loaded from environment variables.

```
shml config show
```

Reads settings via `PlatformConfig.from_env()` and displays all fields.

### Example

```bash
shml config show
```

Rich output:

```
     Platform Configuration
┌──────────────┬──────────────────────────────┐
│ Setting      │ Value                        │
├──────────────┼──────────────────────────────┤
│ base_url     │ http://localhost:8265         │
│ mlflow_url   │ http://localhost:5000         │
│ gpu_count    │ 1                            │
│ log_level    │ INFO                         │
└──────────────┴──────────────────────────────┘
```

Without Rich, settings are printed as `key: value` pairs.

---

## shml config list-profiles

List all available training profiles from `config/profiles/`.

```
shml config list-profiles
```

### Example

```bash
shml config list-profiles
```

Rich output:

```
          Training Profiles
┌────────────┬────────────┬────────┬───────┬───────┬───────────────────────┐
│ Name       │ Model      │ Epochs │ Batch │ ImgSz │ File                  │
├────────────┼────────────┼────────┼───────┼───────┼───────────────────────┤
│ balanced   │ yolov8n.pt │ 100    │ 16    │ 640   │ config/profiles/…     │
│ quick-test │ yolov8n.pt │ 5      │ 8     │ 320   │ config/profiles/…     │
└────────────┴────────────┴────────┴───────┴───────┴───────────────────────┘
```

!!! info
    If no profiles are found, the CLI prints: `No profiles found in config/profiles/`. Create YAML profile files in that directory to get started.

---

## shml config validate

Validate a training profile by loading it through `JobConfig.from_profile()`.

```
shml config validate PROFILE
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `PROFILE` | `TEXT` | Profile name to validate (required) |

### Example

```bash
shml config validate balanced
```

```
✓ Profile 'balanced' is valid
  model=yolov8n.pt, epochs=100, batch=16, imgsz=640
```

If validation fails:

```bash
shml config validate nonexistent
```

```
Error: Profile 'nonexistent' validation failed: FileNotFoundError…
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Profile is valid |
| `1` | Validation failed |

!!! tip "Pre-flight check"
    Run `shml config validate <profile>` before `shml train --profile <profile>` to catch configuration errors without consuming GPU resources.
