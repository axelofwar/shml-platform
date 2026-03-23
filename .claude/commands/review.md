---
description: "Review the current branch changes for code quality, correctness, and security issues"
---

# Code Review

Review the current branch changes against main.

```bash
git diff main...HEAD
```

Please provide a thorough code review covering:

1. **Correctness** — Does the code do what it's intended to do? Are there logic errors or edge cases?
2. **Security** — Check against OWASP Top 10: hardcoded secrets, injection risks, improper auth, path traversal
3. **ML/Ray patterns** — If modifying Ray jobs or training code, verify memory formulas and GPU allocation
4. **Docker/Traefik** — If modifying compose files, check router priority (must be 2147483647) and healthchecks
5. **Tests** — Are there tests for the new behavior? Any edge cases untested?
6. **Style** — Follows `.agent/rules/code-style.md` conventions (types, async, logging)?

Format your response as:
- **Summary**: 2-3 sentence overview
- **Issues** (if any): Severity (critical/warning/info) + file:line + explanation + suggested fix
- **Verdict**: APPROVE / REQUEST_CHANGES / NEEDS_DISCUSSION
