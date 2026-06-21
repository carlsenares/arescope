"""Web routes: account flows + the input interface, server-rendered.

Auth gate: protected pages redirect logged-out users to /login?next=… and back.
Every state-changing POST carries a per-session CSRF token. The input form
creates a Subject (owned by the logged-in user) + a queued Scan, then hands off
to the worker. Results UI is a separate pass.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from arescope.auth import (
    AuthError,
    authenticate,
    can_run_scan,
    create_user,
    current_user,
    login_session,
    logout_session,
)
from arescope.db import models
from arescope.db.session import session_scope
from arescope.magic import consume_token, send_magic_login, send_verification
from arescope.schemas import Identifier, InputType
from arescope.service import create_scan, create_subject
from arescope.worker.tasks import run_scan_task

_HERE = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(_HERE, "templates")
APP_STATIC_DIR = os.path.join(_HERE, "static")

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Which identifier types the form collects (photo upload comes with a later pass).
_INPUT_FIELDS: list[tuple[InputType, str, str, str]] = [
    (InputType.EMAIL, "email", "Email address", "you@example.com"),
    (InputType.USERNAME, "username", "Username / handle", "yourhandle"),
    (InputType.NAME, "name", "Full name", "Jane Doe"),
    (InputType.IP, "ip", "IP address you own", "203.0.113.4"),
]


# --- CSRF --------------------------------------------------------------------


def _csrf(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


def _check_csrf(request: Request, token: str | None) -> None:
    if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(400, "Invalid or expired form token. Please try again.")


def _render(request: Request, template: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {"user": current_user(request), "csrf": _csrf(request), **ctx},
    )


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirects (no open-redirect)."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/app"


# --- signup / login / logout -------------------------------------------------


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, next: str = "/app") -> HTMLResponse:
    if current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render(request, "signup.html", next=next, error=None, values={})


@router.post("/signup", response_class=HTMLResponse)
def signup_submit(
    request: Request,
    email: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/app"),
    csrf: str = Form(""),
) -> HTMLResponse:
    _check_csrf(request, csrf)
    try:
        uid = create_user(email, username, password)
    except AuthError as e:
        return _render(
            request,
            "signup.html",
            next=next,
            error=str(e),
            values={"email": email, "username": username},
        )
    # Log them in immediately (password works), and send a confirm-email link in the
    # background — fire-and-forget so an email hiccup never blocks signup.
    login_session(request, uid)
    try:
        send_verification(uid, email.strip().lower())
    except Exception:  # noqa: BLE001 — email is best-effort; the screen offers a resend
        pass
    # Funnel straight to the verify gate — confirming the address comes before anything else.
    return RedirectResponse("/verify-email", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/app") -> HTMLResponse:
    if current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render(request, "login.html", next=next, error=None, values={})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    identifier: str = Form(""),
    password: str = Form(""),
    next: str = Form("/app"),
    csrf: str = Form(""),
) -> HTMLResponse:
    _check_csrf(request, csrf)
    uid = authenticate(identifier, password)
    if uid is None:
        return _render(
            request,
            "login.html",
            next=next,
            error="Wrong email/username or password.",
            values={"identifier": identifier},
        )
    login_session(request, uid)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")) -> RedirectResponse:
    _check_csrf(request, csrf)
    logout_session(request)
    return RedirectResponse("/", status_code=303)


# --- magic link: passwordless login + email verification ---------------------


@router.post("/magic", response_class=HTMLResponse)
def magic_request(request: Request, email: str = Form(""), csrf: str = Form("")) -> HTMLResponse:
    """Request a sign-in link. Always shows the same confirmation (no enumeration)."""
    _check_csrf(request, csrf)
    try:
        send_magic_login(email)
    except Exception:  # noqa: BLE001 — never reveal whether the address exists / send failed
        pass
    return _render(request, "magic_sent.html", email=email.strip())


@router.post("/verify/resend")
def resend_verification(request: Request, csrf: str = Form("")) -> RedirectResponse:
    """Re-send the confirm-email link to the logged-in user, stay on the gate."""
    _check_csrf(request, csrf)
    user = current_user(request)
    if user and not user.email_verified:
        try:
            send_verification(user.id, user.email)
        except Exception:  # noqa: BLE001
            pass
    return RedirectResponse("/verify-email?sent=1", status_code=303)


@router.get("/verify-email", response_class=HTMLResponse)
def verify_email_screen(request: Request, sent: int = 0):
    """Blocking gate after signup: confirm your address before using the app."""
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.email_verified:
        return RedirectResponse("/app", status_code=303)
    return _render(request, "verify_email.html", email=user.email, sent=bool(sent))


@router.get("/verify-status")
def verify_status(request: Request) -> dict:
    """Polled by the verify screen so it auto-advances when the link is clicked
    on another device (e.g. the user's phone)."""
    user = current_user(request)
    return {"verified": bool(user and user.email_verified)}


@router.get("/auth/verify", response_class=HTMLResponse)
def magic_verify(request: Request, token: str = ""):
    """Consume a magic link: log in (login) or confirm the address (verify)."""
    result = consume_token(token)
    if result is None:
        return _render(request, "magic_invalid.html")
    user_id, _purpose = result  # email_verified flip (verify) happens inside consume_token
    login_session(request, user_id)
    # A login link signs them in; a verify link confirms the address (they may already
    # be logged in). Either way, land them in the app.
    return RedirectResponse("/app", status_code=303)


# --- app: dashboard + new scan ----------------------------------------------


def _require(request: Request) -> models.User | RedirectResponse:
    user = current_user(request)
    if user is None:
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    return user


def _require_verified(request: Request) -> models.User | RedirectResponse:
    """Logged in AND email-confirmed (admins are exempt — seeded pre-verified).
    Unverified accounts are bounced to the verify gate before any app surface."""
    user = _require(request)
    if isinstance(user, RedirectResponse):
        return user
    if not user.email_verified and not user.is_admin:
        return RedirectResponse("/verify-email", status_code=303)
    return user


@router.get("/app", response_class=HTMLResponse)
def app_home(request: Request):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    with session_scope() as s:
        scans = (
            s.query(models.Scan)
            .join(models.Subject, models.Scan.subject_id == models.Subject.id)
            .filter(models.Subject.user_id == user.id)
            .order_by(models.Scan.started_at.desc())
            .all()
        )
        rows = [
            {"id": sc.id, "status": sc.status, "started_at": sc.started_at}
            for sc in scans
        ]
    return _render(request, "app_home.html", scans=rows)


@router.get("/app/new", response_class=HTMLResponse)
def new_scan_form(request: Request):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    if not can_run_scan(user):
        return _render(request, "locked.html")
    return _render(request, "new_scan.html", fields=_INPUT_FIELDS, error=None, values={})


@router.post("/app/new", response_class=HTMLResponse)
async def new_scan_submit(request: Request):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    if not can_run_scan(user):
        # Defence in depth: the form is hidden behind the gate, but never trust that.
        return _render(request, "locked.html")

    form = await request.form()
    _check_csrf(request, form.get("csrf"))

    # One value per identifier type (audit a single email / username / name / IP
    # per run — not bulk lists).
    identifiers: list[Identifier] = []
    values: dict[str, str] = {}
    for itype, key, _label, _ph in _INPUT_FIELDS:
        raw = str(form.get(key, "")).strip()
        values[key] = raw
        if raw:
            identifiers.append(Identifier(type=itype, value=raw, ownership_verified=True))

    if not identifiers:
        return _render(
            request,
            "new_scan.html",
            fields=_INPUT_FIELDS,
            error="Add at least one identifier.",
            values=values,
        )
    # Self-audit confirmation. Admins bypass it (and, when the P2 per-input
    # ownership gate lands, that gate must skip admins too — they can audit anything).
    if not user.is_admin and not form.get("own"):
        return _render(
            request,
            "new_scan.html",
            fields=_INPUT_FIELDS,
            error="Please confirm these identifiers are yours — Arescope is self-audit only.",
            values=values,
        )

    subject_id = create_subject(identifiers, user_id=user.id)
    scan_id = create_scan(subject_id)
    try:
        run_scan_task.delay(scan_id)  # hand off to the worker
    except Exception:
        # Broker offline: the scan stays queued and can be picked up later. Never
        # fail the submission over infra — the record is already persisted.
        pass
    return RedirectResponse("/app", status_code=303)


# --- admin: real-time run-access control ------------------------------------


def _require_admin(request: Request) -> models.User | RedirectResponse:
    user = current_user(request)
    if user is None:
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    if not user.is_admin:
        raise HTTPException(404)  # don't advertise the admin surface to non-admins
    return user


@router.get("/app/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    admin = _require_admin(request)
    if isinstance(admin, RedirectResponse):
        return admin
    with session_scope() as s:
        users = s.query(models.User).order_by(models.User.created_at.desc()).all()
        rows = [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "is_admin": u.is_admin,
                "email_verified": u.email_verified,
                "can_scan": u.can_scan,
                "created_at": u.created_at,
            }
            for u in users
        ]
    return _render(request, "admin.html", users=rows)


@router.post("/app/admin/access")
def admin_set_access(
    request: Request,
    user_id: str = Form(...),
    grant: str = Form(""),
    csrf: str = Form(""),
):
    """Flip a user's run-access in real time. grant=='1' grants, else revokes."""
    admin = _require_admin(request)
    if isinstance(admin, RedirectResponse):
        return admin
    _check_csrf(request, csrf)
    with session_scope() as s:
        target = s.get(models.User, user_id)
        if target is not None and not target.is_admin:  # admins are always allowed
            target.can_scan = grant == "1"
    return RedirectResponse("/app/admin", status_code=303)
