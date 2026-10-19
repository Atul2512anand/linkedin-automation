from __future__ import annotations

import argparse
import sys

from . import __version__
from .browser import SafetyStop, browser_session, is_logged_in, save_screenshot
from .config import CONFIG_PATH, ROOT, load_config, project_path
from .db import connect, save_jobs
from .jobs import (
    build_jobs_search_url,
    collect_jobs,
    export_jobs,
    list_jobs,
    open_job,
    prep_jobs,
    run_job_batch,
)
from .outreach import (
    CONTACT_STATUSES,
    build_people_search_url,
    discover_contacts,
    import_contacts,
    inspect_queue,
    mark_contact,
    preview_queue,
    remaining_allowance,
    run_batch,
    send_connections,
    send_followups,
    within_working_hours,
)
from .profile import save_profile, scan_profile, update_config_from_profile
from .util import print_table

JOB_STATUSES = {
    "new",
    "shortlisted",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "archived",
}


def _require_login(context) -> bool:
    if is_logged_in(context):
        return True
    print("Not signed in to LinkedIn. Run:  run.cmd login")
    return False


def cmd_login(args, cfg, con) -> int:
    with browser_session(cfg) as (page, context):
        if is_logged_in(context):
            print("Already signed in (LinkedIn session cookie found).")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        print("A Chrome window is open. Sign in to LinkedIn there.")
        print("This tool never asks for or stores your password.")
        if not is_logged_in(context):
            input("Press Enter here after you are signed in... ")
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        if is_logged_in(context):
            print("Login confirmed.")
            return 0
        print("Could not confirm the session. Please try again.")
        return 2


def cmd_doctor(args, cfg, con) -> int:
    print(f"LinkedIn automation {__version__}")
    print(f"Project:        {ROOT}")
    print(f"Config:         {CONFIG_PATH}")
    print(f"Browser channel:{cfg['browser']['channel']}")
    print(f"Profile dir:    {project_path(cfg['browser']['profile_dir'])}")
    print(f"Database:       {project_path(cfg['storage']['database'])}")
    print(f"Outreach gate:  enabled={cfg['outreach']['enabled']} dry_run={cfg['outreach']['dry_run']}")

    jobs = con.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    contacts = con.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"]
    print(f"Stored jobs:    {jobs}")
    print(f"Contacts:       {contacts}")

    try:
        with browser_session(cfg, headless=True) as (page, context):
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=45000)
            print(f"Browser OK:     {page.title()}")
            print(f"Logged in:      {is_logged_in(context)}")
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash
        print(f"Browser check failed: {exc}")
        print("Try: .venv\\Scripts\\python -m playwright install chromium")
        return 2
    return 0


def cmd_jobs_collect(args, cfg, con) -> int:
    url = args.url or (
        build_jobs_search_url(args.query, args.location or "Japan", args.level)
        if args.query
        else ""
    )
    if not url:
        print("Pass --url or --query (with optional --location and --level).")
        return 2

    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        jobs = collect_jobs(page, cfg, url)
        new_count = save_jobs(con, jobs)
        if not jobs:
            print(f"No jobs found. Screenshot: {save_screenshot(page, cfg, 'jobs_collect_empty')}")
    print(f"Collected {len(jobs)} jobs ({new_count} new, {len(jobs) - new_count} duplicates).")
    return 0


def cmd_jobs_list(args, cfg, con) -> int:
    list_jobs(con, args.status, args.limit)
    return 0


def cmd_jobs_status(args, cfg, con) -> int:
    if args.status not in JOB_STATUSES:
        print(f"Invalid status. Choose from: {', '.join(sorted(JOB_STATUSES))}")
        return 2
    cursor = con.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE job_id = ?",
        (args.status, args.job_id),
    )
    con.commit()
    if not cursor.rowcount:
        print(f"No job with id {args.job_id}.")
        return 2
    print(f"Job {args.job_id} -> {args.status}")
    return 0


def cmd_jobs_export(args, cfg, con) -> int:
    path = export_jobs(con, cfg, args.format, args.out)
    print(f"Exported to {path}")
    return 0


def cmd_jobs_open(args, cfg, con) -> int:
    row = con.execute("SELECT url FROM jobs WHERE job_id = ?", (args.job_id,)).fetchone()
    if not row or not row["url"]:
        print(f"No job with id {args.job_id}.")
        return 2
    open_job(row["url"])
    print(f"Opened {row['url']}")
    return 0


