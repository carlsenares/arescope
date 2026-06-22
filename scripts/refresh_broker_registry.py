#!/usr/bin/env python3
"""Generate the bundled people-search broker list the name connector enumerates.

Why this exists (docs/DEEP_SEARCH_PLAN.md, 2026-06-22 decision): every *paid*
people-search / removal API that confirms an individual's listing is walled to a
non-US individual (Enformion/Endato need a US phone + company, PDL needs a work
email, Optery/Onerep are B2B apply-only). But the **removal track** — "here are the
people-search sites that list people, and the direct opt-out link for each" — does
NOT need a paid lookup. The opt-out catalog is public and stable.

So the name connector's free provider enumerates a *curated* set of the consumer
people-search brokers a person is most likely to appear on (the ones users actually
want removed), each with its opt-out URL. We then cross-reference California's public
**Data Broker Registry** (live since the Delete Act; ~580 registered brokers) to
stamp an authoritative `ca_registered` flag — a real provenance signal, not a claim
that the user is personally listed.

This is honest by construction: it is *enumeration*, not confirmation. The connector
marks every signal `confirmed: false`; the report frames it as "major brokers + how
to remove yourself", never "you are listed here".

Usage:
    python scripts/refresh_broker_registry.py                 # download the CA CSV
    python scripts/refresh_broker_registry.py --registry-csv path/to/registry.csv

Writes arescope/connectors/data/people_search_brokers.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

CA_REGISTRY_CSV_URL = "https://cppa.ca.gov/data_broker_registry/registry.csv"
OUT = Path(__file__).resolve().parent.parent / "arescope" / "connectors" / "data" / "people_search_brokers.json"

# Curated consumer people-search brokers — the sites a real person is most likely
# listed on and most wants removed. Opt-out URLs verified against each broker's
# public removal page (≈2025/2026; re-verify periodically — they drift). This is the
# same catalog the managed-removal services (DeleteMe/Optery) work from, minus the
# paid "we confirmed your individual listing" step.
CURATED: list[dict] = [
    {"broker": "Spokeo", "domain": "spokeo.com", "opt_out_url": "https://www.spokeo.com/optout"},
    {"broker": "Whitepages", "domain": "whitepages.com", "opt_out_url": "https://www.whitepages.com/suppression-requests"},
    {"broker": "BeenVerified", "domain": "beenverified.com", "opt_out_url": "https://www.beenverified.com/app/optout/search"},
    {"broker": "Intelius", "domain": "intelius.com", "opt_out_url": "https://www.intelius.com/opt-out/"},
    {"broker": "PeopleFinders", "domain": "peoplefinders.com", "opt_out_url": "https://www.peoplefinders.com/opt-out"},
    {"broker": "TruePeopleSearch", "domain": "truepeoplesearch.com", "opt_out_url": "https://www.truepeoplesearch.com/removal"},
    {"broker": "MyLife", "domain": "mylife.com", "opt_out_url": "https://www.mylife.com/ccpa/index.pubview"},
    {"broker": "Instant Checkmate", "domain": "instantcheckmate.com", "opt_out_url": "https://www.instantcheckmate.com/opt-out/"},
    {"broker": "TruthFinder", "domain": "truthfinder.com", "opt_out_url": "https://www.truthfinder.com/opt-out/"},
    {"broker": "Nuwber", "domain": "nuwber.com", "opt_out_url": "https://nuwber.com/removal/link"},
    {"broker": "Advanced Background Checks", "domain": "advancedbackgroundchecks.com", "opt_out_url": "https://www.advancedbackgroundchecks.com/removal"},
    {"broker": "Pipl", "domain": "pipl.com", "opt_out_url": "https://pipl.com/personal-information-removal-request"},
    {"broker": "FamilyTreeNow", "domain": "familytreenow.com", "opt_out_url": "https://www.familytreenow.com/optout"},
    {"broker": "Radaris", "domain": "radaris.com", "opt_out_url": "https://radaris.com/control/privacy"},
    {"broker": "PeekYou", "domain": "peekyou.com", "opt_out_url": "https://www.peekyou.com/about/contact/optout/"},
    {"broker": "FastPeopleSearch", "domain": "fastpeoplesearch.com", "opt_out_url": "https://www.fastpeoplesearch.com/removal"},
    {"broker": "PeopleLooker", "domain": "peoplelooker.com", "opt_out_url": "https://www.peoplelooker.com/f/optout/search"},
    {"broker": "ClustrMaps", "domain": "clustrmaps.com", "opt_out_url": "https://clustrmaps.com/bl/opt-out"},
    {"broker": "SearchPeopleFree", "domain": "searchpeoplefree.com", "opt_out_url": "https://www.searchpeoplefree.com/opt-out"},
    {"broker": "ThatsThem", "domain": "thatsthem.com", "opt_out_url": "https://thatsthem.com/optout"},
    {"broker": "ZabaSearch", "domain": "zabasearch.com", "opt_out_url": "https://www.zabasearch.com/block_records/"},
    {"broker": "SmartBackgroundChecks", "domain": "smartbackgroundchecks.com", "opt_out_url": "https://www.smartbackgroundchecks.com/optout"},
    {"broker": "US Search", "domain": "ussearch.com", "opt_out_url": "https://www.ussearch.com/opt-out/"},
    {"broker": "CheckPeople", "domain": "checkpeople.com", "opt_out_url": "https://www.checkpeople.com/do-not-sell-info"},
    {"broker": "PublicRecordsNow", "domain": "publicrecordsnow.com", "opt_out_url": "https://www.publicrecordsnow.com/optout/"},
    {"broker": "USPhoneBook", "domain": "usphonebook.com", "opt_out_url": "https://www.usphonebook.com/opt-out"},
    {"broker": "CocoFinder", "domain": "cocofinder.com", "opt_out_url": "https://cocofinder.com/optout"},
    {"broker": "IDTrue", "domain": "idtrue.com", "opt_out_url": "https://www.idtrue.com/optout"},
    {"broker": "Neighbor.report", "domain": "neighbor.report", "opt_out_url": "https://neighbor.report/remove"},
    {"broker": "Homemetry", "domain": "homemetry.com", "opt_out_url": "https://homemetry.com/optout"},
]


def _host(url: str) -> str:
    u = (url or "").strip().split(";")[0].strip()
    u = re.sub(r"^https?://", "", u, flags=re.I).lstrip("/").lower().split("/")[0]
    return u[4:] if u.startswith("www.") else u


def _load_registry_domains(csv_path: str | None) -> set[str]:
    """Domains of every broker in the CA Data Broker Registry (for the ca_registered flag)."""
    if csv_path:
        data = Path(csv_path).read_text(encoding="utf-8-sig")
    else:
        print(f"Downloading CA Data Broker Registry: {CA_REGISTRY_CSV_URL}")
        req = urllib.request.Request(CA_REGISTRY_CSV_URL, headers={"User-Agent": "arescope-self-audit"})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (trusted gov URL)
            data = r.read().decode("utf-8-sig")
    rows = list(csv.DictReader(data.splitlines()))
    if not rows:
        return set()
    web_col = list(rows[0].keys())[2]  # "Data broker primary website:"
    domains: set[str] = set()
    for row in rows:
        for part in (row.get(web_col) or "").split(";"):
            d = _host(part)
            if d:
                domains.add(d)
    print(f"  registry: {len(rows)} brokers, {len(domains)} domains")
    return domains


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry-csv", help="Local path to a CA registry CSV (else download).")
    args = ap.parse_args()

    try:
        registered = _load_registry_domains(args.registry_csv)
    except Exception as e:  # network/parse — the flag is enrichment, not essential
        print(f"  WARN: could not load registry ({e}); ca_registered left null", file=sys.stderr)
        registered = None

    out = []
    for b in CURATED:
        rec = dict(b)
        rec["ca_registered"] = (b["domain"] in registered) if registered is not None else None
        out.append(rec)

    payload = {
        "_source": "Curated consumer people-search brokers; ca_registered cross-referenced "
        "against the California Data Broker Registry (cppa.ca.gov/data_broker_registry).",
        "_generated": date.today().isoformat(),
        "_note": "Enumeration, not confirmation — the connector marks every signal confirmed:false.",
        "brokers": out,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    n_reg = sum(1 for b in out if b["ca_registered"]) if registered is not None else "?"
    print(f"Wrote {len(out)} brokers -> {OUT} ({n_reg} CA-registered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
