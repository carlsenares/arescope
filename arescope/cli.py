"""Local CLI — run a scan synchronously, no Postgres/Redis/Celery needed.

The fastest way to exercise the pipeline on your own identifiers (Phase 1 goal):

    python -m arescope.cli --email you@example.com --username you

Needs ANTHROPIC_API_KEY for the judge/remediation; connectors with no key just
log coverage gaps. Prints a Markdown report; nothing is persisted.
"""

from __future__ import annotations

import argparse

from arescope.pipeline.orchestrator import run_scan
from arescope.pipeline.report import render_markdown
from arescope.schemas import Identifier, InputType


def main() -> None:
    p = argparse.ArgumentParser(description="Run an Arescope self-audit scan locally.")
    p.add_argument("--email", action="append", default=[], help="email you own (repeatable)")
    p.add_argument("--username", action="append", default=[], help="username you own (repeatable)")
    p.add_argument("--ip", action="append", default=[], help="IP you own (repeatable)")
    args = p.parse_args()

    identifiers: list[Identifier] = []
    for e in args.email:
        identifiers.append(Identifier(type=InputType.EMAIL, value=e, ownership_verified=True))
    for u in args.username:
        identifiers.append(Identifier(type=InputType.USERNAME, value=u, ownership_verified=True))
    for ip in args.ip:
        identifiers.append(Identifier(type=InputType.IP, value=ip, ownership_verified=True))

    if not identifiers:
        p.error("provide at least one --email / --username / --ip")

    report = run_scan(identifiers)
    print(render_markdown(report))


if __name__ == "__main__":
    main()
