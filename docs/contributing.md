# Contributing

Guidelines for contributing to the SHML Platform.

---

## Prerequisites

- Docker & Docker Compose (v3.8+)
- Git
- Python 3.10+
- Basic understanding of MLflow and Ray

---

## Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd shml-platform

# Install pre-commit hooks (required)
pip install pre-commit ggshield
pre-commit install
pre-commit install --hook-type pre-push
ggshield auth login

# Start the platform
./start_all_safe.sh

# Verify all services are healthy
./start_all_safe.sh status
```

---

## Pre-Commit Hooks

Every commit is scanned for:

- **Secrets** — ggshield blocks commits containing passwords, API keys, or tokens
- **Formatting** — Standard Python and YAML formatting checks

```bash
# Run all hooks manually
pre-commit run --all-files

# Skip hooks (emergency only)
git commit --no-verify -m "emergency fix"
```

---

## Making Changes

### Infrastructure Changes

```bash
# 1. Stop services
./stop_all.sh

# 2. Edit compose files — add inline comments for critical values
# 3. Validate
docker compose -f docker-compose.infra.yml config

# 4. Restart and verify
./start_all_safe.sh
docker ps
```

### Code Changes

```bash
# 1. Create a feature branch
git checkout -b feature/your-feature

# 2. Make changes following existing patterns
# 3. Run tests
python -m pytest tests/

# 4. Update documentation (see below)
# 5. Commit and push
git add -A && git commit -m "feat: description of change"
git push origin feature/your-feature
```

### Configuration Changes

- **Never** commit secrets or credentials
- Document all new configuration options in the appropriate docs page
- Test with a fresh deployment: `./stop_all.sh && ./start_all_safe.sh`

---

## Code Style

- **Python**: Follow existing patterns in the codebase. Use type hints, dataclasses, and `pathlib`.
- **Docker Compose**: Add inline comments explaining critical values and resource limits.
- **Bash scripts**: Use `set -e`, quote variables, add color-coded logging.
- **Documentation**: Use MkDocs Material admonitions and Mermaid diagrams where appropriate.

---

## Documentation Rules

!!! warning "Update Existing Docs"
    Always update existing documentation files instead of creating new ones. The platform maintains a structured docs hierarchy under `docs/`.

Before creating a new documentation file:

1. Check if the content fits in an existing page
2. If a new page is truly needed, add it to `mkdocs.yml` navigation
3. Update the changelog

---

## PR Process

1. Create a feature branch from `main`
2. Make changes with clear, atomic commits
3. Ensure pre-commit hooks pass
4. Test with `./start_all_safe.sh` on a clean environment
5. Submit PR with a description of:
    - What changed and why
    - How to test
    - Any migration steps required
6. Address review feedback
7. Squash-merge when approved

---

## Reporting Issues

When reporting a bug, include:

- Output of `./start_all_safe.sh status`
- Relevant container logs (`docker logs <container> --tail 50`)
- Steps to reproduce
- Expected vs actual behavior
