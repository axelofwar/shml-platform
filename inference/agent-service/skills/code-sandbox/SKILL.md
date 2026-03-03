---
name: code-sandbox
description: Execute code safely in isolated containers. Run Python, Node.js, Go, or Rust code with resource limits and no network access. Use for testing, validation, or running untrusted code.
license: MIT
compatibility: Requires Docker with Kata Containers. Needs elevated-developer role.
metadata:
  author: shml-platform
  version: "1.0"
---

# Code Sandbox Skill

## When to use this skill
Use this skill when the user asks to:
- Run/execute code
- Test a code snippet
- Validate code behavior
- Execute untrusted code safely

## Execution Environment

- **Isolation**: Kata Container VM (hardware-level isolation)
- **Memory**: 150MB per container
- **Timeout**: 10 minutes max
- **Disk**: 10GB per sandbox
- **Network**: Disabled (no external access)
- **GPU**: Not available (use Ray for GPU jobs)

## Operations

### run_python
Execute Python code.

**Parameters:**
- `code` (required): Python code to execute
- `timeout_seconds` (optional): Max execution time (default: 600)

**Example:**
```python
result = await execute("run_python", {
    "code": """
import math
print(f"Pi is {math.pi:.4f}")
for i in range(5):
    print(f"Square of {i} is {i**2}")
""",
    "timeout_seconds": 30
})
```

**Response:**
```json
{
  "stdout": "Pi is 3.1416\nSquare of 0 is 0\n...",
  "stderr": "",
  "exit_code": 0,
  "execution_time_ms": 45
}
```

### run_bash
Execute bash commands.

**Parameters:**
- `command` (required): Bash command to execute
- `timeout_seconds` (optional): Max execution time

## Supported Languages

| Language | Version | Package Manager |
|----------|---------|-----------------|
| Python | 3.10+ | pip |
| Node.js | 18+ | npm |
| Go | 1.20+ | go mod |
| Rust | 1.70+ | cargo |

## Resource Limits

- CPU: Shared (fair scheduling)
- Memory: 150MB hard limit
- Disk: 10GB
- Processes: Limited
- Network: Blocked

## Permissions

Requires `elevated-developer` or `admin` role.

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| 403 | Permission denied | Need elevated-developer role |
| 408 | Timeout | Code took too long |
| 429 | Too many sandboxes | Wait for others to complete |
| 507 | Disk full | Clean up or reduce output |

## Best Practices

1. Keep code snippets focused and small
2. Set reasonable timeouts
3. Don't try to install large packages
4. Use Ray for GPU-accelerated code
5. Clean up after yourself
