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
    create_user,
    current_user,
    login_session,
    logout_session,
)
from arescope.db import models
from arescope.db.session import session_scope
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
    (InputType.EMAIL, "email", "Email address(es)", "you@example.com"),
    (InputType.USERNAME, "username", "Username / handle(s)", "yourhandle"),
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
    login_session(request, uid)
    return RedirectResponse(_safe_next(next), status_code=303)


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


# --- app: dashboard + new scan ----------------------------------------------


def _require(request: Request) -> models.User | RedirectResponse:
    user = current_user(request)
    if user is None:
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    return user


@router.get("/app", response_class=HTMLResponse)
def app_home(request: Request):
    user = _require(request)
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
    user = _require(request)
    if isinstance(user, RedirectResponse):
        return user
    return _render(request, "new_scan.html", fields=_INPUT_FIELDS, error=None, values={})


@router.post("/app/new", response_class=HTMLResponse)
async def new_scan_submit(request: Request):
    user = _require(request)
    if isinstance(user, RedirectResponse):
        return user

    form = await request.form()
    _check_csrf(request, form.get("csrf"))

    # Each field may hold several comma/newline-separated values you own.
    identifiers: list[Identifier] = []
    values: dict[str, str] = {}
    for itype, key, _label, _ph in _INPUT_FIELDS:
        raw = str(form.get(key, "")).strip()
        values[key] = raw
        for part in raw.replace("\n", ",").split(","):
            v = part.strip()
            if v:
                identifiers.append(
                    Identifier(type=itype, value=v, ownership_verified=True)
                )

    if not identifiers:
        return _render(
            request,
            "new_scan.html",
            fields=_INPUT_FIELDS,
            error="Add at least one identifier you own.",
            values=values,
        )
    if not form.get("own"):
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
