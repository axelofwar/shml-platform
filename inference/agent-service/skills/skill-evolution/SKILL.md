---
name: skill-evolution
description: "Manage and trigger GEPA (Generate-Evaluate-Prioritize-Archive) skill evolution. Use when the user asks about skill improvement, viewing skill evolution history, manually triggering evolution, or understanding how the agent learns from experience."
license: MIT
compatibility: Requires skill_evolution.py (SkillEvolutionEngine) loaded in agent-service
metadata:
  author: shml-platform
  version: "1.0"
  pattern: GEPA (from hermes-agent-self-evolution)
  trigger: autonomous (curator_node) + scheduled (02:00 UTC nightly)
allowed-tools: Bash(ls:*) Bash(cat:*) Bash(diff:*) Bash(find:*)
---

# Skill Evolution Skill (GEPA)

## When to use this skill

Activate when the user asks about:
- "How does the agent learn?"
- "Show me the agent's skill history"
- "What skills have been auto-generated?"
- "Trigger skill evolution now"
- "What lessons has the curator extracted?"
- "Improve the [X] skill based on recent sessions"
- Viewing evolution diffs or version history

## How GEPA works

```
                  ┌─────────────────────────────────────────┐
                  │         ACE Workflow (each session)       │
                  │  Generator → Tools → Reflector → Curator  │
                  └──────────────────┬──────────────────────┘
                                     │ lessons (1-3 per session)
                                     ▼
                  ┌─────────────────────────────────────────┐
                  │         SkillEvolutionEngine             │
                  │  record_lessons() → cluster_lessons()    │
                  │                                          │
                  │  If cluster.count ≥ 3 and sessions ≥ 2  │
                  │    ┌───────────────────────────────┐     │
                  │    │   No existing skill?           │     │
                  │    │   → Generate new SKILL.md      │     │
                  │    │   Existing skill?              │     │
                  │    │   → Evolve SKILL.md (v+1)     │     │
                  │    └───────────────────────────────┘     │
                  └─────────────────────────────────────────┘
                                     │
                  ┌──────────────────▼──────────────────────┐
                  │    Scheduler (nightly 02:00 UTC)          │
                  │    Runs GEPA on all accumulated lessons    │
                  └─────────────────────────────────────────┘
```

## Configuration constants (skill_evolution.py)

| Constant             | Default | Meaning                                          |
|----------------------|---------|--------------------------------------------------|
| PATTERN_THRESHOLD    | 3       | Min lesson occurrences before skill creation     |
| MIN_SESSIONS         | 2       | Must span at least N different curator sessions  |
| EVOLUTION_THRESHOLD  | 5       | Accumulated on-topic lessons to trigger evolve   |
| SIMILARITY_CUTOFF    | 0.60    | SequenceMatcher ratio to cluster as "same topic" |

## How to view evolution results

```bash
# List all auto-generated / evolved skills
find /app/skills -name "SKILL.md" | xargs ls -la

# View evolution history for a specific skill
ls /app/skills/coding-assistant/.evolution_history/

# Diff an evolved skill vs its backup
diff /app/skills/coding-assistant/.evolution_history/SKILL_20261201_020000.md \
     /app/skills/coding-assistant/SKILL.md
```

## How to manually trigger evolution

The evolution engine accumulates lessons in-memory per process restart.
To manually force evolution for testing:

```python
import asyncio
from app.skill_evolution import get_evolution_engine

engine = get_evolution_engine()
# Inject synthetic lessons to simulate pattern accumulation
test_lessons = [
    "Always validate JWT tokens before processing coding requests",
    "JWT validation errors should return 401 not 500",
    "Include token expiry check in every auth middleware",
]
for lesson in test_lessons * 3:  # 3x to exceed PATTERN_THRESHOLD
    engine.record_lessons([lesson], session_id="test-session-1")
    engine.record_lessons([lesson], session_id="test-session-2")

results = asyncio.run(engine.process_lessons([], session_id="manual-trigger"))
print(engine.summarize_evolution_results(results))
```

## Playbook integration

After evolution runs, results appear in the agent playbook under category `gepa-evolution`:
```
[GEPA] Skill evolution results:
  ✨ [created] jwt-auth: New skill 'jwt-auth' created from 9 recurring lessons
  ⬆ [evolved] coding-assistant: Evolved to v1.1: 14 lines changed
  · [skipped] gpu-monitoring: Only 2/5 lessons accumulated; deferring evolution
```

## Skill lifecycle states

```
unborn → created (auto, ≥3 patterns) → evolved (v1.1, v1.2...) → archived
                                                    ↑
                              .evolution_history/ backups preserved forever
```

## Anti-patterns

- Do not manually edit SKILL.md files while evolution is running (race condition)
- Do not delete `.evolution_history/` — it's the rollback mechanism
- Do not set PATTERN_THRESHOLD=1 — creates noisy, low-quality skills from one-off lessons
