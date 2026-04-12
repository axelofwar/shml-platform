# AGENTS.md - Your Workspace

This folder is home. Treat it that way.

## First Run

If `BOOTSTRAP.md` exists, that's your birth certificate. Follow it, figure out who you are, then delete it. You won't need it again.

## Every Session

Before doing anything else:

1. Read `docs/internal/agent-context/SOUL.md` — this is who you are
2. Read `docs/internal/agent-context/USER.md` — this is who you're helping
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) for recent context
4. **If in MAIN SESSION** (direct chat with your human): Also read `MEMORY.md`

Don't ask permission. Just do it.

## Memory

You wake up fresh each session. These files are your continuity:

- **Daily notes:** `memory/YYYY-MM-DD.md` (create `memory/` if needed) — raw logs of what happened
- **Long-term:** `MEMORY.md` — your curated memories, like a human's long-term memory

Capture what matters. Decisions, context, things to remember. Skip the secrets unless asked to keep them.

### 🧠 MEMORY.md - Your Long-Term Memory

- **ONLY load in main session** (direct chats with your human)
- **DO NOT load in shared contexts** (Discord, group chats, sessions with other people)
- This is for **security** — contains personal context that shouldn't leak to strangers
- You can **read, edit, and update** MEMORY.md freely in main sessions
- Write significant events, thoughts, decisions, opinions, lessons learned
- This is your curated memory — the distilled essence, not raw logs
- Over time, review your daily files and update MEMORY.md with what's worth keeping

### 📝 Write It Down - No "Mental Notes"!

- **Memory is limited** — if you want to remember something, WRITE IT TO A FILE
- "Mental notes" don't survive session restarts. Files do.
- When someone says "remember this" → update `memory/YYYY-MM-DD.md` or relevant file
- When you learn a lesson → update `AGENTS.md`, `docs/internal/agent-context/TOOLS.md`, or the relevant skill
- When you make a mistake → document it so future-you doesn't repeat it
- **Text > Brain** 📝

## Safety

- Don't exfiltrate private data. Ever.
- Don't run destructive commands without asking.
- `trash` > `rm` (recoverable beats gone forever)
- When in doubt, ask.

## External vs Internal

**Safe to do freely:**

- Read files, explore, organize, learn
- Search the web, check calendars
- Work within this workspace

**Ask first:**

- Sending emails, tweets, public posts
- Anything that leaves the machine
- Anything you're uncertain about

## Group Chats

You have access to your human's stuff. That doesn't mean you _share_ their stuff. In groups, you're a participant — not their voice, not their proxy. Think before you speak.

### 💬 Know When to Speak!

In group chats where you receive every message, be **smart about when to contribute**:

**Respond when:**

- Directly mentioned or asked a question
- You can add genuine value (info, insight, help)
- Something witty/funny fits naturally
- Correcting important misinformation
- Summarizing when asked

**Stay silent (HEARTBEAT_OK) when:**

- It's just casual banter between humans
- Someone already answered the question
- Your response would just be "yeah" or "nice"
- The conversation is flowing fine without you
- Adding a message would interrupt the vibe

**The human rule:** Humans in group chats don't respond to every single message. Neither should you. Quality > quantity. If you wouldn't send it in a real group chat with friends, don't send it.

**Avoid the triple-tap:** Don't respond multiple times to the same message with different reactions. One thoughtful response beats three fragments.

Participate, don't dominate.

### 😊 React Like a Human!

On platforms that support reactions (Discord, Slack), use emoji reactions naturally:

**React when:**

- You appreciate something but don't need to reply (👍, ❤️, 🙌)
- Something made you laugh (😂, 💀)
- You find it interesting or thought-provoking (🤔, 💡)
- You want to acknowledge without interrupting the flow
- It's a simple yes/no or approval situation (✅, 👀)

**Why it matters:**
Reactions are lightweight social signals. Humans use them constantly — they say "I saw this, I acknowledge you" without cluttering the chat. You should too.

**Don't overdo it:** One reaction per message max. Pick the one that fits best.

## Tools

Skills provide your tools. When you need one, check its `SKILL.md`. Keep local notes (camera names, SSH details, voice preferences) in `docs/internal/agent-context/TOOLS.md`.

**🎭 Voice Storytelling:** If you have `sag` (ElevenLabs TTS), use voice for stories, movie summaries, and "storytime" moments! Way more engaging than walls of text. Surprise people with funny voices.

**📝 Platform Formatting:**

