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
from arescope.schemas import SEVERITY_ORDER, Category, Identifier, InputType, Severity
from arescope.service import (
    create_scan,
    create_subject,
    generate_finding_remediation,
    resolve_finding,
)
from arescope.taxonomy import TAXONOMY
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

# "Top sites only" Maigret choice → cap to the N most popular sites (much faster).
_MAIGRET_TOP_N = 50


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
            {"id": sc.id, "name": sc.name, "status": sc.status, "started_at": sc.started_at}
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

    # Per-run options: the "top sites only" Maigret choice (only bites when a
    # username was entered; harmless otherwise).
    options: dict = {}
    if str(form.get("maigret_scope", "")) == "top":
        options["maigret_top_sites"] = _MAIGRET_TOP_N
    name = str(form.get("name", "")).strip()[:80] or None

    subject_id = create_subject(identifiers, user_id=user.id)
    scan_id = create_scan(subject_id, options=options, name=name)
    try:
        run_scan_task.delay(scan_id)  # hand off to the worker
    except Exception:
        # Broker offline: the scan stays queued and can be picked up later. Never
        # fail the submission over infra — the record is already persisted.
        pass
    return RedirectResponse(f"/app/scans/{scan_id}", status_code=303)


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


# --- results: per-finding ratings, questions, on-demand solutions ------------

_SEV_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}


def _finding_view(f: models.Finding) -> dict:
    """Flatten a Finding row into everything the results template needs."""
    rem = f.remediation
    try:
        cat_label = TAXONOMY[Category(f.category)].label
    except (KeyError, ValueError):
        cat_label = f.category
    try:
        rank = SEVERITY_ORDER[Severity(f.severity)]
    except (KeyError, ValueError):
        rank = 0
    questions = f.questions or []
    return {
        "id": f.id,
        "severity": f.severity,
        "severity_label": _SEV_LABEL.get(f.severity, f.severity.title()),
        "rank": rank,
        "action": f.action,
        "category_label": cat_label,
        "title": f.title,
        "rationale": f.rationale,
        "confidence": round((f.confidence or 0) * 100),
        "fix_difficulty": f.fix_difficulty,
        "easy_fix": f.easy_fix,
        "members": f.member_locators or [],
        "show_questions": f.action == "depends" and bool(questions),
        "questions": [{"idx": i, "prompt": q.get("prompt", "")} for i, q in enumerate(questions)],
        "can_generate_solution": (
            f.fix_difficulty == "involved"
            and rem is None
            and f.action in ("fix_now", "worth_fixing")
        ),
        "remediation": None
        if rem is None
        else {
            "summary": rem.summary,
            "steps": rem.steps or [],
            "artifact": rem.artifact,
        },
    }


def _load_owned_scan(user: models.User, scan_id: str) -> dict | None:
    """Load a scan + its findings IF it belongs to the user (or user is admin)."""
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            return None
        subject = s.get(models.Subject, scan.subject_id)
        if subject is None or (subject.user_id != user.id and not user.is_admin):
            return None
        findings = s.query(models.Finding).filter(models.Finding.scan_id == scan_id).all()
        views = sorted(
            (_finding_view(f) for f in findings),
            key=lambda v: (-v["rank"], -v["confidence"]),
        )
        snap = scan.config_snapshot or {}
        return {
            "id": scan.id,
            "name": scan.name,
            "status": scan.status,
            "started_at": scan.started_at,
            "options": scan.options or {},
            "phase": snap.get("phase"),
            "coverage_gaps": snap.get("coverage_gaps", []),
            "findings": views,
            "actionable": sum(1 for v in views if v["action"] in ("fix_now", "worth_fixing")),
        }


def _finding_scan_id(user: models.User, finding_id: str) -> str | None:
    """Return the scan_id for a finding IF the user owns it (or is admin), else None."""
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            return None
        scan = s.get(models.Scan, f.scan_id)
        subject = s.get(models.Subject, scan.subject_id) if scan else None
        if subject is None or (subject.user_id != user.id and not user.is_admin):
            return None
        return f.scan_id


@router.get("/app/scans/{scan_id}", response_class=HTMLResponse)
def scan_results(request: Request, scan_id: str):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    scan = _load_owned_scan(user, scan_id)
    if scan is None:
        raise HTTPException(404, "scan not found")
    return _render(request, "results.html", scan=scan)


@router.get("/app/scans/{scan_id}/status")
def scan_status(request: Request, scan_id: str) -> dict:
    """Polled by the results page while a scan is still running."""
    user = current_user(request)
    if user is None:
        return {"status": "unknown"}
    scan = _load_owned_scan(user, scan_id)
    if scan is None:
        return {"status": "unknown"}
    return {
        "status": scan["status"],
        "findings": len(scan["findings"]),
        "phase": scan["phase"],
    }


@router.post("/app/findings/{finding_id}/solution")
async def finding_solution(request: Request, finding_id: str):
    """Generate the involved, tailored fix for one finding (on demand, Opus)."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    scan_id = _finding_scan_id(user, finding_id)
    if scan_id is None:
        raise HTTPException(404, "finding not found")
    if not can_run_scan(user):  # generating a solution is an LLM cost — gate it
        return _render(request, "locked.html")
    try:
        generate_finding_remediation(finding_id)
    except ValueError:
        raise HTTPException(404, "finding not found")
    return RedirectResponse(f"/app/scans/{scan_id}#f-{finding_id}", status_code=303)


@router.post("/app/findings/{finding_id}/resolve")
async def finding_resolve(request: Request, finding_id: str):
    """Apply yes/no answers to a DEPENDS finding's contingency questions (free)."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    scan_id = _finding_scan_id(user, finding_id)
    if scan_id is None:
        raise HTTPException(404, "finding not found")
    # Collect answered questions: each radio is named q-<idx> with value yes/no.
    answers: dict[int, bool] = {}
    for key, val in form.items():
        if key.startswith("q-") and val in ("yes", "no"):
            try:
                answers[int(key[2:])] = val == "yes"
            except ValueError:
                continue
    if answers:
        try:
            resolve_finding(finding_id, answers)
        except ValueError:
            raise HTTPException(404, "finding not found")
    return RedirectResponse(f"/app/scans/{scan_id}#f-{finding_id}", status_code=303)
