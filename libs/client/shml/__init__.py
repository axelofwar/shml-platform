"""
SHML Client SDK - Simple Python client for the SHML Platform.

Quick usage (<150 chars):
    from shml import ray_submit
    ray_submit("print('hello')", key="shml_xxx")

Full client:
    from shml import Client
    client = Client(api_key="shml_xxx")
    job = client.submit(code="print('hello')", gpu=0.25)

Admin SDK (FusionAuth management):
    from shml.admin import PlatformSDK
    sdk = PlatformSDK(api_key="fusionauth-api-key")
    users = sdk.users.list()
"""

from .client import Client
from .shortcuts import ray_submit, ray_status, ray_logs
from .models import Job, JobStatus, User, Quota


# Lazy import for admin module to avoid loading unnecessary dependencies
def __getattr__(name):
    if name == "admin":
        from . import admin

        return admin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__version__ = "0.1.0"
__all__ = [
    "Client",
    "ray_submit",
    "ray_status",
    "ray_logs",
    "Job",
    "JobStatus",
    "User",
    "Quota",
    "admin",
]
