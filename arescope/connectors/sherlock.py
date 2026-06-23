"""Sherlock — username presence across sites (#4, #8), a cross-check for Maigret.

Consumes: username. Free, self-hosted. Driven via the `sherlock` CLI (more stable
than its internals). Only "available" when the CLI is on PATH, so an environment
without it simply skips Sherlock (no coverage-gap noise) — Maigret remains the
primary username source. Emits one `account` Signal per found site (same kind/shape
as Maigret/Holehe, so cross-source agreement collapses to one Evidence).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_FOUND = re.compile(r"\[\+\]\s*([^:]+):\s*(https?://\S+)")


class SherlockConnector(Connector):
    name = "sherlock"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.sherlock_enabled and shutil.which("sherlock") is not None

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                proc = subprocess.run(
                    ["sherlock", value, "--print-found", "--no-color", "--timeout", "10"],
                    cwd=tmp, capture_output=True, text=True, timeout=180,
                )
            except FileNotFoundError as e:
                raise ConnectorGap("sherlock CLI not found on PATH") from e
            except subprocess.TimeoutExpired as e:
                raise ConnectorGap("sherlock timed out") from e

        signals: list[Signal] = []
        seen: set[str] = set()
        for line in proc.stdout.splitlines():
            m = _FOUND.search(line)
            if not m:
                continue
            site, url = m.group(1).strip(), m.group(2).strip()
            domain = (urlparse(url).netloc or site).lower()
            if domain in seen:
                continue
            seen.add(domain)
            signals.append(Signal(
                source=self.name, kind="account", locator=site,
                subject_value=value, subject_type=InputType.USERNAME,
                raw={"url": url, "domain": domain},
            ))
        return signals
