# Authentication

Commands for managing credentials used to communicate with the SHML Platform API.

---

## Credential Storage

Credentials are stored in:

```
~/.shml/credentials
```

The CLI reads and writes this file automatically. The directory is created on first login.

!!! warning "File permissions"
    Ensure `~/.shml/credentials` is only readable by your user (`chmod 600`). The file contains sensitive API keys or OAuth tokens.

---

## shml auth login

Store authentication credentials for the platform.

```
shml auth login [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--api-key` | `-k` | `TEXT` | *None* | API key (prompted interactively if omitted) |
| `--url` | | `TEXT` | *None* | Platform base URL |

### API Key Login

```bash
# Provide key inline
shml auth login --api-key sk-abc123...xyz

# Provide key + custom URL
shml auth login --api-key sk-abc123...xyz --url https://shml.example.com

# Interactive prompt (key is hidden when Rich is installed)
shml auth login
```

!!! note "Interactive prompt"
    If `--api-key` is not provided, the CLI prompts for it. With Rich installed, the prompt masks input for security.

### OAuth Login

The platform also supports OAuth tokens managed via `AuthConfig`. When an OAuth token is present in the credentials file, the CLI uses it automatically. See the SDK documentation for programmatic OAuth flows.

---

## shml auth status

Show the current authentication state.

```
shml auth status
```

### Example

```bash
shml auth status
```

Authenticated with an API key:

```
✓ Authenticated (API key: sk-abc12...9xyz)
```

Authenticated with OAuth:

```
✓ Authenticated (OAuth token)
```

Not authenticated:

```
Not authenticated. Run: shml auth login
```

!!! info
    The API key is partially masked in the output — only the first 8 and last 4 characters are shown.

---

## shml auth logout

Clear all stored credentials.

```
shml auth logout
```

### Example

```bash
shml auth logout
```

```
✓ Credentials cleared
```

If no credentials exist:

```
No credentials to clear
```

---

## Environment Variables

The CLI client also respects environment variables for configuration:

| Variable | Description |
|----------|-------------|
| `SHML_API_KEY` | API key (overrides stored credentials) |
| `SHML_BASE_URL` | Platform URL |

These can be used in CI/CD pipelines where interactive login is not feasible:

```bash
export SHML_API_KEY="sk-abc123..."
export SHML_BASE_URL="https://shml.example.com"
shml train --profile balanced --epochs 10
```
