"""
Service modules for Platform Admin SDK.

Each service module provides operations for a specific FusionAuth resource type.
"""

from .users import UsersService
from .groups import GroupsService
from .applications import ApplicationsService
from .roles import RolesService
from .registrations import RegistrationsService

__all__ = [
    "UsersService",
    "GroupsService",
    "ApplicationsService",
    "RolesService",
    "RegistrationsService",
]
