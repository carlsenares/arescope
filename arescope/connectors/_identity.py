"""Shared helpers for identity-enrichment connectors (EXTENDED_SEARCH_SCOPE.md).

The enrichment connectors (GitHub, Reddit, Gravatar, Maigret-metadata) all turn a
public profile into the same normalized unit: an `identity_attribute` Signal — one
fact a handle/email reveals about the real person (their name, location, photo,
bio…). Keeping the emit + field-mapping in one place means every connector produces
identical shapes the pipeline (clustering → ACCOUNT_METADATA / FACE_PHOTO_EXPOSURE,
graph → photo/location nodes) can treat uniformly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from arescope.schemas import InputType, Signal

IDENTITY_KIND = "identity_attribute"

# Attribute vocabulary (what the pipeline keys off). "photo" routes to the face/photo
# finding + a map node; "location" to a location node; the rest enrich ACCOUNT_METADATA.
NAME = "name"
LOCATION = "location"
PHOTO = "photo"
BIO = "bio"
COMPANY = "company"
LINK = "link"  # a linked profile/handle the user can be followed to (deanon vector)

# Map the many field names real profiles use → our attribute vocabulary. Unknown
# fields are ignored (we never invent an attribute we can't label honestly).
_FIELD_MAP: dict[str, str] = {
    "fullname": NAME, "full_name": NAME, "name": NAME, "real_name": NAME, "realname": NAME,
    "displayname": NAME, "display_name": NAME,
    "location": LOCATION, "city": LOCATION, "country": LOCATION, "region": LOCATION,
    "currentlocation": LOCATION, "current_location": LOCATION, "geo": LOCATION,
    "image": PHOTO, "avatar": PHOTO, "avatar_url": PHOTO, "picture": PHOTO,
    "image_url": PHOTO, "thumbnailurl": PHOTO, "photo": PHOTO, "icon_img": PHOTO,
    "bio": BIO, "about": BIO, "aboutme": BIO, "description": BIO,
    "company": COMPANY, "organization": COMPANY, "org": COMPANY,
}


def identity_signal(
    *,
    source: str,
    attribute: str,
    value: str,
    subject_value: str,
    subject_type: InputType,
    platform: str,
    url: str | None = None,
    meta: Mapping[str, object] | None = None,
) -> Signal:
    """One normalized identity fact. `platform` is where it was found (e.g. github.com).

    `meta` adds attribute-specific facts to the raw payload — e.g. a photo carries
    `is_default` (Google's monogram avatar vs a real uploaded image) so the judge and
    the UI can tell "no real picture is public" from "the person's face is public".
    """
    raw: dict[str, object] = {
        "attribute": attribute,
        "value": value,
        "platform": platform,
        "url": url,
    }
    if meta:
        raw.update(meta)
    return Signal(
        source=source,
        kind=IDENTITY_KIND,
        # locator carries attribute+platform so distinct facts don't dedup into one
        locator=f"{platform}:{attribute}",
        subject_value=subject_value,
        subject_type=subject_type,
        raw=raw,
    )


def from_profile_fields(
    *,
    source: str,
    platform: str,
    fields: Mapping[str, object],
    subject_value: str,
    subject_type: InputType,
    profile_url: str | None = None,
) -> Iterator[Signal]:
    """Yield identity_attribute Signals for every recognised, non-empty profile field."""
    seen: set[tuple[str, str]] = set()
    for raw_key, raw_val in fields.items():
        attribute = _FIELD_MAP.get(str(raw_key).strip().lower())
        if not attribute:
            continue
        value = str(raw_val).strip() if raw_val is not None else ""
        if not value or value.lower() in ("none", "null"):
            continue
        dedup = (attribute, value.lower())
        if dedup in seen:
            continue
        seen.add(dedup)
        yield identity_signal(
            source=source,
            attribute=attribute,
            value=value,
            subject_value=subject_value,
            subject_type=subject_type,
            platform=platform,
            # photos ARE the value (a URL); for others, link back to the profile page
            url=value if attribute == PHOTO else profile_url,
        )
