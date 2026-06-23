"""EXIF/GPS — what an image file itself leaks (#9, location/doxxing).

Consumes: photo (the value is a local path to the user's own image). Pure-local,
no network, no key — reads the embedded EXIF: GPS coordinates (a photo posted
straight off a phone can carry the exact spot it was taken = home/work), plus
camera make/model and capture timestamp.

Emits a `location` identity_attribute when GPS is present (becomes a location node
on the map and is rated as a location exposure), and a `photo_meta` Signal for
camera/timestamp. No EXIF / no GPS => clean (no signal), never a failure.
"""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors._identity import identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_GPS_IFD = 0x8825


class ExifConnector(Connector):
    name = "exif"
    consumes = {InputType.PHOTO}

    def available(self, cfg: Settings) -> bool:
        if not cfg.exif_enabled:
            return False
        import importlib.util
        return importlib.util.find_spec("PIL") is not None

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            from PIL import Image
        except Exception as e:
            raise ConnectorGap(f"Pillow not available: {e}") from e
        try:
            img = Image.open(value)
            exif = img.getexif()
        except FileNotFoundError as e:
            raise ConnectorGap(f"image not found: {value}") from e
        except Exception as e:
            raise ConnectorGap(f"could not read image EXIF: {e}") from e

        signals: list[Signal] = []

        coords = _gps_decimal(exif)
        if coords:
            lat, lon = coords
            signals.append(identity_signal(
                source=self.name, attribute="location",
                value=f"{lat:.5f}, {lon:.5f}",
                subject_value=value, subject_type=InputType.PHOTO,
                platform="photo EXIF",
                url=f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}",
                meta={"latitude": lat, "longitude": lon, "from_exif": True},
            ))

        make = exif.get(271)
        model = exif.get(272)
        taken = exif.get(306)
        if make or model or taken:
            signals.append(Signal(
                source=self.name, kind="photo_meta", locator=value,
                subject_value=value, subject_type=InputType.PHOTO,
                raw={"camera_make": _s(make), "camera_model": _s(model),
                     "taken_at": _s(taken), "has_gps": bool(coords)},
            ))
        return signals


def _s(v) -> str | None:
    if v is None:
        return None
    return str(v).strip("\x00 ").strip() or None


def _gps_decimal(exif) -> tuple[float, float] | None:
    """Pull GPSLatitude/Longitude (DMS rationals + N/S/E/W refs) -> decimal degrees."""
    try:
        gps = exif.get_ifd(_GPS_IFD)
    except Exception:
        return None
    if not gps:
        return None
    lat = _dms(gps.get(2))
    lon = _dms(gps.get(4))
    if lat is None or lon is None:
        return None
    if str(gps.get(1, "N")).upper().startswith("S"):
        lat = -lat
    if str(gps.get(3, "E")).upper().startswith("W"):
        lon = -lon
    return (lat, lon)


def _dms(parts) -> float | None:
    """((d),(m),(s)) of rationals -> decimal degrees."""
    try:
        d, m, s = (float(x) for x in parts)
        return d + m / 60 + s / 3600
    except Exception:
        return None
