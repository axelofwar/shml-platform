# Platform Admin - DEPRECATED

**This module has been deprecated and consolidated into `platform_sdk`.**

## Migration Guide

The `platform_admin` module has been merged into `platform_sdk` which provides:

- All the same functionality
- Role-based access control
- Better error handling
- Rate limiting and retries
- Async support

### Old Usage (platform_admin)

```python
from platform_admin import PlatformAdminClient
client = PlatformAdminClient()
users = client.users.list()
```

### New Usage (platform_sdk)

```python
from platform_sdk import PlatformSDK
sdk = PlatformSDK.from_env()
response = sdk.users.list()
users = response.data.get("users", [])
```

### CLI Usage

Old:
```bash
python -m platform_admin user list
```

New:
```bash
python -m platform_sdk user list
```

## Why This Change?

1. **Single Source of Truth**: One SDK to maintain instead of two
2. **Better Architecture**: platform_sdk has proper permission system
3. **More Features**: Rate limiting, retries, async support
4. **Consistency**: All platform tools use the same SDK

## Date Deprecated

December 3, 2025

## Removal Date

This archived code will be removed in a future release.
