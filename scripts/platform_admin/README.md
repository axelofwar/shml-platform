# Platform Admin SDK

A modular Python SDK and CLI for managing FusionAuth users, groups, applications, and roles.

## Installation

The SDK uses only Python standard library modules (no external dependencies required).

```bash
cd sfml-platform/scripts
```

## Usage

### Command Line Interface

```bash
# Interactive mode (menus)
python -m platform_admin

# Direct commands
python admin_cli.py user list
python admin_cli.py user add
python admin_cli.py user search john
python admin_cli.py group list
python admin_cli.py app list
python admin_cli.py role list --app OAuth2-Proxy
python admin_cli.py reg list

# JSON output
python admin_cli.py --json user list
python admin_cli.py -j app list
```

### Available Commands

| Command | Description |
|---------|-------------|
| `user list` | List all users |
| `user add` | Add a new user interactively |
| `user get` | Get user details |
| `user delete` | Delete a user |
| `user search <query>` | Search for users |
| `group list` | List all groups |
| `group create` | Create a new group |
| `group add-member` | Add user to group |
| `group remove-member` | Remove user from group |
| `app list` | List all OAuth applications |
| `role list --app <name>` | List roles for an application |
| `reg list` | List user registrations |
| `reg add` | Register user to application |
| `reg update` | Update user roles |

### Python SDK

```python
from platform_admin import PlatformAdmin, Config

# Initialize with auto-detected .env
admin = PlatformAdmin()

# Or with explicit config
config = Config(
    fusionauth_url="http://localhost:9011",
    api_key="your-api-key"
)
admin = PlatformAdmin(config)

# List users
users = admin.users.list()
for user in users:
    print(f"{user['email']} - {user.get('firstName', '')} {user.get('lastName', '')}")

# Create a user
user = admin.users.create(
    email="newuser@example.com",
    password="SecurePass123!",
    first_name="New",
    last_name="User"
)

# Get user by email
user = admin.users.get_by_email("admin@ml-platform.local")

# Register user to an application with roles
admin.registrations.create(
    user_id=user["id"],
    app_id="acda34f0-7cf2-40eb-9cba-7cb0048857d3",  # OAuth2-Proxy
    roles=["viewer", "developer"]
)

# Add user to a group
groups = admin.groups.list()
admin_group = next(g for g in groups if g["name"] == "platform-admins")
admin.groups.add_member(admin_group["id"], user["id"])

# List applications and their roles
apps = admin.applications.list()
for app in apps:
    roles = admin.applications.get_roles(app["id"])
    print(f"{app['name']}: {[r['name'] for r in roles]}")
```

## Configuration

The SDK automatically loads configuration from:

1. Function arguments
2. Environment variables
3. `.env` file (searched up the directory tree)

### Required Environment Variables

```env
FUSIONAUTH_URL=http://localhost:9011
FUSIONAUTH_API_KEY=your-api-key-here
```

Or alternatively:
```env
FUSIONAUTH_ISSUER=http://localhost:9011
```

## Module Structure

```
platform_admin/
├── __init__.py          # Main exports (PlatformAdmin, Config, etc.)
├── __main__.py          # Module entry point
├── cli.py               # Interactive CLI
├── config.py            # Configuration management
├── client.py            # FusionAuth HTTP client
└── services/
    ├── __init__.py      # Service exports
    ├── users.py         # User CRUD operations
    ├── groups.py        # Group management
    ├── applications.py  # OAuth application management
    ├── roles.py         # Role management (per app)
    └── registrations.py # User-to-app registrations
```

## Examples

### Add a new developer user with platform access

```python
from platform_admin import PlatformAdmin

admin = PlatformAdmin()

# Create user
user = admin.users.create(
    email="developer@company.com",
    password="DevPass123!",
    first_name="Dev",
    last_name="User"
)

# Find OAuth2-Proxy app (controls platform access)
oauth_app = admin.applications.get_by_name("OAuth2-Proxy")

# Register with developer role
admin.registrations.create(
    user_id=user["id"],
    app_id=oauth_app["id"],
    roles=["developer", "viewer"]
)

print(f"Created user {user['email']} with developer access")
```

### Grant admin access to existing user

```python
admin = PlatformAdmin()

# Find user
user = admin.users.get_by_email("existing@company.com")

# Find OAuth2-Proxy app and platform-admins group
oauth_app = admin.applications.get_by_name("OAuth2-Proxy")
admin_group = admin.groups.get_by_name("platform-admins")

# Update registration with admin role
admin.registrations.update(
    user_id=user["id"],
    app_id=oauth_app["id"],
    roles=["admin", "developer", "viewer"]
)

# Add to admin group
admin.groups.add_member(admin_group["id"], user["id"])

print(f"Granted admin access to {user['email']}")
```

### List all users and their platform roles

```python
admin = PlatformAdmin()

oauth_app = admin.applications.get_by_name("OAuth2-Proxy")

for user in admin.users.list():
    reg = admin.registrations.get(user["id"], oauth_app["id"])
    roles = reg.get("roles", []) if reg else []
    print(f"{user['email']}: {', '.join(roles) or 'no platform access'}")
```

## Error Handling

```python
from platform_admin import PlatformAdmin
from platform_admin.client import FusionAuthError

admin = PlatformAdmin()

try:
    user = admin.users.create("invalid-email", "short")
except FusionAuthError as e:
    print(f"Error: {e}")
    print(f"Status: {e.status_code}")
    print(f"Details: {e.response}")
```

## License

MIT License - Part of the SFML Platform
