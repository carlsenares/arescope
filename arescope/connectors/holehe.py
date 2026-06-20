"""Holehe — which sites an email is registered on (#4).

Consumes: email. Free, self-hosted. Uses Holehe's library API (trio + httpx).
Holehe enumerates via password-reset flows and does NOT alert the target.

Integration note: Holehe's internals shift between releases (we pin in
pyproject). The whole library call is wrapped so any breakage degrades to a
ConnectorGap rather than failing the scan.
"""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


class HoleheConnector(Connector):
    name = "holehe"
    consumes = {InputType.EMAIL}

    def available(self, cfg: Settings) -> bool:
        return cfg.holehe_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            results = _run_holehe(value)
        except Exception as e:  # import error, API drift, network — all => gap
            raise ConnectorGap(f"holehe run failed: {e}") from e

        signals: list[Signal] = []
        for entry in results:
            if not entry.get("exists"):
                continue
            signals.append(
                Signal(
                    source=self.name,
                    kind="account",
                    locator=entry.get("name", "unknown"),
                    subject_value=value,
                    subject_type=InputType.EMAIL,
                    raw={
                        "domain": entry.get("domain"),
                        "rate_limited": entry.get("rateLimit"),
                        "email_recovery": entry.get("emailrecovery"),
                        "phone_number": entry.get("phoneNumber"),
                    },
                )
            )
        return signals


def _run_holehe(email: str) -> list[dict]:
    """Drive Holehe's async modules and collect per-site result dicts."""
    import httpx
    import trio
    from holehe.core import get_functions, import_submodules

    async def _runmod(module, client, out):
        try:
            await module(email, client, out)
        except Exception:
            pass  # one dead module never sinks the batch

    async def _main() -> list[dict]:
        modules = import_submodules("holehe.modules")
        websites = get_functions(modules)
        out: list[dict] = []
        client = httpx.AsyncClient()
        try:
            async with trio.open_nursery() as nursery:
                for website in websites:
                    nursery.start_soon(_runmod, website, client, out)
        finally:
            await client.aclose()
        return out

    return trio.run(_main)
