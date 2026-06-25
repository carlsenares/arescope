"""Operational CLI for the persistent app (DB + accounts).

Separate from cli.py (which runs a stateless local scan with no DB).

    python -m arescope.manage init-db                 # create tables (dev)
    python -m arescope.manage migrate                 # add new tables/columns to an existing DB
    python -m arescope.manage create-admin            # seed admin from ARESCOPE_ADMIN_* env
    python -m arescope.manage create-admin -e a@b.c -u admin -p secret  # explicit
    python -m arescope.manage eval-coverage [scan_id]  # what each connector returned (map)
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from arescope.auth import AuthError, create_user
from arescope.config import get_settings
from arescope.db.session import _engine, init_db


def _migrate() -> int:
    """Additive migration for an existing DB: new tables (create_all) + new columns.

    Idempotent. create_all() adds the login_tokens table; the ALTER adds users.can_scan
    if an older DB predates it. Postgres supports IF NOT EXISTS; on other dialects we
    attempt the ALTER and treat 'already exists' as success.
    """
    init_db()  # creates any wholly-new tables (e.g. login_tokens)
    dialect = _engine.dialect.name
    with _engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS can_scan BOOLEAN NOT NULL DEFAULT false")
            )
            conn.execute(
                text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS options JSON NOT NULL DEFAULT '{}'")
            )
            conn.execute(text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS name VARCHAR"))
            conn.execute(text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS analysis JSON"))
            conn.execute(text("ALTER TABLE findings ADD COLUMN IF NOT EXISTS problem TEXT"))
        else:
            for ddl in (
                "ALTER TABLE users ADD COLUMN can_scan BOOLEAN NOT NULL DEFAULT 0",
                "ALTER TABLE scans ADD COLUMN options JSON NOT NULL DEFAULT '{}'",
                "ALTER TABLE scans ADD COLUMN name VARCHAR",
                "ALTER TABLE scans ADD COLUMN analysis JSON",
                "ALTER TABLE findings ADD COLUMN problem TEXT",
            ):
                try:
                    conn.execute(text(ddl))
                except Exception as e:  # noqa: BLE001 — column likely already present
                    if "duplicate" not in str(e).lower() and "exist" not in str(e).lower():
                        raise
    print("Migration complete.")
    return 0


def _create_admin(args: argparse.Namespace) -> int:
    cfg = get_settings()
    email = args.email or cfg.admin_email
    username = args.username or cfg.admin_username
    password = args.password or cfg.admin_password
    if not (email and username and password):
        print(
            "Missing admin credentials. Pass -e/-u/-p or set "
            "ARESCOPE_ADMIN_EMAIL / _USERNAME / _PASSWORD.",
            file=sys.stderr,
        )
        return 2
    try:
        uid = create_user(email, username, password, is_admin=True, email_verified=True)
    except AuthError as e:
        print(f"Could not create admin: {e}", file=sys.stderr)
        return 1
    print(f"Admin created: {username} <{email}>  (id={uid})")
    return 0


def _eval_coverage(args: argparse.Namespace) -> int:
    """Print what each connector actually returned for a map scan — the data needed to
    weigh sources against each other (e.g. is Instagram or LinkedIn worth the credits?).
    Defaults to the latest map scan. Run where the DB is reachable (e.g. inside the api
    container) and paste the output.
    """
    from collections import Counter

    from sqlalchemy import select

    from arescope.db import models
    from arescope.db.session import session_scope

    with session_scope() as s:
        scan_id = args.scan_id
        if not scan_id:
            rows = s.execute(
                select(models.Scan.id, models.Scan.options).order_by(models.Scan.started_at.desc())
            ).all()
            scan_id = next((sid for sid, opts in rows if (opts or {}).get("mode") == "map"), None)
            if scan_id is None and rows:
                scan_id = rows[0][0]
        if not scan_id:
            print("No scans found.", file=sys.stderr)
            return 1

        sigs = s.query(models.Signal).filter(models.Signal.scan_id == scan_id).all()
        by_source: dict[str, list] = {}
        for sig in sigs:
            by_source.setdefault(sig.source, []).append(sig)

        print(f"Coverage for scan {scan_id} — {len(sigs)} signals from {len(by_source)} sources\n")
        for source in sorted(by_source):
            group = by_source[source]
            kinds = dict(Counter(sig.kind for sig in group))
            print(f"## {source}  ({len(group)} signals: {kinds})")
            for sig in group:
                raw = sig.raw or {}
                if sig.kind == "account":
                    posts = raw.get("recent_posts") or []
                    print(f"   platform={raw.get('domain')} name={raw.get('display_name')!r} "
                          f"followers={raw.get('followers')} posts={len(posts)}")
                    for p in posts[:3]:
                        print(f"      · {str(p)[:90]}")
                elif sig.kind == "identity_attribute":
                    print(f"   {raw.get('attribute')}={str(raw.get('value'))[:90]!r} "
                          f"({raw.get('platform')})")
                elif sig.kind == "web_mention":
                    print(f"   mention {raw.get('domain') or raw.get('url')}: {raw.get('title')!r}")
            print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arescope.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create database tables")
    sub.add_parser("migrate", help="add new tables/columns to an existing DB (idempotent)")

    ca = sub.add_parser("create-admin", help="seed an admin account")
    ca.add_argument("-e", "--email")
    ca.add_argument("-u", "--username")
    ca.add_argument("-p", "--password")

    ec = sub.add_parser("eval-coverage", help="print per-connector coverage for a map scan")
    ec.add_argument("scan_id", nargs="?", default=None, help="scan id (default: latest map)")

    args = parser.parse_args(argv)
    if args.cmd == "init-db":
        init_db()
        print("Tables created.")
        return 0
    if args.cmd == "migrate":
        return _migrate()
    if args.cmd == "create-admin":
        init_db()  # ensure tables exist before seeding
        return _create_admin(args)
    if args.cmd == "eval-coverage":
        return _eval_coverage(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
