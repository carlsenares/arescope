"""Self-hosted phone tools (input: phone).

- Ignorant   — the Holehe-for-phone: which sites a number is registered on
               (Amazon / Instagram / Snapchat). Library (trio), graceful on absence.
- PhoneInfoga — phone footprinting via the `phoneinfoga` Go CLI; only available when
               the binary is on PATH (otherwise simply skipped, no gap noise).

Both emit alongside IPQS/NumVerify (phone_sources.py) and LeakCheck(type=phone).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


def _split_phone(value: str) -> tuple[str, str]:
    """'+1 800-726-7864' -> ('8007267864', '1'). Uses phonenumbers when present."""
    import phonenumbers
    p = phonenumbers.parse(value if value.strip().startswith("+") else "+" + value.strip(), None)
    return str(p.national_number), str(p.country_code)


class IgnorantConnector(Connector):
    name = "ignorant"
    consumes = {InputType.PHONE}

    def available(self, cfg: Settings) -> bool:
        return (
            cfg.ignorant_enabled
            and importlib.util.find_spec("ignorant") is not None
            and importlib.util.find_spec("phonenumbers") is not None
        )

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            phone, cc = _split_phone(value)
            results = _run_ignorant(phone, cc)
        except Exception as e:  # parse error, import drift, network — all => gap
            raise ConnectorGap(f"ignorant run failed: {e}") from e

        signals: list[Signal] = []
        for entry in results:
            if not entry.get("exists"):
                continue
            signals.append(Signal(
                source=self.name, kind="account",
                locator=entry.get("name", "unknown"),
                subject_value=value, subject_type=InputType.PHONE,
                raw={"domain": entry.get("domain"), "rate_limited": entry.get("rateLimit")},
            ))
        return signals


def _run_ignorant(phone: str, country_code: str) -> list[dict]:
    import httpx
    import trio
    from ignorant.core import get_functions, import_submodules

    async def _runmod(module, client, out):
        try:
            await module(phone, country_code, client, out)
        except Exception:
            pass  # one dead module never sinks the batch

    async def _main() -> list[dict]:
        websites = get_functions(import_submodules("ignorant.modules"))
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


class PhoneInfogaConnector(Connector):
    name = "phoneinfoga"
    consumes = {InputType.PHONE}

    def available(self, cfg: Settings) -> bool:
        # Go binary — only available when installed. Absent => silently skipped.
        return shutil.which("phoneinfoga") is not None

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        num = value if value.strip().startswith("+") else "+" + value.strip()
        try:
            proc = subprocess.run(
                ["phoneinfoga", "scan", "-n", num],
                capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError as e:
            raise ConnectorGap("phoneinfoga CLI not found on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise ConnectorGap("phoneinfoga timed out") from e
        out = (proc.stdout or "").strip()
        if not out:
            return []
        carrier = _grep(out, "Carrier")
        line_type = _grep(out, "Line type") or _grep(out, "Type")
        return [Signal(
            source=self.name, kind="phone_meta", locator=value,
            subject_value=value, subject_type=InputType.PHONE,
            raw={"carrier": carrier, "line_type": line_type, "raw_scan": out[:2000]},
        )]


def _grep(text: str, label: str) -> str | None:
    for line in text.splitlines():
        if label.lower() in line.lower() and ":" in line:
            return line.split(":", 1)[1].strip() or None
    return None
