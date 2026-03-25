#!/usr/bin/env bash
# generate-ide-configs.sh — Assemble IDE configuration files from shared .agent/rules/ sources
#
# Usage:
#   scripts/generate-ide-configs.sh [--target copilot|claude|cline|all] [--dry-run]
#
# Outputs:
#   .github/copilot-instructions.md   — Copilot workspace instructions
#   .claude/CLAUDE.md                 — Claude Code project context
#   .clinerules                       — Cline IDE rules
#
# Sources:
#   .agent/rules/*.md                 — 6 canonical rule files
#
# NEVER edit generated files directly. Edit sources in .agent/rules/ then re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULES_DIR="${REPO_ROOT}/.agent/rules"
DRY_RUN=false
TARGET="all"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2;;
        --dry-run) DRY_RUN=true; shift;;
        *) echo "Unknown arg: $1"; exit 1;;
    esac
done

# Write helper (respects --dry-run)
write_file() {
    local path="$1"
    local content="$2"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY-RUN] Would write: $path ($(echo "$content" | wc -l) lines)"
    else
        echo "$content" > "$path"
        echo "✓ Generated: $path"
    fi
}

# Read all rule files in defined order
read_rules() {
    cat \
        "${RULES_DIR}/service-management.md" \
        "${RULES_DIR}/documentation-policy.md" \
        "${RULES_DIR}/security.md" \
        "${RULES_DIR}/platform-context.md" \
        "${RULES_DIR}/api-conventions.md" \
        "${RULES_DIR}/code-style.md"
}

# Extract a frontmatter value from a rule file: get_fm_value <file> <key>
get_fm_value() {
    local file="$1" key="$2"
    awk -v key="$key" '
        /^---/{f++; next}
        f==1 && $0 ~ "^"key":"{
            gsub(/^[^:]+: *"?/,""); gsub(/"$/,""); print; exit
        }
    ' "$file"
}

# Strip YAML frontmatter from a rule file (returns body only)
strip_frontmatter() {
    awk '/^---/{if(++f==2){found=1;next}} found{print}' "$1"
}

