"""
FusionAuth API Client for Platform Admin SDK.

Provides base HTTP client with authentication and error handling,
plus the high-level PlatformAdminClient with service modules.
"""

import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import Config


@dataclass
class APIResponse:
    """
    Wrapper for API responses.

    Provides consistent interface for success/error handling.
    """

    success: bool
    status_code: int
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        """Convert response to JSON string."""
        return json.dumps(
            {
                "success": self.success,
                "status_code": self.status_code,
                "data": self.data,
                "error": self.error,
            },
            indent=2,
        )


class FusionAuthError(Exception):
    """Exception raised for FusionAuth API errors."""

    def __init__(self, message: str, status_code: int = None, response: Dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class FusionAuthClient:
    """
    Low-level HTTP client for FusionAuth API.

    Handles authentication, request/response formatting, and error handling.
    Returns APIResponse objects for all operations.
    """

    def __init__(self, config: Config):
        """
        Initialize the FusionAuth client.

        Args:
            config: Configuration object with URL and API key
        """
        self.config = config
        self.base_url = config.fusionauth_url.rstrip("/")
        self.api_key = config.api_key

        if not self.api_key:
            raise ValueError("FusionAuth API key is required")

    def validate_connection(self) -> APIResponse:
        """
        Validate API key and connection to FusionAuth.

        Returns:
            APIResponse indicating success or failure with details.
        """
        response = self.get("/api/status")

        if response.success:
            return APIResponse(
                success=True,
                status_code=200,
                data={"message": "API connection validated successfully"},
            )

        return APIResponse(
            success=False,
            status_code=response.status_code,
            error=f"Failed to validate API connection: {response.error}",
        )

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> APIResponse:
        """
        Make an HTTP request to the FusionAuth API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (e.g., /api/user)
            data: Request body data
            params: Query parameters

        Returns:
            APIResponse with result or error
        """
        url = f"{self.base_url}{endpoint}"

        # Add query parameters
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url = f"{url}?{query}"

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(request, timeout=30) as response:
                status_code = response.getcode()
                response_body = response.read().decode("utf-8")

                if response_body:
                    try:
                        parsed = json.loads(response_body)
                    except json.JSONDecodeError:
                        parsed = {"raw": response_body}
                else:
                    parsed = {}

                return APIResponse(success=True, status_code=status_code, data=parsed)

        except HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            try:
                error_data = json.loads(error_body) if error_body else {}
            except json.JSONDecodeError:
                error_data = {"raw": error_body}

            # Extract error message
            message = error_data.get("message", "")
            if not message and "fieldErrors" in error_data:
                # Format field errors
                field_errors = error_data["fieldErrors"]
                messages = []
                for field, errors in field_errors.items():
                    for err in errors:
                        messages.append(f"{field}: {err.get('message', err)}")
                message = "; ".join(messages)

            if not message:
                message = f"HTTP {e.code}: {e.reason}"

            return APIResponse(
                success=False, status_code=e.code, data=error_data, error=message
            )

        except URLError as e:
            return APIResponse(
                success=False, status_code=0, error=f"Connection error: {e.reason}"
            )

        except Exception as e:
            return APIResponse(
                success=False, status_code=0, error=f"Unexpected error: {str(e)}"
            )

    def get(self, endpoint: str, params: Optional[Dict] = None) -> APIResponse:
        """Make a GET request."""
        return self._make_request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Optional[Dict] = None) -> APIResponse:
        """Make a POST request."""
        return self._make_request("POST", endpoint, data=data)

    def put(self, endpoint: str, data: Optional[Dict] = None) -> APIResponse:
        """Make a PUT request."""
        return self._make_request("PUT", endpoint, data=data)

    def patch(self, endpoint: str, data: Optional[Dict] = None) -> APIResponse:
        """Make a PATCH request."""
        return self._make_request("PATCH", endpoint, data=data)

    def delete(self, endpoint: str, params: Optional[Dict] = None) -> APIResponse:
        """Make a DELETE request."""
        return self._make_request("DELETE", endpoint, params=params)


class PlatformAdminClient:
    """
    High-level Platform Admin client.

    Provides service modules for users, groups, roles, and applications.
    Use this as the main entry point for the SDK.

    Example:
        from platform_admin import PlatformAdminClient

        client = PlatformAdminClient()

        # List users
        response = client.users.list()
        if response.success:
            for user in response.data.get("users", []):
                print(user["email"])

        # Create a user
        response = client.users.create(
            email="new@example.com",
            password="SecurePass123!"
        )
    """

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the Platform Admin client.

        Args:
            config: Optional config. If None, loads from environment.
        """
        self._config = config or Config.from_env()
        self._api = FusionAuthClient(self._config)

        # Lazy-loaded service modules
        self._users = None
        self._groups = None
        self._roles = None
        self._applications = None
        self._registrations = None

    @property
    def config(self) -> Config:
        """Get the configuration."""
        return self._config

    @property
    def api(self) -> FusionAuthClient:
        """Get the underlying API client."""
        return self._api

    def validate(self) -> APIResponse:
        """Validate API connection and key."""
        return self._api.validate_connection()

    @property
    def users(self):
        """Get the users service module."""
        if self._users is None:
            from .services.users import UsersService

            self._users = UsersService(self._api)
        return self._users

    @property
    def groups(self):
        """Get the groups service module."""
        if self._groups is None:
            from .services.groups import GroupsService

            self._groups = GroupsService(self._api)
        return self._groups

    @property
    def roles(self):
        """Get the roles service module."""
        if self._roles is None:
            from .services.roles import RolesService

            self._roles = RolesService(self._api)
        return self._roles

    @property
    def applications(self):
        """Get the applications service module."""
        if self._applications is None:
            from .services.applications import ApplicationsService

            self._applications = ApplicationsService(self._api)
        return self._applications

    @property
    def registrations(self):
        """Get the registrations service module."""
        if self._registrations is None:
            from .services.registrations import RegistrationsService

            self._registrations = RegistrationsService(self._api)
        return self._registrations
