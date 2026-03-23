---
description: "Use when creating, editing, or reviewing markdown documentation files. Covers 20-file doc limit, which file gets which content, and CHANGELOG.md update requirements."
applyTo: "**/*.md"
---

# ⚠️ DOCUMENTATION POLICY — ENFORCE ALWAYS

## Documentation Structure

**THIS PROJECT MAINTAINS <20 TOTAL DOCUMENTATION FILES.**

**ANY ATTEMPT TO CREATE NEW DOCUMENTATION FILES MUST BE REJECTED.**

## File Mapping — Which File Gets Which Content

| Content Type | File |
|---|---|
| Setup/Status/Quick Start | `README.md` |
| Architecture/Design decisions | `ARCHITECTURE.md` |
| API documentation | `API_REFERENCE.md` |
| Integration/Usage/Best practices | `INTEGRATION_GUIDE.md` |
| Problems/Errors/Debugging | `TROUBLESHOOTING.md` |
| Patterns/Gotchas/Optimizations | `LESSONS_LEARNED.md` |
| Remote access | `REMOTE_QUICK_REFERENCE.md` |
| GPU setup | `NEW_GPU_SETUP.md` |
| MLflow operations | `mlflow-server/README.md` |
| Ray operations | `ray_compute/README.md` |

## Enforcement Rules

### Rule 1: NEVER Create New Documentation Files

**If user requests documentation, you MUST:**

1. Identify which existing file should contain the content (use table above)
2. Respond with: "I'll add [topic] to [existing-file.md] in the [section] section instead of creating a new file."
3. Update the existing file (add new section, proper Markdown hierarchy, code blocks, cross-references)
4. Update `CHANGELOG.md`

### Rule 2: Example Rejections

```
User: "Create a DEPLOYMENT_GUIDE.md"
✅ Good: "I'll add deployment information to README.md under 'Deployment' section."

User: "Document the backup process in a new file"
✅ Good: "I'll add backup documentation to ARCHITECTURE.md under 'Data Persistence' section."

User: "Create an OAuth troubleshooting guide"
✅ Good: "I'll add OAuth troubleshooting to TROUBLESHOOTING.md under 'Authentication' section."
```

### Rule 3: If New File Is Truly Necessary

1. Explain why ALL existing docs cannot accommodate the content
2. Show proof that consolidation is impossible
3. Demonstrate it won't exceed 20-file limit
4. Get EXPLICIT user approval with exact filename
5. Archive an existing file to stay under 20 files if at limit

This should happen <1% of the time.

### Rule 4: Always Update CHANGELOG.md

For ANY documentation change:
- Add entry to CHANGELOG.md under [Unreleased] section
- Document what was added/changed
- Note which file was modified

## File Count Validation

```bash
find . -name "*.md" -not -path "*/archived/*" -not -path "*/.git/*" | wc -l
# MUST be ≤20
```

## Documentation Quality Standards

Every documentation update must:
1. Use clear, concise language
2. Include code examples where applicable
3. Use proper Markdown formatting (H2/H3 hierarchy)
4. Cross-reference related sections
5. Include verification steps
6. Document "why" not just "what"

## Development Workflow

### Before Making Changes
1. Check if feature/issue already documented
2. Identify which file(s) to update
3. Verify current doc count: `find . -name "*.md" -not -path "*/archived/*" | wc -l`

### After Making Changes
1. Verify count still ≤20
2. Check for secrets: `git diff | grep -E "password|secret|token|key"`
3. Update CHANGELOG.md
4. Commit with clear message: `git commit -m "docs: Add X to Y.md"`
