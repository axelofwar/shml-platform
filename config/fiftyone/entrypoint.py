#!/usr/bin/env python3
"""
FiftyOne Proxy Entrypoint — Patches index.html for reverse proxy path prefix.

When FiftyOne runs behind Traefik at /fiftyone/, the JS needs
window.FIFTYONE_SERVER_PATH_PREFIX set so fetch() calls go to
/fiftyone/graphql instead of /graphql.

This script patches the index.html at startup, then launches the app.
It's version-resilient — it finds the static dir dynamically.
"""

import glob
import os
import re
import subprocess
import sys


PATH_PREFIX = os.environ.get("FIFTYONE_PATH_PREFIX", "/fiftyone")

INJECT_SCRIPT = f'<script>window.FIFTYONE_SERVER_PATH_PREFIX="{PATH_PREFIX}";</script>'


def find_index_html():
    """Find FiftyOne's index.html dynamically."""
    patterns = [
        "/opt/.fiftyone-venv/lib/python*/site-packages/fiftyone/server/static/index.html",
        "/usr/local/lib/python*/site-packages/fiftyone/server/static/index.html",
        "/usr/lib/python*/site-packages/fiftyone/server/static/index.html",
    ]
    for pat in patterns:
        matches = glob.glob(pat)
        if matches:
            return matches[0]
    return None


def patch_index(path):
    """Inject path prefix script into index.html if not already present."""
    with open(path, "r") as f:
        html = f.read()

    if "FIFTYONE_SERVER_PATH_PREFIX" in html:
        print(f"[fiftyone-proxy] index.html already patched (prefix={PATH_PREFIX})")
        return

    # Insert before <title> or first <script>
    patched = re.sub(
        r"(<head[^>]*>)",
        rf"\1\n    {INJECT_SCRIPT}",
        html,
        count=1,
    )

    with open(path, "w") as f:
        f.write(patched)

    print(f"[fiftyone-proxy] Patched index.html with path prefix: {PATH_PREFIX}")


def main():
    index_path = find_index_html()
    if index_path:
        try:
            patch_index(index_path)
        except Exception as e:
            print(f"[fiftyone-proxy] WARNING: Could not patch index.html: {e}")
    else:
        print("[fiftyone-proxy] WARNING: Could not find FiftyOne index.html")

    # Execute the original command
    cmd = sys.argv[1:] or [
        "fiftyone",
        "app",
        "launch",
        "--address",
        "0.0.0.0",
        "--port",
        "5151",
        "--remote",
        "--wait",
        "-1",
    ]
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
