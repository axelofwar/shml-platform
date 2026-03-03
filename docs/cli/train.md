# shml train

Submit a training job from a named profile or explicit parameters.

```
shml train [OPTIONS]
```

## Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--profile` | `-p` | `TEXT` | *None* | Training profile name (e.g. `balanced`, `quick-test`) |
| `--model` | `-m` | `TEXT` | *None* | Model checkpoint |
| `--epochs` | `-e` | `INT` | *None* | Number of epochs |
| `--batch-size` | `-b` | `INT` | *None* | Batch size |
| `--imgsz` | | `INT` | *None* | Image size |
| `--data` | `-d` | `TEXT` | *None* | Path to `data.yaml` |
| `--dry-run` | | `BOOL` | `False` | Show resolved config without submitting |

## How It Works

1. If `--profile` is provided, the CLI loads the profile from `config/profiles/` via `JobConfig.from_profile()`.
2. Any explicit options (`--model`, `--epochs`, etc.) **override** the profile defaults.
3. If no profile is given, a `TrainingConfig` is built directly from the provided options.
4. The resolved configuration is sent to the platform API via `Client.submit_training()`.

!!! note "Profiles vs explicit options"
    You can combine a profile with explicit overrides. For example, `--profile balanced --epochs 5` loads the `balanced` profile but sets epochs to 5.

## Examples

### Train with a profile

```bash
shml train --profile balanced --epochs 10
```

### Quick test run

```bash
shml train --profile quick-test
```

### Explicit parameters (no profile)

```bash
shml train --model yolov8n.pt --epochs 50 --batch-size 16 --imgsz 640 \
    --data ./data/my_dataset/data.yaml
```

### Override profile defaults

```bash
shml train --profile balanced --batch-size 32 --imgsz 1280
```

### Dry run

Preview the resolved configuration without submitting a job:

```bash
shml train --profile balanced --epochs 10 --dry-run
```

Sample output:

```yaml
model: yolov8n.pt
epochs: 10
batch: 16
imgsz: 640
data_yaml: data/coco128/data.yaml
```

!!! tip "Validate before submitting"
    Use `--dry-run` to inspect your training configuration before committing GPU time. Combine with [`shml config validate`](config-commands.md#shml-config-validate) to catch errors early.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Job submitted successfully (or dry-run complete) |
| `1` | Profile not found, validation error, or submission failure |

## See Also

- [Configuration Commands](config-commands.md) — list and validate profiles
- [GPU Management](gpu.md) — ensure GPUs are available before training
- [Job Management](jobs.md) — monitor submitted jobs
