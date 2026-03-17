# Contributing to ML Platform

Thank you for your interest in contributing to the ML Platform! This document provides guidelines and best practices for contributing.

**For AI Assistants:** See `.github/copilot-instructions.md` for comprehensive documentation policy and enforcement rules.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Documentation Guidelines](#documentation-guidelines)
- [Code Style](#code-style)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

---

## Code of Conduct

This project adheres to the Contributor Covenant Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

---

## Getting Started

### Prerequisites

- Docker & Docker Compose (v3.8+)
- Git
- Basic understanding of MLflow and Ray
- (Optional) Tailscale for VPN access

### Initial Setup

```bash
# Clone the repository
git clone <repository-url>
cd ml-platform

# Review documentation
cat README.md
cat ARCHITECTURE.md

# Start the platform
./start_all_safe.sh

# Verify all services are healthy
docker ps
```

---

## Development Workflow

### Before Making Changes

1. **Check existing documentation** - Always review current docs before creating new ones
2. **Read copilot instructions** - See `.github/copilot-instructions.md` for context
3. **Understand the architecture** - Review `ARCHITECTURE.md`
4. **Test locally first** - Use `start_all_safe.sh` for clean startup

### Making Changes

#### Infrastructure Changes (Docker Compose)

```bash
# 1. Stop all services
./stop_all.sh

# 2. Make changes to deploy/compose/docker-compose.yml
# IMPORTANT: Add inline comments explaining critical values
# Example:
# - traefik.http.routers.my-api.priority=2147483647  # CRITICAL: See LESSONS_LEARNED.md

# 3. Validate syntax
docker-compose config

# 4. Start with safe script
./start_all_safe.sh

# 5. Verify health
docker ps
curl http://localhost/api/v1/health
```

#### Code Changes (APIs, Scripts)

```bash
# 1. Create feature branch
git checkout -b feature/your-feature-name

# 2. Make changes with proper error handling
# Follow existing patterns in codebase

# 3. Test thoroughly
python -m pytest tests/  # If tests exist
./scripts/test_integration.sh

# 4. Update relevant documentation
# See Documentation Guidelines below
```

#### Configuration Changes

```bash
# 1. NEVER commit secrets or credentials
# Use .env.example as template, actual .env is gitignored

# 2. Document all new configuration options
# Add to README.md Configuration section

# 3. Test with fresh deployment
./stop_all.sh && ./start_all_safe.sh
```

---

## Documentation Guidelines

### 📌 CRITICAL RULE: Documentation Consolidation

**ALWAYS update existing docs instead of creating new files.**

We maintain **<20 total documentation files**. Before creating new documentation:

1. **Check if content fits in existing docs:**
   - Setup/Installation → `README.md`
   - System design → `ARCHITECTURE.md`
   - API usage → `API_REFERENCE.md`
   - Service integration → `INTEGRATION_GUIDE.md`
   - Issues/Fixes → `TROUBLESHOOTING.md`
   - Best practices → `LESSONS_LEARNED.md`
   - Remote access → `REMOTE_QUICK_REFERENCE.md`

2. **If creating new file is absolutely necessary:**
   - Provide justification in PR description
   - Explain why existing docs can't accommodate content
   - Get approval before merging

3. **Update CHANGELOG.md** with all documentation changes

### Documentation Structure

```
ml-platform/
├── README.md                      # Main overview, quick start
├── ARCHITECTURE.md                # System design, decisions
├── API_REFERENCE.md               # All API documentation
├── INTEGRATION_GUIDE.md           # Service integration patterns
├── TROUBLESHOOTING.md             # Common issues & solutions
├── LESSONS_LEARNED.md             # Best practices & patterns
├── REMOTE_QUICK_REFERENCE.md      # Remote access (public)
├── CHANGELOG.md                   # Version history
├── CONTRIBUTING.md                # This file
├── LICENSE                        # MIT License
├── NEW_GPU_SETUP.md               # GPU setup (exportable)
├── mlflow-server/
│   ├── README.md                  # MLflow-specific docs
│   └── .github/copilot-instructions.md
└── ray_compute/
    ├── README.md                  # Ray-specific docs
    └── .github/copilot-instructions.md
```

### Writing Style

- **Use clear headings** with emoji indicators (📊, 🚀, ⚠️, ✅, ❌)
- **Include code examples** that are copy-paste ready
- **Add inline comments** in critical configuration
- **Reference related docs** with relative links
- **Keep it concise** - if doc exceeds 1000 lines, consider splitting

### Example: Good Documentation Update

```markdown
## ✅ GOOD - Updating existing doc

PR Description:
"Adding GPU job submission section to INTEGRATION_GUIDE.md because it
demonstrates MLflow+Ray integration pattern with GPU resources."

Changes:
- INTEGRATION_GUIDE.md: Added "GPU Job Submission" section (lines 450-520)
- Includes working example with cupy
- References LESSONS_LEARNED.md for resource allocation patterns
```

### Example: Bad Documentation

```markdown
## ❌ BAD - Creating duplicate doc

PR Description:
"Adding GPU_SETUP_GUIDE.md with setup instructions"

Issues:
- Creates 21st documentation file (exceeds limit)
- Content belongs in ARCHITECTURE.md (Infrastructure section)
- Duplicates existing GPU info in NEW_GPU_SETUP.md
```

---

## Code Style

### Python

```python
# Follow PEP 8
# Use type hints
# Add docstrings

def process_experiment(experiment_id: str, params: dict) -> dict:
    """
    Process MLflow experiment with given parameters.

    Args:
        experiment_id: MLflow experiment ID
        params: Configuration parameters

    Returns:
        Dictionary with processing results

    Raises:
        ValueError: If experiment_id is invalid
    """
    pass
```

### Bash Scripts

```bash
#!/bin/bash
# Script name and purpose at top
# Use set -e for error handling
# Add comments for complex logic

set -e  # Exit on error

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "Error: Docker not installed"
    exit 1
fi

# Your script logic here
```

### Docker Compose

```yaml
services:
  my-service:
    image: my-image:latest
    # CRITICAL: Add comments for non-obvious configuration
    # Priority 2147483647 overrides Traefik internal API (see LESSONS_LEARNED.md)
    labels:
      - traefik.http.routers.my-api.priority=2147483647
```

---

## Testing

### Infrastructure Testing

```bash
# Test platform startup
./start_all_safe.sh

# Verify all services healthy
docker ps | grep -E "Up.*healthy"

# Test critical routes
curl http://localhost/api/v1/health
curl http://localhost/mlflow/
curl http://localhost/ray/

# Check logs for errors
docker-compose logs | grep -i error
```

### Integration Testing

```bash
# Run integration tests (if available)
./test_integration.sh

# Test MLflow connectivity
python tests/test_mlflow_connection.py

# Test Ray job submission
python tests/test_ray_jobs.py
```

### Manual Testing Checklist

Before submitting PR:

- [ ] Platform starts cleanly with `./start_all_safe.sh`
- [ ] All 16+ services reach healthy status
- [ ] MLflow UI accessible at `/mlflow/`
- [ ] Ray Dashboard accessible at `/ray/`
- [ ] Custom API responds at `/api/v1/health`
- [ ] No errors in `docker-compose logs`
- [ ] Documentation updated
- [ ] CHANGELOG.md updated

---

## Submitting Changes

### Pull Request Process

1. **Update documentation** - See Documentation Guidelines above
2. **Update CHANGELOG.md** - Add entry under "Unreleased" section
3. **Test thoroughly** - Complete manual testing checklist
4. **Create PR** with descriptive title and detailed description

### PR Title Format

```
[Category] Brief description

Categories:
- [Feature] - New functionality
- [Fix] - Bug fix
- [Docs] - Documentation only
- [Refactor] - Code restructuring
- [Perf] - Performance improvement
- [Infra] - Infrastructure/Docker changes
```

### PR Description Template

```markdown
## Description
Brief summary of changes

## Motivation
Why is this change needed?

## Changes Made
- Changed X in Y
- Updated Z documentation
- Added tests for W

## Testing
- [ ] Tested locally with `./start_all_safe.sh`
- [ ] All services healthy
- [ ] Manual testing complete
- [ ] Documentation updated
- [ ] CHANGELOG.md updated

## Documentation
- Updated: INTEGRATION_GUIDE.md (Added GPU examples)
- No new files created (follows <20 file limit)

## Screenshots (if applicable)
```

### Review Process

1. Maintainer reviews changes
2. Automated checks run (if CI configured)
3. Address feedback
4. Get approval
5. Merge to main

---

## Project-Specific Best Practices

### Traefik Routing

**CRITICAL:** Always use maximum priority for custom API routes:

```yaml
- traefik.http.routers.my-api.priority=2147483647
```

See `LESSONS_LEARNED.md` for detailed explanation.

### Ray Resource Allocation

**CRITICAL:** Container memory must exceed allocated resources:

```yaml
command: --object-store-memory=1000000000  # 1GB
deploy:
  resources:
    limits:
      memory: 4G  # Must be >> object store + overhead
```

See `LESSONS_LEARNED.md` for calculation patterns.

### Health Checks

**CRITICAL:** Keep health endpoints lightweight:

```python
# ✅ GOOD - Fast response
@app.get("/health")
def health():
    return {"status": "healthy"}

# ❌ BAD - Expensive query
@app.get("/health")
def health():
    experiments = mlflow.search_experiments()  # 97 seconds!
    return {"status": "healthy"}
```

### Service Startup

**CRITICAL:** Use phased startup script:

```bash
# ✅ Always use safe startup
./start_all_safe.sh

# ❌ Never use raw docker-compose up
docker-compose up -d  # Causes dependency failures
```

---

## Getting Help

- **Documentation:** Start with README.md
- **Architecture:** See ARCHITECTURE.md
- **Issues:** Check TROUBLESHOOTING.md
- **Best Practices:** See LESSONS_LEARNED.md
- **Copilot Context:** Read `.github/copilot-instructions.md`

---

## Recognition

Contributors will be recognized in:
- CHANGELOG.md for their contributions
- Project README.md (Contributors section)

Thank you for contributing to the ML Platform! 🚀
