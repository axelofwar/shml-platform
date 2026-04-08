## 🤖 Agent-Generated MR

**Agent:** Hermes | **Task type:** %{task_type}

## Summary

%{summary}

## Related Issue

Closes #%{issue_iid}

## Changes

%{changes}

## Agent Analysis

%{analysis}

## Actions Taken

%{actions}

## Vault Reference

- Decision log: [[20-Decisions/%{vault_note}]]
- Related: [[50-Projects/INDEX|Projects]]

## Testing

- [ ] CI pipeline passes
- [ ] GitNexus impact analysis: %{gitnexus_status}
- [ ] Gitleaks scan: %{gitleaks_status}
- [ ] Danger review: %{danger_status}

## Checklist

- [x] Code follows project style (agent-enforced)
- [x] No hardcoded secrets (gitleaks verified)
- [ ] Human review of code logic
- [ ] Human review of test coverage

---
*This MR was created by the Hermes autonomous agent. Please review carefully before merging.*
