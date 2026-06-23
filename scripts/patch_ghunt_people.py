"""Patch GHunt 2.3.4 to work against Google's current API + fix its broken --json path.

GHunt 2.3.4 is the last PyPI release and is unmaintained. Two bugs block the email
lookup we drive (verified live 2026-06-23, with a VALID session):

1. `parsers/people.py` indexes `<photo>["metadata"]["container"]` directly, but Google's
   current People API omits `container` on some photo/reachability entries → the lookup
   crashes with `KeyError: 'container'` before returning anything. We rewrite those into
   tolerant `.get(...)` lookups that skip an entry when `container` is absent.

2. `modules/email.py`'s `--json` branch references `photos` and `reviews` in the Maps
   block, but the Maps call only ever assigns `err, stats` — so writing JSON dies with
   `NameError: name 'photos' is not defined`. We initialise `photos = reviews = None`
   right after the Maps call so the JSON serialises (profile + photo + review stats land).

Idempotent and fail-soft: replacements that no longer match (e.g. upstream changed shape)
are simply skipped, leaving the file valid — the connector then degrades to a coverage
gap, never a crash. Pass the installed `ghunt` package directory (defaults to the venv).
"""

from __future__ import annotations

import sys
from pathlib import Path

GHUNT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "/opt/ghunt-venv/lib/python3.12/site-packages/ghunt"
)

# {relative file: [(old, new), ...]}
PATCHES: dict[str, list[tuple[str, str]]] = {
    "parsers/people.py": [
        (
            'self.profilePhotos[profile_data["metadata"]["container"]] = person_photo',
            'if (___c := profile_data.get("metadata", {}).get("container")):\n'
            '                            self.profilePhotos[___c] = person_photo',
        ),
        (
            'self.coverPhotos[cover_photo_data["metadata"]["container"]] = person_cover_photo',
            'if (___c := cover_photo_data.get("metadata", {}).get("container")):\n'
            '                    self.coverPhotos[___c] = person_cover_photo',
        ),
        (
            'containers_names.add(app_data["metadata"]["container"])',
            'if (___c := app_data.get("metadata", {}).get("container")):\n'
            '                    containers_names.add(___c)',
        ),
    ],
    "modules/email.py": [
        (
            "    err, stats = await gmaps.get_reviews(as_client, target.personId)",
            "    err, stats = await gmaps.get_reviews(as_client, target.personId)\n"
            "    photos = reviews = None  # ghunt 2.3.4 refs these in --json but never assigns them",
        ),
    ],
}


def main() -> int:
    total = applied = 0
    for rel, reps in PATCHES.items():
        target = GHUNT_DIR / rel
        if not target.is_file():
            print(f"[patch_ghunt] target not found, skipping: {target}")
            continue
        text = target.read_text()
        for old, new in reps:
            total += 1
            if old in text:
                text = text.replace(old, new)
                applied += 1
        target.write_text(text)
    print(f"[patch_ghunt] applied {applied}/{total} guard(s) under {GHUNT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
