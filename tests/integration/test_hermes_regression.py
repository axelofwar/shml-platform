"""
Hermes integration regression tests.

Tests the gateway session API and workspace integration points.
Requires: Hermes gateway running on localhost:8642

Markers: integration (skipped by default — run with: pytest -m integration)
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

GATEWAY_URL = os.environ.get("HERMES_GATEWAY_URL", "http://127.0.0.1:8642")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_SESSION_TOKEN = os.environ.get("HERMES_SESSION_TOKEN", "")
STATE_DB = HERMES_HOME / "state.db"


def gateway_available() -> bool:
    try:
        req = Request(f"{GATEWAY_URL}/health", method="GET")
        with urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


skip_no_gateway = pytest.mark.skipif(
    not gateway_available(),
    reason="Hermes gateway not running at " + GATEWAY_URL,
)


def _build_request(path: str, method: str, body: dict | None = None) -> Request:
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{GATEWAY_URL}{path}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if HERMES_SESSION_TOKEN:
        req.add_header("Authorization", f"Bearer {HERMES_SESSION_TOKEN}")
    return req


def session_api_accessible() -> bool:
    try:
        api_get("/api/sessions")
        return True
    except HTTPError as exc:
        if exc.code == 401:
            return False
        raise


def api_get(path: str) -> dict:
    req = _build_request(path, "GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_post(path: str, body: dict) -> dict:
    req = _build_request(path, "POST", body)
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_patch(path: str, body: dict) -> tuple[int, dict]:
    req = _build_request(path, "PATCH", body)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def api_delete(path: str) -> int:
    req = _build_request(path, "DELETE")
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code


skip_no_session_api_access = pytest.mark.skipif(
    not gateway_available() or not session_api_accessible(),
    reason="Hermes session API requires a valid HERMES_SESSION_TOKEN",
)


# ── Gateway Health ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestGatewayHealth:
    @skip_no_gateway
    def test_health_endpoint(self):
        result = api_get("/health")
        assert result.get("status") == "ok"

    @skip_no_gateway
    def test_sessions_list(self):
        try:
            result = api_get("/api/sessions")
        except HTTPError as exc:
            assert exc.code == 401, f"Expected public session list or 401, got {exc.code}"
            return

        assert "sessions" in result or "items" in result or isinstance(result, list)


# ── Session Title Uniqueness (the "hi" bug) ─────────────────────────────────


@pytest.mark.integration
class TestSessionTitleUniqueness:
    @skip_no_session_api_access
    def test_create_session_with_title(self):
        """Creating a session via gateway works."""
        import uuid

        unique_title = f"test-{uuid.uuid4().hex[:8]}"
        result = api_post("/api/sessions", {"title": unique_title})
        assert "session" in result
        session_id = result["session"]["id"]
        # Clean up
        api_delete(f"/api/sessions/{session_id}")

    @skip_no_session_api_access
    def test_duplicate_title_returns_error(self):
        """Two sessions with same title should fail on second."""
        import uuid

        title = f"dup-test-{uuid.uuid4().hex[:8]}"
        r1 = api_post("/api/sessions", {"title": title})
        assert "session" in r1
        sid1 = r1["session"]["id"]

        try:
            # Second session with same title via PATCH
            r2 = api_post("/api/sessions", {})
            sid2 = r2["session"]["id"]
            status, body = api_patch(f"/api/sessions/{sid2}", {"title": title})
            assert status == 500
            assert "already in use" in body.get("error", "")
            api_delete(f"/api/sessions/{sid2}")
        finally:
            api_delete(f"/api/sessions/{sid1}")


# ── SQLite State DB ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestStateDB:
    @pytest.mark.skipif(
        not STATE_DB.exists(), reason="state.db not found"
    )
    def test_db_has_sessions(self):
        conn = sqlite3.connect(str(STATE_DB))
        try:
            count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            assert count > 0, "Expected sessions in state.db"
        finally:
            conn.close()

    @pytest.mark.skipif(
        not STATE_DB.exists(), reason="state.db not found"
    )
    def test_db_has_fts_index(self):
        conn = sqlite3.connect(str(STATE_DB))
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert any(
                "fts" in t.lower() for t in tables
            ), f"No FTS table found. Tables: {tables}"
        finally:
            conn.close()


# ── Context File Loading ────────────────────────────────────────────────────


@pytest.mark.unit
class TestContextFiles:
    def test_hermes_md_exists(self):
        """The focused .hermes.md context file should exist in shml-platform."""
        platform_root = Path(__file__).resolve().parent.parent.parent
        hermes_md = platform_root / ".hermes.md"
        assert hermes_md.exists(), f"Expected .hermes.md at {hermes_md}"

    def test_hermes_md_not_bloated(self):
        """The .hermes.md file should be under 5KB (focused context)."""
        platform_root = Path(__file__).resolve().parent.parent.parent
        hermes_md = platform_root / ".hermes.md"
        if hermes_md.exists():
            size = hermes_md.stat().st_size
            assert size < 5000, f".hermes.md is {size} bytes — should be < 5KB"


# ── Skills Configuration ────────────────────────────────────────────────────


@pytest.mark.unit
class TestSkillsConfig:
    @pytest.mark.skipif(
        not (HERMES_HOME / "config.yaml").exists(),
        reason="Hermes config not found",
    )
    def test_no_duplicate_skill_dirs(self):
        """Skills external_dirs should not have duplicate paths."""
        import yaml

        config_path = HERMES_HOME / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        skills_config = config.get("skills", {})
        external_dirs = skills_config.get("external_dirs", [])
        # Resolve all paths to detect duplicates via different representations
        resolved = [str(Path(d).expanduser().resolve()) for d in external_dirs]
        assert len(resolved) == len(set(resolved)), (
            f"Duplicate skill dirs detected: {external_dirs}"
        )

    @pytest.mark.skipif(
        not (HERMES_HOME / "config.yaml").exists(),
        reason="Hermes config not found",
    )
    def test_skill_dirs_exist(self):
        """All configured skill directories should exist on disk."""
        import yaml

        config_path = HERMES_HOME / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        skills_config = config.get("skills", {})
        external_dirs = skills_config.get("external_dirs", [])
        for d in external_dirs:
            p = Path(d).expanduser()
            assert p.exists(), f"Skill dir does not exist: {d}"


# ── Session File Cleanup ────────────────────────────────────────────────────


@pytest.mark.unit
class TestSessionFileHealth:
    def test_session_dir_not_excessive(self):
        """Sessions directory should not have > 5000 JSON files."""
        sessions_dir = HERMES_HOME / "sessions"
        if not sessions_dir.exists():
            pytest.skip("Sessions directory not found")
        count = sum(1 for f in sessions_dir.iterdir() if f.suffix == ".json")
        assert count < 5000, (
            f"Sessions dir has {count} JSON files — run cleanup-sessions.sh"
        )


# ── End-to-End Session Tracking ─────────────────────────────────────────────


@pytest.mark.integration
class TestE2ESessionTracking:
    @skip_no_session_api_access
    def test_full_session_lifecycle(self):
        """Create → list → retrieve → rename → delete: full session lifecycle."""
        import uuid

        title = f"e2e-{uuid.uuid4().hex[:8]}"

        # Create
        created = api_post("/api/sessions", {"title": title})
        assert "session" in created
        sid = created["session"]["id"]

        try:
            # List and find
            listing = api_get("/api/sessions")
            items = listing.get("items", [])
            assert any(s["id"] == sid for s in items), "Session not in list"

            # Retrieve by ID
            fetched = api_get(f"/api/sessions/{sid}")
            assert fetched["session"]["id"] == sid

            # Update title
            new_title = f"e2e-renamed-{uuid.uuid4().hex[:8]}"
            status, updated = api_patch(f"/api/sessions/{sid}", {"title": new_title})
            assert status == 200
            assert updated["session"]["title"] == new_title

            # Delete
            del_status = api_delete(f"/api/sessions/{sid}")
            assert del_status == 200
        except Exception:
            # Cleanup on failure
            api_delete(f"/api/sessions/{sid}")
            raise
