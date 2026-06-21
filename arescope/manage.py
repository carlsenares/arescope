"""Operational CLI for the persistent app (DB + accounts).

Separate from cli.py (which runs a stateless local scan with no DB).

    python -m arescope.manage init-db                 # create tables (dev)
    python -m arescope.manage migrate                 # add new tables/columns to an existing DB
    python -m arescope.manage create-admin            # seed admin from ARESCOPE_ADMIN_* env
    python -m arescope.manage create-admin -e a@b.c -u admin -p secret  # explicit
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
        else:
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN can_scan BOOLEAN NOT NULL DEFAULT 0"))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arescope.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create database tables")
    sub.add_parser("migrate", help="add new tables/columns to an existing DB (idempotent)")

    ca = sub.add_parser("create-admin", help="seed an admin account")
    ca.add_argument("-e", "--email")
    ca.add_argument("-u", "--username")
    ca.add_argument("-p", "--password")

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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
