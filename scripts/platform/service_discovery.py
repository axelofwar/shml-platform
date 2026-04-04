#!/usr/bin/env python3
"""Dynamic service discovery helpers for host and container runtime."""
from __future__ import annotations

import os
import socket
import subprocess
from functools import lru_cache


DEFAULT_GITLAB_BASE_URL = "http://shml-gitlab:8929/gitlab"
DEFAULT_MLFLOW_URL = "http://mlflow-nginx:80"


def _can_resolve(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


@lru_cache(maxsize=32)
def container_ip(*names: str) -> str | None:
    for name in names:
        if not name:
            continue
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "inspect",
                    name,
                    "--format",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        ip = proc.stdout.strip()
        if proc.returncode == 0 and ip:
            return ip
    return None


def resolve_host(*candidates: str) -> str | None:
    for host in candidates:
        if host and _can_resolve(host):
            return host
    return container_ip(*candidates)


def resolve_gitlab_base_url() -> str:
    if os.getenv("GITLAB_BASE_URL"):
        return os.environ["GITLAB_BASE_URL"].rstrip("/")
    # Prefer docker inspect (authoritative) over DNS/hosts which may be stale
    ip = container_ip("shml-gitlab", "gitlab")
    if ip:
        return f"http://{ip}:8929/gitlab"
    host = resolve_host("shml-gitlab", "gitlab")
    if host:
        return f"http://{host}:8929/gitlab"
    return DEFAULT_GITLAB_BASE_URL


def resolve_mlflow_url() -> str:
    if os.getenv("MLFLOW_TRACKING_URI"):
        return os.environ["MLFLOW_TRACKING_URI"].rstrip("/")
    host = resolve_host("mlflow-nginx", "mlflow-server")
    if host:
        port = 80 if host == "mlflow-nginx" else 5000
        return f"http://{host}:{port}"
    return DEFAULT_MLFLOW_URL
