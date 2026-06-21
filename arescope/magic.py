"""Magic-link tokens: passwordless login + signup email verification.

A token is a high-entropy random string sent only inside the emailed URL; the DB
stores just its SHA-256 (so a DB read can't forge a usable link). Tokens are
single-use (used_at) and time-boxed (expires_at). `purpose` keeps the two flows
distinct — a 'login' link can't be replayed as a 'verify', and vice versa.

The pure helpers (generate/hash/expiry) are unit-tested without a DB; the
DB-touching create/consume sit on top of them.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from sqlalchemy import select

from arescope.config import get_settings
from arescope.db import models
from arescope.db.session import session_scope
from arescope.mailer import send_login_link, send_verify_link

LOGIN = "login"
VERIFY = "verify"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(raw: str) -> str:
    """Stable SHA-256 hex of the raw token (what we persist + look up by)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). The raw value only ever leaves in the URL."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    now = now or _now()
    # Tolerate naive datetimes coming back from some backends (treat as UTC).
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now >= expires_at


def _verify_url(raw: str) -> str:
    base = get_settings().base_url.rstrip("/")
    return f"{base}/auth/verify?" + urlencode({"token": raw}, quote_via=quote)


# --- DB-backed create + consume ---------------------------------------------


def issue_token(user_id: str, purpose: str) -> str:
    """Persist a fresh single-use token for a user and return the raw value."""
    raw, token_hash = generate_token()
    ttl = get_settings().magic_link_ttl_minutes
    with session_scope() as s:
        s.add(
            models.LoginToken(
                user_id=user_id,
                purpose=purpose,
                token_hash=token_hash,
                expires_at=_now() + timedelta(minutes=ttl),
            )
        )
    return raw


def send_magic_login(email: str) -> None:
    """Email a login link IF an account exists. Silent on miss (anti-enumeration)."""
    email = email.strip().lower()
    with session_scope() as s:
        user = s.execute(
            select(models.User).where(models.User.email == email)
        ).scalar_one_or_none()
        user_id = user.id if user else None
    if user_id is None:
        return  # caller shows the same generic "check your inbox" either way
    send_login_link(email, _verify_url(issue_token(user_id, LOGIN)))


def send_verification(user_id: str, email: str) -> None:
    """Email an address-confirmation link for a freshly created account."""
    send_verify_link(email, _verify_url(issue_token(user_id, VERIFY)))


def consume_token(raw: str) -> tuple[str, str] | None:
    """Validate + burn a token. Returns (user_id, purpose) or None if invalid.

    Marks the row used atomically so a link works exactly once. On verify it also
    flips the account's email_verified flag.
    """
    if not raw:
        return None
    token_hash = hash_token(raw)
    with session_scope() as s:
        tok = s.execute(
            select(models.LoginToken).where(models.LoginToken.token_hash == token_hash)
        ).scalar_one_or_none()
        if tok is None or tok.used_at is not None or is_expired(tok.expires_at):
            return None
        tok.used_at = _now()
        result = (tok.user_id, tok.purpose)
        if tok.purpose == VERIFY:
            user = s.get(models.User, tok.user_id)
            if user is not None:
                user.email_verified = True
    return result
