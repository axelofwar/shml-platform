"""
Nessie Integration Client
==========================

Git-like data catalog versioning: branches per experiment, tags on completion.
Uses the v1 REST API (v2 has incompatible branch creation format).
"""

from __future__ import annotations

from typing import Any

import requests

from shml.config import PlatformConfig
from shml.exceptions import NessieError


class NessieClient:
    """Nessie REST API client for experiment branching and tagging."""

    def __init__(self, config: PlatformConfig | None = None):
        self._config = config or PlatformConfig.from_env()
        self._base = self._config.nessie_uri
        self._api = f"{self._base}/api/v1"
        self._timeout = 10

    @property
    def base_url(self) -> str:
        return self._base

    def healthy(self) -> bool:
        """Check if Nessie is reachable."""
        try:
            resp = requests.get(f"{self._api}/trees", timeout=self._timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def get_main_hash(self) -> str:
        """Get the current commit hash of the main branch."""
        try:
            resp = requests.get(f"{self._api}/trees/tree/main", timeout=self._timeout)
            if resp.status_code != 200:
                raise NessieError(f"Failed to get main branch: HTTP {resp.status_code}")
            hash_val = resp.json().get("hash", "")
            if not hash_val:
                raise NessieError("Main branch returned empty hash")
            return hash_val
        except NessieError:
            raise
        except Exception as e:
            raise NessieError(f"Failed to get main hash: {e}")

    def create_branch(self, name: str, from_hash: str | None = None) -> dict[str, Any]:
        """Create a new branch, optionally from a specific hash.

        If from_hash is None, branches from current main HEAD.
        """
        if from_hash is None:
            from_hash = self.get_main_hash()

        try:
            resp = requests.post(
                f"{self._api}/trees/tree",
                json={"type": "BRANCH", "name": name, "hash": from_hash},
                timeout=self._timeout,
            )
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 409:
                # Branch already exists — not an error
                return {
                    "type": "BRANCH",
                    "name": name,
                    "hash": from_hash,
                    "existed": True,
                }
            else:
                raise NessieError(
                    f"Branch creation failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )
        except NessieError:
            raise
        except Exception as e:
            raise NessieError(f"Branch creation failed: {e}")

    def create_tag(self, name: str, from_hash: str | None = None) -> dict[str, Any]:
        """Create a tag at the current main HEAD or a specific hash."""
        if from_hash is None:
            from_hash = self.get_main_hash()

        try:
            resp = requests.post(
                f"{self._api}/trees/tree",
                json={"type": "TAG", "name": name, "hash": from_hash},
                timeout=self._timeout,
            )
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 409:
                return {"type": "TAG", "name": name, "hash": from_hash, "existed": True}
            else:
                raise NessieError(
                    f"Tag creation failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )
        except NessieError:
            raise
        except Exception as e:
            raise NessieError(f"Tag creation failed: {e}")

    def list_branches(self) -> list[dict[str, Any]]:
        """List all branches."""
        try:
            resp = requests.get(f"{self._api}/trees", timeout=self._timeout)
            if resp.status_code != 200:
                raise NessieError(f"Failed to list branches: HTTP {resp.status_code}")
            data = resp.json()
            return [r for r in data.get("references", []) if r.get("type") == "BRANCH"]
        except NessieError:
            raise
        except Exception as e:
            raise NessieError(f"Failed to list branches: {e}")

    def list_tags(self) -> list[dict[str, Any]]:
        """List all tags."""
        try:
            resp = requests.get(f"{self._api}/trees", timeout=self._timeout)
            if resp.status_code != 200:
                raise NessieError(f"Failed to list tags: HTTP {resp.status_code}")
            data = resp.json()
            return [r for r in data.get("references", []) if r.get("type") == "TAG"]
        except NessieError:
            raise
        except Exception as e:
            raise NessieError(f"Failed to list tags: {e}")

    def delete_branch(self, name: str) -> bool:
        """Delete a branch. Returns True if deleted, False if not found."""
        try:
            main_hash = self.get_main_hash()
            resp = requests.delete(
                f"{self._api}/trees/branch/{name}",
                params={"expectedHash": main_hash},
                timeout=self._timeout,
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False

    # ── Experiment lifecycle helpers ──────────────────────────────────────

    def create_experiment_branch(
        self, experiment_name: str, prefix: str = "experiment"
    ) -> str:
        """Create an experiment branch. Returns the branch name.

        Convention: experiment-{experiment_name}
        """
        branch_name = f"{prefix}-{experiment_name}"
        result = self.create_branch(branch_name)
        existed = result.get("existed", False)
        return branch_name

    def tag_experiment(
        self,
        experiment_name: str,
        metrics: dict[str, float] | None = None,
    ) -> str:
        """Create a tag for a completed experiment. Returns the tag name.

        Convention: training-phase8-{experiment_name}
        """
        tag_name = f"training-{experiment_name}"
        self.create_tag(tag_name)
        return tag_name
