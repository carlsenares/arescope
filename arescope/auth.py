"""Self-hosted authentication: password hashing, account creation, sessions.

No third-party identity provider — accounts live in our own Postgres, consistent
with the product's data-minimization promise. The session is a signed cookie
(Starlette SessionMiddleware) carrying only the user id; everything else is read
from the DB per request. Magic-link / email verification is additive on top of
this (the `email_verified` column already exists).
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import func, select
from starlette.requests import Request

from arescope.db import models
from arescope.db.session import session_scope

_ph = PasswordHasher()

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_KEY = "uid"


class AuthError(ValueError):
    """Validation / credential failure surfaced to the form layer."""


# --- password hashing --------------------------------------------------------


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


# --- account creation + lookup ----------------------------------------------


def _normalize(email: str, username: str) -> tuple[str, str]:
    return email.strip().lower(), username.strip().lower()


def validate_signup(email: str, username: str, password: str) -> None:
    email, username = _normalize(email, username)
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3–32 chars: lowercase letters, numbers, underscore.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")


def create_user(
    email: str,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
    email_verified: bool = False,
) -> str:
    """Create an account. Raises AuthError on validation or uniqueness failure."""
    validate_signup(email, username, password)
    email, username = _normalize(email, username)
    with session_scope() as s:
        existing = s.execute(
            select(models.User).where(
                (func.lower(models.User.email) == email)
                | (func.lower(models.User.username) == username)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.email == email:
                raise AuthError("An account with that email already exists.")
            raise AuthError("That username is taken.")
        user = models.User(
            email=email,
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
            email_verified=email_verified,
        )
        s.add(user)
        s.flush()
        return user.id


def authenticate(identifier: str, password: str) -> str | None:
    """Return the user id for email-or-username + password, else None."""
    ident = identifier.strip().lower()
    with session_scope() as s:
        user = s.execute(
            select(models.User).where(
                (func.lower(models.User.email) == ident)
                | (func.lower(models.User.username) == ident)
            )
        ).scalar_one_or_none()
        if user is None:
            return None
        return user.id if verify_password(user.password_hash, password) else None


# --- session helpers ---------------------------------------------------------


def login_session(request: Request, user_id: str) -> None:
    request.session[SESSION_KEY] = user_id


def logout_session(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


def can_run_scan(user: models.User | None) -> bool:
    """Run-lock predicate: only admins or explicitly granted accounts may scan.

    Scans cost money (LLM + paid connectors), so this gate is closed by default.
    Admins always pass; everyone else needs `can_scan` flipped on from the admin
    dashboard. This is the seam the paywall slots into later (plan/quota check here).
    """
    return bool(user and (user.is_admin or user.can_scan))


def current_user(request: Request) -> models.User | None:
    """Load the logged-in user (detached copy), or None. Cheap per-request lookup."""
    uid = request.session.get(SESSION_KEY)
    if not uid:
        return None
    with session_scope() as s:
        return s.get(models.User, uid)
