# SHML Client SDK

Simple Python client for the SHML Platform Ray Compute API.

## Installation

```bash
# From git (recommended)
pip install git+https://github.com/axelofwar/shml-platform.git#subdirectory=libs/client

# Or editable install for development
git clone https://github.com/axelofwar/shml-platform.git
cd shml-platform/libs/client
pip install -e .
```

## Quick Start

### Simple Job Submission (<150 chars!)

```python
from shml import ray_submit
ray_submit("print('hello')", key="shml_xxx")  # 45 chars!
```

### With Environment Variable

```bash
export SHML_API_KEY="shml_your_key_here"
```

```python
from shml import ray_submit
ray_submit("print('hello')")  # Auto-detects key from env
```

### Service Account Impersonation

```python
from shml import ray_submit
ray_submit("print('hello')", impersonate="developer")
```

### Full Configuration

```python
from shml import Client

client = Client(
    base_url="https://${PUBLIC_DOMAIN}",
    api_key="shml_xxx",  # Or uses SHML_API_KEY env var
)

# Submit a job
job = client.submit(
    code="import torch; print(torch.cuda.is_available())",
    name="GPU Test",
    gpu=0.25,
    timeout_hours=1,
)

# Check status
status = client.status(job.job_id)
print(f"Job {job.job_id}: {status.status}")

# Get logs
logs = client.logs(job.job_id)
print(logs)

# List all jobs
jobs = client.list_jobs()
for j in jobs:
    print(f"{j.job_id}: {j.name} - {j.status}")
```

## Authentication

### API Keys

Generate an API key from the Ray UI or via API:

```python
from shml import Client

client = Client(base_url="...", oauth_token="your_oauth_token")
key = client.create_api_key(name="my-script", expires_in_days=30)
print(f"Save this key: {key.key}")
```

### Service Account Impersonation

If you have the `impersonation-enabled` FusionAuth group:

```python
from shml import Client

# Authenticate with your credentials first
client = Client(base_url="...", oauth_token="...")

# Start impersonation (returns a new token)
impersonated = client.impersonate("developer")

# Submit job as developer service account
job = impersonated.submit(code="print('hello')")
```

## CLI Tool

See `shml --help` for CLI usage:

```bash
# Login
shml auth login

# Submit job
shml run script.py --gpu 0.5

# Check status
shml status job-123

# Use service account
shml auth service-account developer
shml run script.py
```

## Configuration

The client looks for configuration in this order:

1. Constructor arguments
2. Environment variables
3. `~/.shml/credentials` file

### Environment Variables

- `SHML_API_KEY` - API key for authentication
- `SHML_BASE_URL` - Platform URL (default: `https://${PUBLIC_DOMAIN}`)
- `SHML_OAUTH_TOKEN` - OAuth token (alternative to API key)

### Credentials File (~/.shml/credentials)

```ini
[default]
api_key = shml_xxx
base_url = https://${PUBLIC_DOMAIN}

[dev]
api_key = shml_yyy
base_url = http://localhost:8000
```

Use profiles:

```python
from shml import Client
client = Client(profile="dev")
```

## Admin SDK (FusionAuth Management)

The SDK includes an admin module for FusionAuth administration:

```python
from shml.admin import PlatformSDK

# Initialize with FusionAuth API key
sdk = PlatformSDK(api_key="your-fusionauth-api-key")

# User management
users = sdk.users.list()
user = sdk.users.get("user-id")
sdk.users.create(email="new@example.com", password="...")

# Group management
groups = sdk.groups.list()
sdk.groups.add_member(group_id="...", user_id="...")

# API key management
keys = sdk.api_keys.list()
sdk.api_keys.create(name="my-key", permissions=["read", "write"])

# Role management
sdk.roles.assign(user_id="...", role="developer")
```

### Admin Environment Variables

- `FUSIONAUTH_API_KEY` - FusionAuth API key
- `FUSIONAUTH_URL` - FusionAuth URL (default: `http://localhost:9011`)

### Role-Based Access

The admin SDK enforces role-based permissions:
- **Admin**: Full access to all operations
- **Developer**: Read access + own resource management
- **Viewer**: Read-only access

## License

MIT - Part of the SHML Platform
