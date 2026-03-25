---
description: "Extract key lessons from this Copilot session and record them for daily skill evolution. Run at the end of any significant work session to feed learnings into the GEPA pipeline."
---

Review the conversation history in this session and extract concrete, reusable lessons.

**Focus on:**
- Problems encountered and how they were solved
- Patterns that worked well (tools, approaches, commands)
- Mistakes made and corrected
- Platform-specific gotchas (Traefik, Ray, Docker networking, GPU allocation)
- Code patterns or conventions that proved useful

**Format each lesson as a single actionable sentence.** Examples:
- "Ray memory formula: container_memory ≥ object_store_memory + shm_size + 1GB"
- "Traefik routers need priority=2147483647 to prevent internal API interception"
- "Use `unlink` instead of `rm` for symlinks when shell policy denies rm"

**Output format (JSON Lines, one lesson per line):**
```json
{"lesson": "<lesson text>", "domain": "<domain: platform|coding|security|infrastructure|gpu|service-management>", "session_date": "<YYYY-MM-DD>", "source": "copilot"}
```

Write the output to:
`.agent/learnings/$CURRENT_DATE.jsonl`

Where `$CURRENT_DATE` is today's date as YYYY-MM-DD.

If the file already exists for today, append to it. Maximum 10 lessons per session.

After writing, confirm with: "Wrote N lessons to .agent/learnings/YYYY-MM-DD.jsonl"