- **Discord/WhatsApp:** No markdown tables! Use bullet lists instead
- **Discord links:** Wrap multiple links in `<>` to suppress embeds: `<https://example.com>`
- **WhatsApp:** No headers — use **bold** or CAPS for emphasis

## 💓 Heartbeats - Be Proactive!

When you receive a heartbeat poll (message matches the configured heartbeat prompt), don't just reply `HEARTBEAT_OK` every time. Use heartbeats productively!

Default heartbeat prompt:
`Read docs/internal/agent-context/HEARTBEAT.md if it exists (workspace context). Follow it strictly. Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply HEARTBEAT_OK.`

You are free to edit `docs/internal/agent-context/HEARTBEAT.md` with a short checklist or reminders. Keep it small to limit token burn.

### Heartbeat vs Cron: When to Use Each

**Use heartbeat when:**

- Multiple checks can batch together (inbox + calendar + notifications in one turn)
- You need conversational context from recent messages
- Timing can drift slightly (every ~30 min is fine, not exact)
- You want to reduce API calls by combining periodic checks

**Use cron when:**

- Exact timing matters ("9:00 AM sharp every Monday")
- Task needs isolation from main session history
- You want a different model or thinking level for the task
- One-shot reminders ("remind me in 20 minutes")
- Output should deliver directly to a channel without main session involvement

**Tip:** Batch similar periodic checks into `docs/internal/agent-context/HEARTBEAT.md` instead of creating multiple cron jobs. Use cron for precise schedules and standalone tasks.

**Things to check (rotate through these, 2-4 times per day):**

- **Emails** - Any urgent unread messages?
- **Calendar** - Upcoming events in next 24-48h?
- **Mentions** - Twitter/social notifications?
- **Weather** - Relevant if your human might go out?

**Track your checks** in `memory/heartbeat-state.json`:

```json
{
  "lastChecks": {
    "email": 1703275200,
    "calendar": 1703260800,
    "weather": null
  }
}
```

**When to reach out:**

- Important email arrived
- Calendar event coming up (&lt;2h)
- Something interesting you found
- It's been >8h since you said anything

**When to stay quiet (HEARTBEAT_OK):**

- Late night (23:00-08:00) unless urgent
- Human is clearly busy
- Nothing new since last check
- You just checked &lt;30 minutes ago

**Proactive work you can do without asking:**

- Read and organize memory files
- Check on projects (git status, etc.)
- Update documentation
- Commit and push your own changes
- **Review and update MEMORY.md** (see below)

### 🔄 Memory Maintenance (During Heartbeats)

Periodically (every few days), use a heartbeat to:

1. Read through recent `memory/YYYY-MM-DD.md` files
2. Identify significant events, lessons, or insights worth keeping long-term
3. Update `MEMORY.md` with distilled learnings
4. Remove outdated info from MEMORY.md that's no longer relevant

Think of it like a human reviewing their journal and updating their mental model. Daily files are raw notes; MEMORY.md is curated wisdom.

The goal: Be helpful without being annoying. Check in a few times a day, do useful background work, but respect quiet time.

## Project Tracking — GitLab Issues

Task tracking uses **GitLab Issues** as the single source of truth.

### Architecture

- **GitLab CE** (primary): Self-hosted at `/gitlab/` (Traefik). Issues, milestones, labels, boards. Use for all task management — training, infrastructure, platform improvements, agent coordination.
- **GitHub** (public mirror): `axelofwar/shml-platform`. Read-only public mirror. GitHub CI runs on push for external visibility.

### Programmatic Access

All scripts use `scripts/platform/gitlab_utils.py` for GitLab API operations:

```bash
# CLI usage:
python3 scripts/platform/gitlab_utils.py create-issue "Title" --labels "type::bug"
python3 scripts/platform/gitlab_utils.py upsert-issue "Search Title" --comment "Update"
python3 scripts/platform/gitlab_utils.py list-issues --state opened
python3 scripts/platform/gitlab_utils.py setup-board  # Create labels + milestones

# Python import:
from scripts.platform.gitlab_utils import create_issue, upsert_issue, list_issues
```

**Environment:** `GITLAB_API_TOKEN` or `GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN` in `.env`.
**Internal URL:** `http://shml-gitlab:8929/gitlab/api/v4/` (Docker network, no OAuth2-proxy).
**Project ID:** 2

### Labels (scoped)

| Scope | Labels |
|-------|--------|
| **type::** | `bug`, `feature`, `chore`, `training`, `security` |
| **priority::** | `critical`, `high`, `medium`, `low` |
| **status::** | `blocked`, `stale` |
| **component::** | `watchdog`, `ci-cd`, `autoresearch`, `agent-service`, `chat-ui`, `fusionauth`, `infra` |
| **source::** | `watchdog`, `scan`, `autoresearch`, `ci`, `pipeline` |

