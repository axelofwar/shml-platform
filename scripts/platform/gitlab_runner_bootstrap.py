#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
from dataclasses import dataclass

try:
    from gitlab_utils import _api
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    sys.path.insert(0, os.path.dirname(__file__))
    from gitlab_utils import _api


@dataclass(frozen=True)
class RunnerProject:
    name: str
    project_id: str
    token_env: str


def _runner_projects() -> list[RunnerProject]:
    return [
        RunnerProject(
            name="platform",
            project_id=os.getenv("GITLAB_PLATFORM_PROJECT_ID", "2"),
            token_env="GITLAB_PLATFORM_RUNNER_REGISTRATION_TOKEN",
        ),
        RunnerProject(
            name="robotics",
            project_id=os.getenv("GITLAB_ROBOTICS_PROJECT_ID", "3"),
            token_env="GITLAB_ROBOTICS_RUNNER_REGISTRATION_TOKEN",
        ),
        RunnerProject(
            name="training",
            project_id=os.getenv("GITLAB_TRAINING_PROJECT_ID", "4"),
            token_env="GITLAB_TRAINING_RUNNER_REGISTRATION_TOKEN",
        ),
    ]


def _project_runner_token(project_id: str) -> str:
    payload = _api("GET", f"/projects/{project_id}")
    token = str(payload.get("runners_token") or "").strip()
    if not token:
        raise RuntimeError(f"GitLab project {project_id} did not return a runners_token")
    return token


def export_env() -> int:
    for project in _runner_projects():
        token = _project_runner_token(project.project_id)
        print(f"export {project.token_env}={shlex.quote(token)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch GitLab project runner registration tokens")
    parser.add_argument(
        "command",
        nargs="?",
        default="export-env",
        choices=["export-env"],
        help="Output shell exports for per-project runner registration tokens",
    )
    parser.parse_args()
    return export_env()


if __name__ == "__main__":
    raise SystemExit(main())
