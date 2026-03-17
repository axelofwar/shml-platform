---
name: openshell-skill
description: "Hardened code execution in NemoClaw OpenShell sandboxes with Landlock, seccomp, and netns policy enforcement. Replaces SandboxSkill for elevated-developer+ roles. Supports Python, Node.js, bash, and platform CLI tools."
license: Apache-2.0
compatibility: "nemoclaw>=0.1.0"
metadata:
  author: shml-platform
  requires_role: elevated-developer
  blueprint_required: true
allowed_tools:
  - shell
  - python
  - node
  - bash
---

# OpenShell Skill

**Purpose:** Execute code and shell commands inside a NemoClaw-managed OpenShell sandbox.
Every execution is governed by declarative policy: Landlock filesystem, seccomp syscall
filtering, network namespace egress control, and inference routing.

## When to Use

- Elevated-developer or admin role requests code execution
- Tasks requiring isolation stronger than plain Docker (Landlock + seccomp + netns)
- Agents executing multi-step operations that need GPU tools (`nvidia-smi`, Ray CLI)
- Platform code analysis (elevated: read access to `/opt/shml-platform/inference`)

## Operations

### `create_sandbox`
Create a new OpenShell sandbox for the current user+role.
```json
{
  "operation": "create_sandbox",
  "params": {
    "user_id": "user@example.com",
    "user_role": "elevated-developer",
    "session_id": "optional-session-id"
  }
}
```
Returns: `{ "sandbox_name": "shml-user-1234", "connect_cmd": "...", "blueprint": "..." }`

### `execute`
Run code/commands inside an existing sandbox.
```json
{
  "operation": "execute",
  "params": {
    "sandbox_name": "shml-user-1234",
    "code": "nvidia-smi --query-gpu=name,memory.free --format=csv",
    "language": "bash",
    "timeout_seconds": 30
  }
}
```
Returns: `{ "stdout": "...", "stderr": "...", "exit_code": 0, "sandbox_name": "..." }`

### `destroy_sandbox`
Destroy a sandbox after use.
```json
{
  "operation": "destroy_sandbox",
  "params": { "sandbox_name": "shml-user-1234" }
}
```

### `list_sandboxes`
List active sandboxes for the current user.
```json
{ "operation": "list_sandboxes", "params": {} }
```

### `status`
Get sandbox health and policy state.
```json
{
  "operation": "status",
  "params": { "sandbox_name": "shml-user-1234" }
}
```

## Policy Rules

| Role | Filesystem | Network | Inference |
|---|---|---|---|
| `viewer` | `/tmp` read-only | Web search only | N/A |
| `developer` | `/sandbox` r/w | Platform CIDR + GitHub + Brave | local vLLM |
| `elevated-developer` | `/sandbox` r/w + platform code read | + Docker proxy + ghcr.io | local vLLM |
| `admin` | Full platform (secrets excluded) | Full + NVIDIA cloud | vLLM + nimcloud |

## Error Codes

- `SANDBOX_NOT_FOUND`: Sandbox was destroyed or expired
- `POLICY_BLOCKED`: Network egress denied by OpenShell policy
- `PERMISSION_DENIED`: Role insufficient for requested blueprint
- `FACTORY_UNAVAILABLE`: NemoClaw factory sidecar unreachable (fallback to SandboxSkill)
