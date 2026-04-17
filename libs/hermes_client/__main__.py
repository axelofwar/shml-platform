"""CLI entry point for libs.hermes_client.

Usage:
  python3 -m libs.hermes_client dispatch issue 580
  python3 -m libs.hermes_client dispatch issue 580 --project 2 --background --timeout 600
  python3 -m libs.hermes_client dispatch task --title "..." --description "..." --monitor
  python3 -m libs.hermes_client jobs list
  python3 -m libs.hermes_client jobs list --status running
  python3 -m libs.hermes_client jobs tail JOB_ID [--follow]
  python3 -m libs.hermes_client jobs status JOB_ID
  python3 -m libs.hermes_client jobs clean [--days 7]
  python3 -m libs.hermes_client jobs kill JOB_ID
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_dispatch_issue(args: argparse.Namespace) -> int:
    from . import dispatch_issue
    result = dispatch_issue(
        iid=args.iid,
        project_id=args.project,
        background=args.background,
        monitor=not args.no_monitor,
        timeout=args.timeout,
        skills=args.skills.split(",") if args.skills else None,
        worktree=args.worktree,
        session=args.session,
    )
    from ._types import BackgroundJob, DispatchResult
    if isinstance(result, BackgroundJob):
        print(f"Job ID: {result.job_id}")
        return 0
    assert isinstance(result, DispatchResult)
    if result.success:
        print(f"[ok] {result.status_label()} ({result.duration_seconds:.1f}s)")
        return 0
    else:
        print(f"[error] {result.error}", file=sys.stderr)
        return 1


def _cmd_dispatch_task(args: argparse.Namespace) -> int:
    from . import dispatch_task
    from ._types import DispatchTask

    description = args.description or ""
    if args.description_file:
        description = Path(args.description_file).read_text()

    task = DispatchTask(
        task_type=args.task_type,
        title=args.title,
        description=description,
        project_id=args.project,
        gitlab_issue_iid=args.issue_iid,
        skills=args.skills.split(",") if args.skills else [],
        timeout=args.timeout,
    )
    result = dispatch_task(task, background=args.background, monitor=not args.no_monitor)
    from ._types import BackgroundJob, DispatchResult
    if isinstance(result, BackgroundJob):
        print(f"Job ID: {result.job_id}")
        return 0
    assert isinstance(result, DispatchResult)
    return 0 if result.success else 1


def _cmd_jobs_list(args: argparse.Namespace) -> int:
    from . import list_jobs
    jobs = list_jobs(status=args.status)
    if not jobs:
        print("No jobs found.")
        return 0
    fmt = "{:<26} {:<12} {:<12} {}"
    print(fmt.format("JOB ID", "STATUS", "PID", "TITLE"))
    print("-" * 72)
    for job in jobs:
        alive = "●" if job.is_alive() else " "
        print(fmt.format(job.job_id, f"{alive}{job.status.value}", str(job.pid), job.title[:40]))
    return 0


def _cmd_jobs_status(args: argparse.Namespace) -> int:
    from . import get_job_status, get_job
    job = get_job(args.job_id)
    if job is None:
        print(f"Job {args.job_id} not found.", file=sys.stderr)
        return 1
    status = get_job_status(args.job_id)
    print(f"Job:     {job.job_id}")
    print(f"Title:   {job.title}")
    print(f"Status:  {status.value if status else 'unknown'}")
    print(f"PID:     {job.pid} ({'alive' if job.is_alive() else 'dead'})")
    print(f"Started: {job.started_at}")
    print(f"Log:     {job.log_file}")
    if job.result:
        print(f"Error:   {job.result.error or '(none)'}")
    return 0


def _cmd_jobs_tail(args: argparse.Namespace) -> int:
    from . import tail_job
    tail_job(args.job_id, n=args.lines, follow=args.follow)
    return 0


def _cmd_jobs_watch(args: argparse.Namespace) -> int:
    from ._session_watch import watch_session
    watch_session(
        session_id=args.session_id or None,
        job_id=args.job_id or None,
        poll_interval=args.interval,
        stop_on_job_done=True,
    )
    return 0


def _cmd_jobs_clean(args: argparse.Namespace) -> int:
    from . import cleanup_old_jobs
    removed = cleanup_old_jobs(max_age_days=args.days)
    print(f"Removed {removed} job state file(s) older than {args.days} days.")
    return 0


def _cmd_jobs_kill(args: argparse.Namespace) -> int:
    import signal
    from . import JOBS_DIR
    state_file = JOBS_DIR / args.job_id / "state.json"
    if not state_file.exists():
        print(f"Job {args.job_id} not found.")
        return 1
    import json
    state = json.loads(state_file.read_text())
    pid = state.get("pid")
    if not pid:
        # PID not in state — search by command line
        import subprocess
        r = subprocess.run(
            ["pgrep", "-f", args.job_id],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in r.stdout.split() if p.strip().isdigit()]
        if not pids:
            print(f"No running process found for job {args.job_id}.")
            return 1
        pid = pids[0]
    try:
        import os
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid} (job {args.job_id}).")
    except ProcessLookupError:
        print(f"PID {pid} already dead.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m libs.hermes_client",
        description="Hermes dispatch client — assign tasks to the Hermes agent",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- dispatch ---
    p_dispatch = sub.add_parser("dispatch", help="Dispatch a task to Hermes")
    dsub = p_dispatch.add_subparsers(dest="dispatch_type", required=True)

    # dispatch issue
    p_issue = dsub.add_parser("issue", help="Dispatch Hermes to a GitLab issue")
    p_issue.add_argument("iid", type=int, help="GitLab issue IID")
    p_issue.add_argument("--project", type=int, default=2)
    p_issue.add_argument("--background", action="store_true")
    p_issue.add_argument("--no-monitor", action="store_true", help="Do not stream output")
    p_issue.add_argument("--timeout", type=int, default=600)
    p_issue.add_argument("--skills", default="", help="Comma-separated skill names")
    p_issue.add_argument("--worktree", action="store_true")
    p_issue.add_argument("--session", default=None,
                         help="Session: 'last' for --continue, or SESSION_ID for --resume")
    p_issue.set_defaults(func=_cmd_dispatch_issue)

    # dispatch task
    p_task = dsub.add_parser("task", help="Dispatch a manual task to Hermes")
    p_task.add_argument("--title", required=True)
    p_task.add_argument("--description", default="")
    p_task.add_argument("--description-file", help="Read description from this file")
    p_task.add_argument("--task-type", default="issue", choices=["issue", "incident", "manual"])
    p_task.add_argument("--project", type=int, default=2)
    p_task.add_argument("--issue-iid", type=int, default=None)
    p_task.add_argument("--skills", default="")
    p_task.add_argument("--timeout", type=int, default=600)
    p_task.add_argument("--background", action="store_true")
    p_task.add_argument("--no-monitor", action="store_true")
    p_task.set_defaults(func=_cmd_dispatch_task)

    # --- jobs ---
    p_jobs = sub.add_parser("jobs", help="Manage background Hermes jobs")
    jsub = p_jobs.add_subparsers(dest="jobs_cmd", required=True)

    p_jlist = jsub.add_parser("list", help="List all jobs")
    p_jlist.add_argument("--status", default=None,
                         choices=["pending", "running", "completed", "failed",
                                  "interrupted", "timeout"])
    p_jlist.set_defaults(func=_cmd_jobs_list)

    p_jstatus = jsub.add_parser("status", help="Show detail for one job")
    p_jstatus.add_argument("job_id")
    p_jstatus.set_defaults(func=_cmd_jobs_status)

    p_jtail = jsub.add_parser("tail", help="Tail a job's log file")
    p_jtail.add_argument("job_id")
    p_jtail.add_argument("-n", "--lines", type=int, default=50)
    p_jtail.add_argument("-f", "--follow", action="store_true")
    p_jtail.set_defaults(func=_cmd_jobs_tail)

    p_jwatch = jsub.add_parser("watch", help="Live session viewer (Rich markdown, tool calls)")
    p_jwatch.add_argument("job_id", nargs="?", default=None,
                          help="Job ID to find session for (auto-detects newest if omitted)")
    p_jwatch.add_argument("--session-id", default=None,
                          help="Explicit Hermes session ID to watch")
    p_jwatch.add_argument("--interval", type=float, default=0.8,
                          help="Poll interval in seconds (default: 0.8)")
    p_jwatch.set_defaults(func=_cmd_jobs_watch)

    p_jclean = jsub.add_parser("clean", help="Remove old job state files")
    p_jclean.add_argument("--days", type=int, default=7)
    p_jclean.set_defaults(func=_cmd_jobs_clean)

    p_jkill = jsub.add_parser("kill", help="Send SIGTERM to a running job")
    p_jkill.add_argument("job_id", help="Job ID to kill")
    p_jkill.set_defaults(func=_cmd_jobs_kill)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