# Generate scoped .github/instructions/*.instructions.md from each rule file
generate_instructions() {
    local instructions_dir="${REPO_ROOT}/.github/instructions"
    mkdir -p "$instructions_dir"

    declare -A DESCRIPTIONS=(
        [service-management]="Use when restarting, starting, or stopping services; writing docker-compose files; modifying Taskfile.yml; managing the platform lifecycle. Covers mandatory start_all_safe.sh usage, task runner commands, and deploy library patterns."
        [documentation-policy]="Use when creating, editing, or reviewing markdown documentation files. Covers 20-file doc limit, which file gets which content, and CHANGELOG.md update requirements."
        [security]="Use when writing code that handles credentials, secrets, environment variables, authentication, or external inputs. Covers OWASP Top 10, ggshield pre-commit hooks, and Docker secrets patterns."
        [platform-context]="Use when asking about platform topology, service endpoints, GPU allocation, or network architecture. Reference for the 23-container ML platform with MLflow, Ray, inference, and monitoring stacks."
        [api-conventions]="Use when writing FastAPI handlers, docker-compose service definitions, Traefik routing labels, or OpenAI-compatible inference APIs. Covers Traefik priority 2147483647, Ray memory formula, and OAuth2-Proxy header trust."
        [code-style]="Use when writing Python, TypeScript, or bash code. Covers async/await patterns, type annotations, logging, error handling, import ordering, naming conventions, and complexity budget."
    )

    for rule_file in "${RULES_DIR}"/*.md; do
        local rule_name
        rule_name="$(basename "$rule_file" .md)"
        local applies_to
        applies_to="$(get_fm_value "$rule_file" "applies-to")"
        local description="${DESCRIPTIONS[$rule_name]:-}"
        local body
        body="$(strip_frontmatter "$rule_file")"
        local out="${instructions_dir}/${rule_name}.instructions.md"

        local content
        content=$(cat <<EOF
---
description: "${description}"
applyTo: "${applies_to}"
---
${body}
EOF
)
        write_file "$out" "$content"
    done
}

# Version from VERSION file
VERSION=$(cat "${REPO_ROOT}/VERSION" 2>/dev/null || echo "0.1.0")

generate_copilot() {
    local output

    output=$(cat <<COPILOT_HEADER
\`\`\`\`instructions
# GitHub Copilot Instructions — SHML Platform

<!-- GENERATED FILE — edit sources in .agent/rules/, run scripts/generate-ide-configs.sh to update -->
**Version:** ${VERSION} | **License:** MIT | **Generated:** $(date +%Y-%m-%d)

---

COPILOT_HEADER
)

    output+="$(read_rules)"

    output+=$(cat <<COPILOT_FOOTER


---

## 🤖 Agent Skills

Workspace skills are in \`.github/skills/\`. Each skill has a \`SKILL.md\` with \`name\`, \`description\`, and activation keywords.

Available skills: $(ls "${REPO_ROOT}/.github/skills/" 2>/dev/null | tr '\n' ' ')

Copilot loads skill descriptions automatically (~100 tokens each). Full skill body is loaded when the skill matches the current task (progressive disclosure).

## 🧑‍💼 Subagents

Workspace subagents are in \`.github/agents/\`. Use \`#<agentname>\` to invoke them.

## 📋 Prompts

Custom slash prompts are in \`.github/prompts/\`. Use them for common workflows.

\`\`\`\`
COPILOT_FOOTER
)

    write_file "${REPO_ROOT}/.github/copilot-instructions.md" "$output"
}

generate_claude() {
    local output

    output=$(cat <<CLAUDE_HEADER
# CLAUDE.md — SHML Platform Project Context

<!-- GENERATED FILE — edit sources in .agent/rules/, run scripts/generate-ide-configs.sh to update -->
**Version:** ${VERSION} | **Generated:** $(date +%Y-%m-%d)

This file is automatically loaded by Claude Code at session start.

---

## Quick Command Reference

\`\`\`bash
# Platform management
task status              # Check all services
task restart:ray         # Restart Ray stack
task restart:mlflow      # Restart MLflow stack
task restart:inference   # Restart inference stack
task gpu                 # GPU VRAM status

# Generate IDE configs (after editing .agent/rules/)
scripts/generate-ide-configs.sh --target all
\`\`\`

## Agent Context

- **Rules:** \`.agent/rules/\` — 6 focused rule files (service-management, documentation, security, platform, api, code)
- **Skills:** \`.claude/skills/\` — 13 skills with SKILL.md (same canonical files as agent-service)
- **Commands:** \`.claude/commands/\` — slash commands (/project:review, /project:audit, etc.)
- **Agents:** \`.claude/agents/\` — specialized subagents (code-reviewer, security-auditor, training-monitor)

---

CLAUDE_HEADER
)

    # Append condensed rules (strip YAML frontmatter from each rule file)
    for rule_file in \
        "${RULES_DIR}/service-management.md" \
        "${RULES_DIR}/security.md" \
        "${RULES_DIR}/api-conventions.md" \
        "${RULES_DIR}/platform-context.md" \
        "${RULES_DIR}/code-style.md"; do
        output+="$(awk '/^---/{if(++f==2){found=1;next}} found{print}' "$rule_file")"
        output+=$'\n\n---\n\n'
    done

    write_file "${REPO_ROOT}/.claude/CLAUDE.md" "$output"
}

generate_cline() {
    local output

    output=$(cat <<CLINE_HEADER
# .clinerules — SHML Platform

<!-- GENERATED FILE — edit sources in .agent/rules/, run scripts/generate-ide-configs.sh to update -->

## Platform

This is a unified ML platform (MLflow + Ray + Traefik + Inference). See \`.agent/rules/\` for complete rules.

## Critical Rules

1. **ALWAYS use \`./start_all_safe.sh\` or \`task\` for service management** (never raw docker-compose restart)
2. **Never create new documentation files** — add to existing docs, max 20 files total
3. **Never hardcode secrets** — use environment variables or Docker secrets
4. **Traefik routers need priority 2147483647** to override internal API
5. **GPU allocation**: cuda:0=RTX 3090 (training/image), cuda:1=RTX 2070 (Qwen3-VL, always loaded)

## Full Rule Sources

- Service management: \`.agent/rules/service-management.md\`
- Documentation policy: \`.agent/rules/documentation-policy.md\`
- Security: \`.agent/rules/security.md\`
- Platform context: \`.agent/rules/platform-context.md\`
- API conventions: \`.agent/rules/api-conventions.md\`
- Code style: \`.agent/rules/code-style.md\`
CLINE_HEADER
)

    write_file "${REPO_ROOT}/.clinerules" "$output"
}

# Execute targets
case "$TARGET" in
    copilot)
        generate_copilot
        generate_instructions
        ;;
    claude)  generate_claude;;
    cline)   generate_cline;;
    all)
        generate_copilot
        generate_claude
        generate_cline
        generate_instructions
        ;;
    *)
        echo "Error: unknown target '$TARGET'. Use: copilot|claude|cline|all"
        exit 1
        ;;
esac

echo ""
echo "Done. Run with --dry-run to preview without writing."
