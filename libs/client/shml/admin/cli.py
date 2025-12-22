#!/usr/bin/env python3
"""
Platform SDK CLI - Interactive command-line interface for platform management.

This CLI uses the Platform SDK for all operations, inheriting its permission
system and API handling.

Usage:
    # Interactive mode (default)
    python -m platform_sdk

    # Direct commands
    python -m platform_sdk user list
    python -m platform_sdk user add
    python -m platform_sdk group list
    python -m platform_sdk role list --app oauth2-proxy
"""

import argparse
import json
import sys
from typing import Optional, List, Dict, Any

from . import PlatformSDK
from .exceptions import PermissionDeniedError, AuthenticationError, PlatformSDKError


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2, default=str))


def print_table(headers: List[str], rows: List[List[str]]) -> None:
    """Print data as a simple ASCII table."""
    if not rows:
        print("No data to display.")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))

    # Print header
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in widths)
    print(header_line)
    print(separator)

    # Print rows
    for row in rows:
        row_line = " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        print(row_line)


def select_from_list(
    items: List[Dict], display_key: str, id_key: str = "id", prompt: str = "Select"
) -> Optional[Dict]:
    """Display a numbered list and let user select an item."""
    if not items:
        print("No items available.")
        return None

    print(f"\n{prompt}:")
    for i, item in enumerate(items, 1):
        display_value = item.get(display_key, item.get("name", str(item)))
        print(f"  {i}. {display_value}")

    print(f"  0. Cancel")

    while True:
        try:
            choice = input("\nEnter number: ").strip()
            if choice == "0" or choice.lower() == "q":
                return None

            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return items[idx]
            print(f"Please enter a number between 0 and {len(items)}")
        except ValueError:
            print("Invalid input. Please enter a number.")