def cmd_jobs_prep(args, cfg, con) -> int:
    if args.fetch:
        with browser_session(cfg) as (page, context):
            if not _require_login(context):
                return 2
            paths = prep_jobs(
                con, cfg, page, args.limit, args.status, args.id, fetch=True
            )
    else:
        paths = prep_jobs(con, cfg, None, args.limit, args.status, args.id, fetch=False)

    if paths:
        print(f"Wrote {len(paths)} application pack(s) to {paths[0].parent}")
    return 0


def cmd_jobs_batch(args, cfg, con) -> int:
    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        summary = run_job_batch(con, cfg, page, args.limit, args.status, args.keep_open)
    if summary is None:
        return 0
    print(f"Logged {summary['applied']} application(s), skipped {summary['skipped']}.")
    return 0


def cmd_contacts_import(args, cfg, con) -> int:
    imported, skipped = import_contacts(con, args.file)
    print(f"Imported {imported} contacts ({skipped} skipped).")
    return 0


def cmd_contacts_discover(args, cfg, con) -> int:
    url = args.url
    if not url:
        try:
            url = build_people_search_url(args.query or "", args.location, args.geo)
        except ValueError as exc:
            print(exc)
            return 2

    print(f"Search: {url}")
    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        added, seen = discover_contacts(con, cfg, page, url, args.limit)
    print(f"Added {added} new contacts ({seen} profiles seen).")
    if added:
        print("Next: run 'outreach batch --limit 10'")
    return 0


def cmd_contacts_list(args, cfg, con) -> int:
    query = "SELECT id, name, company, role, status, last_error FROM contacts"
    params: tuple = ()
    if args.status:
        query += " WHERE status = ?"
        params = (args.status,)
    query += " ORDER BY id LIMIT ?"
    params += (args.limit,)
    rows = con.execute(query, params).fetchall()
    print_table(rows, ["id", "name", "company", "role", "status", "last_error"], max_width=30)
    return 0


def cmd_outreach_preview(args, cfg, con) -> int:
    preview_queue(con, cfg, args.limit)
    return 0


def cmd_outreach_inspect(args, cfg, con) -> int:
    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        inspect_queue(con, cfg, page, args.limit, apply=args.apply)
    return 0


def _send_preflight(cfg, con, kind: str, limit: int | None) -> int | None:
    """Return the allowed batch size, or None when sending must not start."""
    outreach = cfg["outreach"]
    if not outreach["enabled"]:
        print("Sending is disabled: set outreach.enabled to true in config.yaml.")
        return None
    if outreach["dry_run"]:
        print("Sending is in dry-run mode: set outreach.dry_run to false in config.yaml.")
        return None
    if not within_working_hours(cfg):
        start, end = outreach.get("working_hours", [0, 24])
        print(f"Outside working hours ({start}:00-{end}:00). Adjust working_hours in config.yaml.")
        return None

    daily_left, weekly_left, daily_used, weekly_used = remaining_allowance(con, cfg, kind)
    print(
        f"Cap check: {daily_used}/{outreach['daily_cap']} today, "
        f"{weekly_used}/{outreach['weekly_cap']} this week."
    )
    if daily_left <= 0 or weekly_left <= 0:
        print("Daily or weekly cap reached. Nothing sent.")
        return None
    if limit is not None:
        return min(limit, daily_left, weekly_left)
    return min(daily_left, weekly_left)


def cmd_outreach_send(args, cfg, con) -> int:
    if not args.confirm:
        print("Refusing to send without --confirm. Run 'outreach preview' first.")
        return 2
    allowed = _send_preflight(cfg, con, "connect", args.limit)
    if allowed is None:
        return 2
    if isinstance(allowed, int) and allowed <= 0:
        return 2

    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        summary = send_connections(con, cfg, page, allowed)

    print(
        "Done: "
        f"{summary['sent']} sent, {summary['pending']} pending, "
        f"{summary['connected']} already connected, {summary['failed']} failed."
    )
    return 0


def cmd_outreach_batch(args, cfg, con) -> int:
    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        summary = run_batch(con, cfg, page, args.limit, args.keep_open)
    if summary is None:
        return 0
    print(
        "Reviewed: "
        f"{summary['sent']} sent, {summary['connected']} already connected, "
        f"{summary['not_sent']} still queued, {summary['unknown']} unknown."
    )
    return 0