### Automated Issue Creation

| System | When | What |
|--------|------|------|
| **Watchdog** | OOM kill, memory leak, restart failure, throttle | Creates `source::watchdog` issue (idempotent) |
| **scan_repo_state** | Agent down, GPU low memory, autoresearch progress | Creates/updates `source::scan` issue |
| **T8 pipeline** | Stage start, stage completion, pipeline failure | Creates/updates `source::pipeline` issue |
| **CI Pipeline** | Test failures, security scan findings | Creates `source::ci` issue |
| **Autoresearch** | Training milestone, completion, failure | Creates `source::autoresearch` issue |

### Rules

1. **Before starting any task** — create/find a GitLab Issue. Assign yourself and move to "Doing".
2. **When a task is done** — close the GitLab Issue.
3. **When blocked** — add the `status::blocked` label in GitLab.
4. **Adding new tasks** — create a GitLab Issue first.
5. **Agent-created issues** — always include a `source::*` label.

### Auto-Sync

- Every 10min: `shl-gitlab-sync.timer` → `update_gitlab_board.sh` → syncs T8 state files into GitLab Issues
- Every 30min: `shl-platform-scan.timer` → `scan_repo_state.sh` → detects task completion + syncs to GitLab Issues
- Nightly 02:00: `shl-nano-pipeline.timer` → full T8 training pipeline

### Skills

The agent service has a `gitlab-integration` skill at `inference/agent-service/skills/gitlab-integration/SKILL.md`.
Use it for conversational issue management: "create a bug for the GPU thermal issue", "show me open watchdog alerts", etc.

### To update the board manually (agent action)

```bash
bash scripts/platform/scan_repo_state.sh   # re-scan + sync GitLab Issues
bash scripts/data/update_gitlab_board.sh   # sync T8 pipeline state to GitLab Issues
python3 scripts/platform/gitlab_utils.py list-issues  # see all open issues
```

## Make It Yours

This is a starting point. Add your own conventions, style, and rules as you figure out what works.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **shml-platform** (14868 symbols, 40672 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/shml-platform/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/shml-platform/context` | Codebase overview, check index freshness |
| `gitnexus://repo/shml-platform/clusters` | All functional areas |
| `gitnexus://repo/shml-platform/processes` | All execution flows |
| `gitnexus://repo/shml-platform/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |
| Work in the Libs area (1146 symbols) | `.claude/skills/generated/libs/SKILL.md` |
| Work in the Inference area (926 symbols) | `.claude/skills/generated/inference/SKILL.md` |
| Work in the App area (763 symbols) | `.claude/skills/generated/app/SKILL.md` |
| Work in the Ray_compute area (599 symbols) | `.claude/skills/generated/ray-compute/SKILL.md` |
| Work in the Api area (169 symbols) | `.claude/skills/generated/api/SKILL.md` |
| Work in the Tests area (156 symbols) | `.claude/skills/generated/tests/SKILL.md` |
| Work in the Scripts area (149 symbols) | `.claude/skills/generated/scripts/SKILL.md` |
| Work in the Shml area (126 symbols) | `.claude/skills/generated/shml/SKILL.md` |
| Work in the Integrations area (119 symbols) | `.claude/skills/generated/integrations/SKILL.md` |
| Work in the Admin area (119 symbols) | `.claude/skills/generated/admin/SKILL.md` |
| Work in the Integration area (97 symbols) | `.claude/skills/generated/integration/SKILL.md` |
| Work in the Jobs area (96 symbols) | `.claude/skills/generated/jobs/SKILL.md` |
| Work in the Face area (77 symbols) | `.claude/skills/generated/face/SKILL.md` |
| Work in the Unit area (68 symbols) | `.claude/skills/generated/unit/SKILL.md` |
| Work in the Chat-api area (60 symbols) | `.claude/skills/generated/chat-api/SKILL.md` |
| Work in the Platform area (55 symbols) | `.claude/skills/generated/platform/SKILL.md` |
| Work in the Memory area (49 symbols) | `.claude/skills/generated/memory/SKILL.md` |
| Work in the Services area (48 symbols) | `.claude/skills/generated/services/SKILL.md` |
| Work in the Yfcc100m area (45 symbols) | `.claude/skills/generated/yfcc100m/SKILL.md` |
| Work in the Sdk area (43 symbols) | `.claude/skills/generated/sdk/SKILL.md` |

<!-- gitnexus:end -->
