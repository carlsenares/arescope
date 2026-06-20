"""Operational CLI for the persistent app (DB + accounts).

Separate from cli.py (which runs a stateless local scan with no DB).

    python -m arescope.manage init-db                 # create tables (dev)
    python -m arescope.manage create-admin            # seed admin from ARESCOPE_ADMIN_* env
    python -m arescope.manage create-admin -e a@b.c -u admin -p secret  # explicit
"""

from __future__ import annotations

import argparse
import sys

from arescope.auth import AuthError, create_user
from arescope.config import get_settings
from arescope.db.session import init_db


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

    ca = sub.add_parser("create-admin", help="seed an admin account")
    ca.add_argument("-e", "--email")
    ca.add_argument("-u", "--username")
    ca.add_argument("-p", "--password")

    args = parser.parse_args(argv)
    if args.cmd == "init-db":
        init_db()
        print("Tables created.")
        return 0
    if args.cmd == "create-admin":
        init_db()  # ensure tables exist before seeding
        return _create_admin(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