def cmd_outreach_message(args, cfg, con) -> int:
    if not args.confirm:
        print("Refusing to send without --confirm.")
        return 2
    allowed = _send_preflight(cfg, con, "message", args.limit)
    if allowed is None:
        return 2
    if isinstance(allowed, int) and allowed <= 0:
        return 2

    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        summary = send_followups(con, cfg, page, allowed)

    print(
        "Done: "
        f"{summary['sent']} sent, {summary['skipped']} skipped, "
        f"{summary['failed']} failed."
    )
    return 0


def cmd_outreach_mark(args, cfg, con) -> int:
    if mark_contact(con, args.id, args.status):
        print(f"Contact {args.id} -> {args.status}")
        return 0
    return 2


def cmd_profile_scan(args, cfg, con) -> int:
    with browser_session(cfg) as (page, context):
        if not _require_login(context):
            return 2
        profile = scan_profile(page, cfg, args.url)

    json_path, md_path = save_profile(profile, cfg)
    if args.update_config:
        config_path = update_config_from_profile(profile)
        print(f"Updated profile fields in {config_path}")

    skills = profile.get("skills") or []
    print(f"Scanned: {profile.get('name') or '(name not found)'}")
    print(f"Headline: {profile.get('headline') or '-'}")
    print(f"Location: {profile.get('location') or '-'}")
    print(f"Skills captured: {len(skills)}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    return 0


def cmd_stats(args, cfg, con) -> int:
    print("Jobs by status")
    print_table(
        con.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY count DESC").fetchall(),
        ["status", "count"],
    )
    print("\nContacts by status")
    print_table(
        con.execute(
            "SELECT status, COUNT(*) AS count FROM contacts GROUP BY status ORDER BY count DESC"
        ).fetchall(),
        ["status", "count"],
    )
    print("\nActions")
    print_table(
        con.execute(
            "SELECT kind, result, COUNT(*) AS count FROM actions GROUP BY kind, result ORDER BY kind, result"
        ).fetchall(),
        ["kind", "result", "count"],
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la",
        description="Local LinkedIn job tracker and assisted outreach.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="Open LinkedIn and save a local browser session")
    login.set_defaults(func=cmd_login)

    doctor = sub.add_parser("doctor", help="Check config, database, and browser")
    doctor.set_defaults(func=cmd_doctor)

    stats = sub.add_parser("stats", help="Show stored job/contact/action totals")
    stats.set_defaults(func=cmd_stats)

    profile = sub.add_parser("profile", help="Your LinkedIn profile")
    profile_sub = profile.add_subparsers(dest="profile_command")

    profile_scan = profile_sub.add_parser(
        "scan", help="Scan your own profile and save it locally"
    )
    profile_scan.add_argument(
        "--url", help="Profile URL (default: profile.linkedin from config.yaml)"
    )
    profile_scan.add_argument(
        "--update-config",
        action="store_true",
        help="Refresh name/headline/location/email in config.yaml",
    )
    profile_scan.set_defaults(func=cmd_profile_scan)

    jobs = sub.add_parser("jobs", help="Job tracker commands")
    jobs_sub = jobs.add_subparsers(dest="jobs_command")

    collect = jobs_sub.add_parser("collect", help="Collect jobs from a LinkedIn search URL")
    collect.add_argument("--url", help="Full LinkedIn jobs search URL")
    collect.add_argument("--query", help="Search keywords, e.g. 'cybersecurity analyst'")
    collect.add_argument("--location", default="", help="Location, e.g. Japan")
    collect.add_argument(
        "--level",
        choices=["", "internship", "entry", "internship+entry"],
        default="",
        help="Optional LinkedIn experience filter",
    )
    collect.set_defaults(func=cmd_jobs_collect)

    jobs_list = jobs_sub.add_parser("list", help="List stored jobs")
    jobs_list.add_argument("--status", choices=sorted(JOB_STATUSES))
    jobs_list.add_argument("--limit", type=int, default=25)
    jobs_list.set_defaults(func=cmd_jobs_list)

    job_status = jobs_sub.add_parser("status", help="Update a job status")
    job_status.add_argument("job_id")
    job_status.add_argument("status", choices=sorted(JOB_STATUSES))
    job_status.set_defaults(func=cmd_jobs_status)

    job_export = jobs_sub.add_parser("export", help="Export jobs to CSV or JSON")
    job_export.add_argument("--format", choices=["csv", "json"], default="csv")
    job_export.add_argument("--out", help="Output path (default: data/exports/...)")
    job_export.set_defaults(func=cmd_jobs_export)

    job_open = jobs_sub.add_parser("open", help="Open a stored job in the browser")
    job_open.add_argument("job_id")
    job_open.set_defaults(func=cmd_jobs_open)

    job_prep = jobs_sub.add_parser("prep", help="Generate an application pack per job")
    job_prep.add_argument("--limit", type=int, default=5)
    job_prep.add_argument("--status", default="", help="Filter by job status")
    job_prep.add_argument("--id", default="", help="Job id, or comma-separated ids")
    job_prep.add_argument(
        "--fetch",
        action="store_true",
        help="Open each posting to pull its description for keywords",
    )
    job_prep.set_defaults(func=cmd_jobs_prep)

    job_batch = jobs_sub.add_parser(
        "batch", help="Open shortlisted jobs in tabs for manual applications"
    )
    job_batch.add_argument("--limit", type=int, default=10)
    job_batch.add_argument("--status", default="shortlisted")
    job_batch.add_argument(
        "--keep-open", action="store_true", help="Leave tabs open after logging"
    )
    job_batch.set_defaults(func=cmd_jobs_batch)

    contacts = sub.add_parser("contacts", help="Outreach contact commands")
    contacts_sub = contacts.add_subparsers(dest="contacts_command")

    contacts_discover = contacts_sub.add_parser(
        "discover", help="Extract profiles from LinkedIn people search"
    )
    contacts_discover.add_argument("--url", help="Full LinkedIn people search URL")
    contacts_discover.add_argument("--query", help="Search keywords, e.g. 'technical recruiter'")
    contacts_discover.add_argument(
        "--location", default="", help="Country filter, e.g. japan, india, united states"
    )
    contacts_discover.add_argument("--geo", default="", help="LinkedIn geo ID override")
    contacts_discover.add_argument("--limit", type=int, default=10)
    contacts_discover.set_defaults(func=cmd_contacts_discover)

    contacts_import = contacts_sub.add_parser("import", help="Import contacts from CSV")
    contacts_import.add_argument("file", help="CSV with profile_url,name,company,role,note")
    contacts_import.set_defaults(func=cmd_contacts_import)

    contacts_list = contacts_sub.add_parser("list", help="List contacts")
    contacts_list.add_argument("--status", choices=sorted(CONTACT_STATUSES))
    contacts_list.add_argument("--limit", type=int, default=50)
    contacts_list.set_defaults(func=cmd_contacts_list)

    outreach = sub.add_parser("outreach", help="Assisted outreach commands")
    outreach_sub = outreach.add_subparsers(dest="outreach_command")

    preview = outreach_sub.add_parser("preview", help="Preview queued messages")
    preview.add_argument("--limit", type=int, default=20)
    preview.set_defaults(func=cmd_outreach_preview)

    inspect = outreach_sub.add_parser("inspect", help="Check each profile's Connect/Message state")
    inspect.add_argument("--limit", type=int, default=5)
    inspect.add_argument(
        "--apply",
        action="store_true",
        help="Update contact statuses from the observed state (pending -> sent)",
    )
    inspect.set_defaults(func=cmd_outreach_inspect)

    batch = outreach_sub.add_parser(
        "batch", help="Open queued profiles in tabs for manual Connect clicks"
    )
    batch.add_argument("--limit", type=int, default=10)
    batch.add_argument("--keep-open", action="store_true", help="Leave tabs open after review")
    batch.set_defaults(func=cmd_outreach_batch)

    send = outreach_sub.add_parser("send", help="Send queued connection requests")
    send.add_argument("--limit", type=int)
    send.add_argument("--confirm", action="store_true", help="Required to actually click")
    send.set_defaults(func=cmd_outreach_send)

    message = outreach_sub.add_parser("message", help="Send follow-ups to connected contacts")
    message.add_argument("--limit", type=int)
    message.add_argument("--confirm", action="store_true", help="Required to actually click")
    message.set_defaults(func=cmd_outreach_message)

    mark = outreach_sub.add_parser("mark", help="Manually set a contact status")
    mark.add_argument("id", type=int)
    mark.add_argument("status", choices=sorted(CONTACT_STATUSES))
    mark.set_defaults(func=cmd_outreach_mark)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    cfg = load_config()
    con = connect(cfg)
    try:
        return args.func(args, cfg, con) or 0
    except SafetyStop as exc:
        print(f"Stopped: {exc}")
        return 3
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        con.close()