def confirm(prompt: str, default: bool = False) -> bool:
    """Ask for yes/no confirmation."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    response = input(prompt + suffix).strip().lower()

    if not response:
        return default
    return response in ("y", "yes")


class CLI:
    """Interactive CLI for platform administration using Platform SDK."""

    def __init__(self, json_output: bool = False):
        self.json_output = json_output
        self.sdk: Optional[PlatformSDK] = None

    def connect(self) -> bool:
        """Initialize connection to FusionAuth via SDK."""
        try:
            self.sdk = PlatformSDK.from_env()
            # Test connection by listing applications
            response = self.sdk.applications.list()
            if response.success:
                if not self.json_output:
                    print(f"✓ Connected to FusionAuth via Platform SDK")
                    print(f"  Role: {self.sdk.role.value}")
                return True
            else:
                if self.json_output:
                    print_json({"error": response.error})
                else:
                    print(f"✗ Connection failed: {response.error}")
                return False
        except AuthenticationError as e:
            if self.json_output:
                print_json({"error": str(e)})
            else:
                print(f"✗ Authentication failed: {e}")
            return False
        except Exception as e:
            if self.json_output:
                print_json({"error": str(e)})
            else:
                print(f"✗ Failed to connect: {e}")
            return False

    def _handle_error(self, e: Exception, operation: str) -> None:
        """Handle and display errors consistently."""
        if isinstance(e, PermissionDeniedError):
            print(f"✗ Permission denied: {e.message}")
            print(f"  Required roles: {e.required_roles}")
            print(f"  Your role: {e.user_role}")
        elif isinstance(e, PlatformSDKError):
            print(f"✗ {operation} failed: {e.message}")
        else:
            print(f"✗ {operation} failed: {e}")

    # ==================== USER COMMANDS ====================

    def cmd_user_list(self) -> None:
        """List all users."""
        try:
            response = self.sdk.users.list()
            if not response.success:
                print(f"✗ Failed to list users: {response.error}")
                return

            users = response.data.get("users", [])

            if self.json_output:
                print_json(users)
            else:
                headers = ["ID", "Email", "Name", "Active", "Verified"]
                rows = []
                for user in users:
                    rows.append(
                        [
                            user.get("id", "")[:8] + "...",
                            user.get("email", ""),
                            f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
                            or "-",
                            "Yes" if user.get("active") else "No",
                            "Yes" if user.get("verified") else "No",
                        ]
                    )
                print_table(headers, rows)
                print(f"\nTotal: {len(users)} users")
        except Exception as e:
            self._handle_error(e, "List users")

    def cmd_user_get(self, user_id: Optional[str] = None) -> None:
        """Get details for a specific user."""
        try:
            if not user_id:
                response = self.sdk.users.list()
                if not response.success:
                    print(f"✗ Failed to list users: {response.error}")
                    return
                users = response.data.get("users", [])
                user = select_from_list(users, "email", prompt="Select user")
                if not user:
                    return
                user_id = user["id"]

            response = self.sdk.users.get(user_id)
            if not response.success:
                print(f"✗ Failed to get user: {response.error}")
                return

            user = response.data.get("user", {})

            if self.json_output:
                print_json(user)
            else:
                print(f"\nUser Details:")
                print(f"  ID:         {user.get('id')}")
                print(f"  Email:      {user.get('email')}")
                print(
                    f"  Name:       {user.get('firstName', '')} {user.get('lastName', '')}"
                )
                print(f"  Active:     {user.get('active')}")
                print(f"  Verified:   {user.get('verified')}")
                print(f"  Created:    {user.get('insertInstant')}")

                # Show registrations
                registrations = user.get("registrations", [])
                if registrations:
                    print(f"\n  Registrations:")
                    for reg in registrations:
                        app_id = reg.get("applicationId")
                        roles = reg.get("roles", [])
                        print(
                            f"    - App: {app_id[:8]}... | Roles: {', '.join(roles) or 'none'}"
                        )
        except Exception as e:
            self._handle_error(e, "Get user")

    def cmd_user_add(self) -> None:
        """Interactively add a new user."""
        print("\n=== Add New User ===\n")

        email = input("Email: ").strip()
        if not email:
            print("Email is required.")
            return

        password = input("Password (leave blank to auto-generate): ").strip()
        if not password:
            import secrets
            import string

            password = "".join(
                secrets.choice(string.ascii_letters + string.digits + "!@#$%")
                for _ in range(16)
            )
            print(f"Generated password: {password}")

        first_name = input("First name (optional): ").strip() or None
        last_name = input("Last name (optional): ").strip() or None

        send_verification = confirm("Send verification email?", default=False)

        try:
            response = self.sdk.users.create(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )

            if not response.success:
                print(f"✗ Failed to create user: {response.error}")
                return

            user = response.data.get("user", {})
            user_id = user["id"]
            print(f"\n✓ User created: {user_id}")

            # Offer to assign to application
            if confirm("Register to an application?", default=True):
                self._register_user_to_app(user_id, email)

            if self.json_output:
                print_json(user)

        except Exception as e:
            self._handle_error(e, "Create user")

    def _register_user_to_app(self, user_id: str, email: str) -> None:
        """Helper to register a user to an application with roles."""
        try:
            response = self.sdk.applications.list()
            if not response.success:
                print(f"  ✗ Failed to list applications: {response.error}")
                return

            apps = response.data.get("applications", [])
            app = select_from_list(apps, "name", prompt="Select application")
            if not app:
                return

            # Get roles for the application
            roles_response = self.sdk.roles.list_for_application(app["id"])
            roles_to_assign = []

            if roles_response.success:
                app_roles = roles_response.data.get("roles", [])
                if app_roles:
                    print(
                        "\nAvailable roles (enter numbers separated by commas, or 'all'):"
                    )
                    for i, role in enumerate(app_roles, 1):
                        print(f"  {i}. {role.get('name')}")

                    role_input = input("\nRoles to assign: ").strip()
                    if role_input.lower() == "all":
                        roles_to_assign = [r["name"] for r in app_roles]
                    elif role_input:
                        try:
                            indices = [
                                int(x.strip()) - 1 for x in role_input.split(",")
                            ]
                            roles_to_assign = [
                                app_roles[i]["name"]
                                for i in indices
                                if 0 <= i < len(app_roles)
                            ]
                        except (ValueError, IndexError):
                            print("Invalid role selection, skipping roles.")

            reg_response = self.sdk.registrations.create(
                user_id, app["id"], roles=roles_to_assign
            )
            if reg_response.success:
                print(
                    f"  ✓ Registered to {app['name']} with roles: {', '.join(roles_to_assign) or 'none'}"
                )
            else:
                print(f"  ✗ Registration failed: {reg_response.error}")

        except Exception as e:
            self._handle_error(e, "Register user")

    def cmd_user_delete(self, user_id: Optional[str] = None) -> None:
        """Delete a user."""
        try:
            if not user_id:
                response = self.sdk.users.list()
                if not response.success:
                    print(f"✗ Failed to list users: {response.error}")
                    return
                users = response.data.get("users", [])
                user = select_from_list(users, "email", prompt="Select user to delete")
                if not user:
                    return
                user_id = user["id"]
                email = user.get("email")
            else:
                response = self.sdk.users.get(user_id)
                if not response.success:
                    print(f"✗ User not found: {response.error}")
                    return
                email = response.data.get("user", {}).get("email", user_id)

            if not confirm(f"Delete user {email}?"):
                print("Cancelled.")
                return

            response = self.sdk.users.delete(user_id)
            if response.success:
                print(f"✓ User {email} deleted.")
            else:
                print(f"✗ Failed to delete user: {response.error}")

        except Exception as e:
            self._handle_error(e, "Delete user")

    def cmd_user_search(self, query: Optional[str] = None) -> None:
        """Search for users."""
        if not query:
            query = input("Search query (email, name): ").strip()

        if not query:
            print("Search query required.")
            return

        try:
            response = self.sdk.users.search(query)
            if not response.success:
                print(f"✗ Search failed: {response.error}")
                return

            users = response.data.get("users", [])

            if self.json_output:
                print_json(users)
            else:
                headers = ["ID", "Email", "Name"]
                rows = []
                for user in users:
                    rows.append(
                        [
                            user.get("id", "")[:8] + "...",
                            user.get("email", ""),
                            f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
                            or "-",
                        ]
                    )
                print_table(headers, rows)
                print(f"\nFound: {len(users)} users")

        except Exception as e:
            self._handle_error(e, "Search users")

    # ==================== GROUP COMMANDS ====================

    def cmd_group_list(self) -> None:
        """List all groups."""
        try:
            response = self.sdk.groups.list()
            if not response.success:
                print(f"✗ Failed to list groups: {response.error}")
                return

            groups = response.data.get("groups", [])

            if self.json_output:
                print_json(groups)
            else:
                headers = ["ID", "Name", "Description"]
                rows = []
                for group in groups:
                    rows.append(
                        [
                            group.get("id", "")[:8] + "...",
                            group.get("name", ""),
                            (group.get("data", {}).get("description", "") or "-")[:40],
                        ]
                    )
                print_table(headers, rows)
                print(f"\nTotal: {len(groups)} groups")

        except Exception as e:
            self._handle_error(e, "List groups")

    def cmd_group_create(self) -> None:
        """Create a new group."""
        print("\n=== Create New Group ===\n")

        name = input("Group name: ").strip()
        if not name:
            print("Name is required.")
            return

        description = input("Description (optional): ").strip() or None

        try:
            response = self.sdk.groups.create(name, description=description)
            if response.success:
                group = response.data.get("group", {})
                print(f"✓ Group created: {group.get('id')}")
                if self.json_output:
                    print_json(group)
            else:
                print(f"✗ Failed to create group: {response.error}")

        except Exception as e:
            self._handle_error(e, "Create group")

    def cmd_group_add_member(self) -> None:
        """Add a user to a group."""
        try:
            # Select group
            response = self.sdk.groups.list()
            if not response.success:
                print(f"✗ Failed to list groups: {response.error}")
                return
            groups = response.data.get("groups", [])
            group = select_from_list(groups, "name", prompt="Select group")
            if not group:
                return

            # Select user
            response = self.sdk.users.list()
            if not response.success:
                print(f"✗ Failed to list users: {response.error}")
                return
            users = response.data.get("users", [])
            user = select_from_list(users, "email", prompt="Select user to add")
            if not user:
                return

            response = self.sdk.groups.add_member(group["id"], user["id"])
            if response.success:
                print(f"✓ Added {user['email']} to group {group['name']}")
            else:
                print(f"✗ Failed: {response.error}")

        except Exception as e:
            self._handle_error(e, "Add group member")

    def cmd_group_remove_member(self) -> None:
        """Remove a user from a group."""
        try:
            # Select group
            response = self.sdk.groups.list()
            if not response.success:
                print(f"✗ Failed to list groups: {response.error}")
                return
            groups = response.data.get("groups", [])
            group = select_from_list(groups, "name", prompt="Select group")
            if not group:
                return

            # Select user
            response = self.sdk.users.list()
            if not response.success:
                print(f"✗ Failed to list users: {response.error}")
                return
            users = response.data.get("users", [])
            user = select_from_list(users, "email", prompt="Select user to remove")
            if not user:
                return

            response = self.sdk.groups.remove_member(group["id"], user["id"])
            if response.success:
                print(f"✓ Removed {user['email']} from group {group['name']}")
            else:
                print(f"✗ Failed: {response.error}")

        except Exception as e:
            self._handle_error(e, "Remove group member")

    # ==================== APPLICATION/ROLE COMMANDS ====================

    def cmd_app_list(self) -> None:
        """List all applications."""
        try:
            response = self.sdk.applications.list()
            if not response.success:
                print(f"✗ Failed to list applications: {response.error}")
                return

            apps = response.data.get("applications", [])

            if self.json_output:
                print_json(apps)
            else:
                headers = ["ID", "Name", "Active"]
                rows = []
                for app in apps:
                    rows.append(
                        [
                            app.get("id", "")[:8] + "...",
                            app.get("name", ""),
                            "Yes" if app.get("active") else "No",
                        ]
                    )
                print_table(headers, rows)
                print(f"\nTotal: {len(apps)} applications")

        except Exception as e:
            self._handle_error(e, "List applications")

    def cmd_role_list(self, app_name: Optional[str] = None) -> None:
        """List roles for an application."""
        try:
            response = self.sdk.applications.list()
            if not response.success:
                print(f"✗ Failed to list applications: {response.error}")
                return

            apps = response.data.get("applications", [])

            if app_name:
                # Find app by name
                app = next(
                    (a for a in apps if a.get("name", "").lower() == app_name.lower()),
                    None,
                )
                if not app:
                    print(f"Application '{app_name}' not found.")
                    return
            else:
                app = select_from_list(apps, "name", prompt="Select application")
                if not app:
                    return

            response = self.sdk.roles.list_for_application(app["id"])
            if not response.success:
                print(f"✗ Failed to list roles: {response.error}")
                return

            roles = response.data.get("roles", [])

            if self.json_output:
                print_json(roles)
            else:
                print(f"\nRoles for {app['name']}:")
                if roles:
                    for role in roles:
                        desc = role.get("description", "")
                        default = " (default)" if role.get("isDefault") else ""
                        super_role = " [SUPER]" if role.get("isSuperRole") else ""
                        print(f"  - {role['name']}{default}{super_role}")
                        if desc:
                            print(f"      {desc}")
                else:
                    print("  No roles defined.")

        except Exception as e:
            self._handle_error(e, "List roles")

    # ==================== REGISTRATION COMMANDS ====================

    def cmd_reg_list(self, user_id: Optional[str] = None) -> None:
        """List registrations for a user."""
        try:
            if not user_id:
                response = self.sdk.users.list()
                if not response.success:
                    print(f"✗ Failed to list users: {response.error}")
                    return
                users = response.data.get("users", [])
                user = select_from_list(users, "email", prompt="Select user")
                if not user:
                    return
                user_id = user["id"]

            response = self.sdk.users.get(user_id)
            if not response.success:
                print(f"✗ Failed to get user: {response.error}")
                return

            user = response.data.get("user", {})
            registrations = user.get("registrations", [])

            if self.json_output:
                print_json(registrations)
            else:
                print(f"\nRegistrations for {user.get('email')}:")
                if registrations:
                    # Get app names
                    apps_response = self.sdk.applications.list()
                    apps = {}
                    if apps_response.success:
                        apps = {
                            a["id"]: a["name"]
                            for a in apps_response.data.get("applications", [])
                        }

                    for reg in registrations:
                        app_id = reg.get("applicationId")
                        app_name = apps.get(app_id, app_id[:8] + "...")
                        roles = reg.get("roles", [])
                        print(f"  - {app_name}: {', '.join(roles) or 'no roles'}")
                else:
                    print("  No registrations.")

        except Exception as e:
            self._handle_error(e, "List registrations")

    def cmd_reg_add(self) -> None:
        """Register a user to an application with roles."""
        try:
            # Select user
            response = self.sdk.users.list()
            if not response.success:
                print(f"✗ Failed to list users: {response.error}")
                return
            users = response.data.get("users", [])
            user = select_from_list(users, "email", prompt="Select user")
            if not user:
                return

            self._register_user_to_app(user["id"], user["email"])

        except Exception as e:
            self._handle_error(e, "Register user")

    def cmd_reg_update_roles(self) -> None:
        """Update roles for an existing registration."""
        try:
            # Select user
            response = self.sdk.users.list()
            if not response.success:
                print(f"✗ Failed to list users: {response.error}")
                return
            users = response.data.get("users", [])
            user = select_from_list(users, "email", prompt="Select user")
            if not user:
                return

            # Get user's registrations
            response = self.sdk.users.get(user["id"])
            if not response.success:
                print(f"✗ Failed to get user: {response.error}")
                return

            full_user = response.data.get("user", {})
            registrations = full_user.get("registrations", [])

            if not registrations:
                print("User has no registrations.")
                return

            # Get apps for display
            apps_response = self.sdk.applications.list()
            apps = {}
            if apps_response.success:
                apps = {a["id"]: a for a in apps_response.data.get("applications", [])}

            # Select registration
            reg_items = []
            for reg in registrations:
                app = apps.get(reg["applicationId"], {})
                reg_items.append(
                    {
                        "id": reg["applicationId"],
                        "name": f"{app.get('name', 'Unknown')} (roles: {', '.join(reg.get('roles', [])) or 'none'})",
                    }
                )

            selected = select_from_list(
                reg_items, "name", prompt="Select registration to update"
            )
            if not selected:
                return

            app_id = selected["id"]
            app = apps.get(app_id, {})

            # Select new roles
            roles_response = self.sdk.roles.list_for_application(app_id)
            roles_to_assign = []

            if roles_response.success:
                app_roles = roles_response.data.get("roles", [])
                if app_roles:
                    print(
                        "\nAvailable roles (enter numbers separated by commas, or 'all', or press Enter for none):"
                    )
                    for i, role in enumerate(app_roles, 1):
                        print(f"  {i}. {role.get('name')}")

                    role_input = input("\nNew roles: ").strip()
                    if role_input.lower() == "all":
                        roles_to_assign = [r["name"] for r in app_roles]
                    elif role_input:
                        try:
                            indices = [
                                int(x.strip()) - 1 for x in role_input.split(",")
                            ]
                            roles_to_assign = [
                                app_roles[i]["name"]
                                for i in indices
                                if 0 <= i < len(app_roles)
                            ]
                        except (ValueError, IndexError):
                            print("Invalid role selection.")
                            return

            response = self.sdk.registrations.update(
                user["id"], app_id, roles=roles_to_assign
            )
            if response.success:
                print(
                    f"✓ Updated roles for {user['email']} in {app.get('name', 'Unknown')}: {', '.join(roles_to_assign) or 'none'}"
                )
            else:
                print(f"✗ Failed: {response.error}")

        except Exception as e:
            self._handle_error(e, "Update roles")

    # ==================== INTERACTIVE MENU ====================

    def interactive_menu(self) -> None:
        """Run interactive menu mode."""
        print("\n" + "=" * 50)
        print("  Platform SDK CLI - FusionAuth Management")
        print("=" * 50)

        if not self.connect():
            return

        while True:
            print("\n--- Main Menu ---")
            print("  1. Users")
            print("  2. Groups")
            print("  3. Applications & Roles")
            print("  4. Registrations")
            print("  0. Exit")

            choice = input("\nSelect: ").strip()

            if choice == "0" or choice.lower() == "q":
                print("Goodbye!")
                break
            elif choice == "1":
                self._user_menu()
            elif choice == "2":
                self._group_menu()
            elif choice == "3":
                self._app_menu()
            elif choice == "4":
                self._reg_menu()
            else:
                print("Invalid choice.")

    def _user_menu(self) -> None:
        """User management submenu."""
        while True:
            print("\n--- User Management ---")
            print("  1. List all users")
            print("  2. Search users")
            print("  3. Get user details")
            print("  4. Add new user")
            print("  5. Delete user")
            print("  0. Back")

            choice = input("\nSelect: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.cmd_user_list()
            elif choice == "2":
                self.cmd_user_search()
            elif choice == "3":
                self.cmd_user_get()
            elif choice == "4":
                self.cmd_user_add()
            elif choice == "5":
                self.cmd_user_delete()

    def _group_menu(self) -> None:
        """Group management submenu."""
        while True:
            print("\n--- Group Management ---")
            print("  1. List all groups")
            print("  2. Create group")
            print("  3. Add member to group")
            print("  4. Remove member from group")
            print("  0. Back")

            choice = input("\nSelect: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.cmd_group_list()
            elif choice == "2":
                self.cmd_group_create()
            elif choice == "3":
                self.cmd_group_add_member()
            elif choice == "4":
                self.cmd_group_remove_member()

    def _app_menu(self) -> None:
        """Application/role management submenu."""
        while True:
            print("\n--- Applications & Roles ---")
            print("  1. List applications")
            print("  2. List roles for an application")
            print("  0. Back")

            choice = input("\nSelect: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.cmd_app_list()
            elif choice == "2":
                self.cmd_role_list()

    def _reg_menu(self) -> None:
        """Registration management submenu."""
        while True:
            print("\n--- Registration Management ---")
            print("  1. List user registrations")
            print("  2. Register user to application")
            print("  3. Update user roles")
            print("  0. Back")

            choice = input("\nSelect: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.cmd_reg_list()
            elif choice == "2":
                self.cmd_reg_add()
            elif choice == "3":
                self.cmd_reg_update_roles()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Platform SDK CLI - FusionAuth Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Interactive mode
  %(prog)s user list                 # List all users
  %(prog)s user add                  # Add a new user interactively
  %(prog)s user search john          # Search for users
  %(prog)s group list                # List all groups
  %(prog)s role list --app OAuth2-Proxy  # List roles for app
  %(prog)s reg list                  # List registrations for a user
""",
    )

    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # User commands
    user_parser = subparsers.add_parser("user", help="User management")
    user_sub = user_parser.add_subparsers(dest="subcommand")
    user_sub.add_parser("list", help="List all users")
    user_sub.add_parser("add", help="Add a new user")
    user_sub.add_parser("get", help="Get user details")
    user_sub.add_parser("delete", help="Delete a user")
    search_parser = user_sub.add_parser("search", help="Search for users")
    search_parser.add_argument("query", nargs="?", help="Search query")

    # Group commands
    group_parser = subparsers.add_parser("group", help="Group management")
    group_sub = group_parser.add_subparsers(dest="subcommand")
    group_sub.add_parser("list", help="List all groups")
    group_sub.add_parser("create", help="Create a new group")
    group_sub.add_parser("add-member", help="Add user to group")
    group_sub.add_parser("remove-member", help="Remove user from group")

    # App commands
    app_parser = subparsers.add_parser("app", help="Application management")
    app_sub = app_parser.add_subparsers(dest="subcommand")
    app_sub.add_parser("list", help="List all applications")

    # Role commands
    role_parser = subparsers.add_parser("role", help="Role management")
    role_sub = role_parser.add_subparsers(dest="subcommand")
    role_list = role_sub.add_parser("list", help="List roles for an application")
    role_list.add_argument("--app", "-a", help="Application name")

    # Registration commands
    reg_parser = subparsers.add_parser("reg", help="Registration management")
    reg_sub = reg_parser.add_subparsers(dest="subcommand")
    reg_sub.add_parser("list", help="List user registrations")
    reg_sub.add_parser("add", help="Register user to application")
    reg_sub.add_parser("update", help="Update user roles")

    args = parser.parse_args()

    cli = CLI(json_output=args.json)

    # Interactive mode if no command specified
    if not args.command:
        cli.interactive_menu()
        return

    # Connect for direct commands
    if not cli.connect():
        sys.exit(1)

    # Route to command handlers
    if args.command == "user":
        if args.subcommand == "list":
            cli.cmd_user_list()
        elif args.subcommand == "add":
            cli.cmd_user_add()
        elif args.subcommand == "get":
            cli.cmd_user_get()
        elif args.subcommand == "delete":
            cli.cmd_user_delete()
        elif args.subcommand == "search":
            cli.cmd_user_search(getattr(args, "query", None))
        else:
            user_parser.print_help()

    elif args.command == "group":
        if args.subcommand == "list":
            cli.cmd_group_list()
        elif args.subcommand == "create":
            cli.cmd_group_create()
        elif args.subcommand == "add-member":
            cli.cmd_group_add_member()
        elif args.subcommand == "remove-member":
            cli.cmd_group_remove_member()
        else:
            group_parser.print_help()

    elif args.command == "app":
        if args.subcommand == "list":
            cli.cmd_app_list()
        else:
            app_parser.print_help()

    elif args.command == "role":
        if args.subcommand == "list":
            cli.cmd_role_list(getattr(args, "app", None))
        else:
            role_parser.print_help()

    elif args.command == "reg":
        if args.subcommand == "list":
            cli.cmd_reg_list()
        elif args.subcommand == "add":
            cli.cmd_reg_add()
        elif args.subcommand == "update":
            cli.cmd_reg_update_roles()
        else:
            reg_parser.print_help()


if __name__ == "__main__":
    main()
