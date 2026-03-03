---
name: shell-execution
description: Execute shell commands safely for system information, file operations, and diagnostics. Use when the user needs to run terminal commands, check system status, inspect files, or perform diagnostics that require shell access.
license: MIT
compatibility: Requires bash shell access. Some commands may need elevated permissions.
metadata:
  author: shml-platform
  version: "1.0"
allowed-tools: Bash(ls:*) Bash(cat:*) Bash(grep:*) Bash(find:*) Bash(docker:*) Bash(curl:*)
---

# Shell Execution Skill

## When to use this skill
Use this skill when the user asks to:
- Run a terminal/shell command
- Check disk space, memory, CPU usage
- List or inspect files
- Query Docker containers
- Make HTTP requests (curl)
- Debug system issues

## Safety First

### Allowed Commands (Safe)
```
nvidia-smi, docker ps, docker stats, docker logs, docker inspect,
df, free, top, cat, ls, pwd, whoami, hostname, uptime, uname,
which, echo, date, wc, head, tail, grep, find, curl, ray
```

### Blocked Commands (Dangerous)
```
rm -rf, mkfs, dd if=, shutdown, reboot, chmod 777,
:(){:|:&};:, > /dev/sda, curl | bash, wget | sh,
sudo su, passwd, any command with eval/exec
```

## Common Operations

### System Information
```bash
# Memory usage
free -h

# Disk space
df -h

# CPU info
cat /proc/cpuinfo | grep "model name" | head -1

# System uptime
uptime
```

### Docker Operations
```bash
# List running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Container logs
docker logs <container> --tail 50

# Container stats (live)
docker stats --no-stream
```

### File Operations
```bash
# List files with details
ls -la /path/to/dir

# Search in files
grep -r "pattern" /path

# Find files
find /path -name "*.py" -type f
```

## Error Handling

When a command fails:
1. Return the error message clearly
2. Suggest fixes if possible
3. If permission denied: suggest sudo or container exec
4. If command not found: PROMPT USER to install

## Interactive Prompts

If a required tool is missing, return:
```json
{
  "status": "missing_dependency",
  "missing": "nvidia-smi",
  "suggestion": "Install NVIDIA drivers: sudo apt install nvidia-driver-535",
  "prompt": "Would you like me to help install this?"
}
```
