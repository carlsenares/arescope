"""Web routes: account flows + the input interface, server-rendered.

Auth gate: protected pages redirect logged-out users to /login?next=… and back.
Every state-changing POST carries a per-session CSRF token. The input form
creates a Subject (owned by the logged-in user) + a queued Scan, then hands off
to the worker. Results UI is a separate pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from kombu.exceptions import OperationalError as BrokerError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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
from arescope.config import get_settings
from arescope.db import models
from arescope.db.session import session_scope
from arescope.graph import build_map_graph
from arescope.magic import consume_token, send_magic_login, send_verification
from arescope.schemas import SEVERITY_ORDER, Category, Identifier, InputType, Severity
from arescope.service import (
    create_scan,
    create_subject,
    evaluate_and_store_map,
    generate_finding_artifact,
    generate_finding_remediation,
    load_chat,
    resolve_finding,
    send_finding_chat,
    send_map_chat,
)
from arescope.taxonomy import TAXONOMY
from arescope.worker.tasks import evaluate_map_task, run_map_task, run_scan_task

_HERE = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(_HERE, "templates")
APP_STATIC_DIR = os.path.join(_HERE, "static")

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _asset_version() -> str:
    """Short content hash of the static assets, appended as ?v= so a redeploy busts
    the browser cache (otherwise app.css/chat.js stay stale and UI fixes don't show)."""
    h = hashlib.sha1()
    for fn in ("app.css", "chat.js"):
        try:
            with open(os.path.join(APP_STATIC_DIR, fn), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()[:10]


templates.env.globals["asset_v"] = _asset_version()

# Search mode = one focused analysis per input type, presented as tabs (each type
# has its own connectors + its own future ownership gate, so they're distinct scans
# — not one bulk run). `kind` is the InputType; `field` is the form key.
_SEARCH_TABS: list[dict] = [
    {"kind": "email", "label": "Email", "ph": "you@example.com",
     "blurb": "Breaches, infostealer logs, leaked passwords, and where it's registered."},
    {"kind": "username", "label": "Username", "ph": "yourhandle",
     "blurb": "Accounts across hundreds of sites, plus public web mentions."},
    {"kind": "phone", "label": "Phone", "ph": "+1 555 010 0000",
     "blurb": "Breach exposure, spam/fraud reputation, registered apps, and carrier."},
    {"kind": "name", "label": "Name", "ph": "Jane Doe",
     "blurb": "Data-broker / people-search listings and public web mentions."},
    {"kind": "ip", "label": "IP address", "ph": "203.0.113.4",
     "blurb": "Exposed services, geolocation, network, and abuse reputation."},
    {"kind": "photo", "label": "Photo", "ph": "",
     "blurb": "GPS location and camera metadata embedded in a photo you've shared."},
]
_SEARCH_KINDS = {t["kind"] for t in _SEARCH_TABS}
# Input types map mode collects (all optional; fill any subset). email/username/phone
# accept multiple (most people have more than one); name/ip/photo are single.
_MAP_MULTI = ["email", "username", "phone"]
_MAP_SINGLE = ["name", "ip"]
_MAP_PER_TYPE_CAP = 3  # bound connector/rate-limit load per map build

_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}
_PHOTO_MAX_BYTES = 25 * 1024 * 1024

# "Top sites only" Maigret choice → cap to the N most popular sites (much faster).
_MAIGRET_TOP_N = 50


async def _save_photo(upload) -> str:
    """Persist an uploaded image to the shared uploads dir; return its path (the
    `photo` identifier value the EXIF connector reads in the worker)."""
    if upload is None or not getattr(upload, "filename", ""):
        raise ValueError("Choose a photo to analyse.")
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in _PHOTO_EXTS:
        raise ValueError("Unsupported image type — use JPG, PNG, TIFF, WebP or HEIC.")
    data = await upload.read()
    if not data:
        raise ValueError("That file was empty.")
    if len(data) > _PHOTO_MAX_BYTES:
        raise ValueError("Image is too large (max 25 MB).")
    updir = get_settings().upload_dir
    try:
        os.makedirs(updir, exist_ok=True)
    except OSError:
        updir = os.path.join("/tmp", "arescope-uploads")  # local-dev fallback
        os.makedirs(updir, exist_ok=True)
    path = os.path.join(updir, secrets.token_hex(16) + ext)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


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


def _wants_json(request: Request) -> bool:
    """True when the caller asked for JSON (the dashboard's in-place AJAX actions)."""
    return "application/json" in request.headers.get("accept", "")


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
            {
                "id": sc.id,
                "name": sc.name,
                "status": sc.status,
                "started_at": sc.started_at,
                "in_map": not (sc.options or {}).get("exclude_from_map"),
                "mode": (sc.options or {}).get("mode", "audit"),
            }
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
    return _render(request, "new_scan.html", tabs=_SEARCH_TABS, active="email",
                   error=None, values={})


def _search_error(request, active, values, msg):
    return _render(request, "new_scan.html", tabs=_SEARCH_TABS, active=active,
                   error=msg, values=values)


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

    kind = str(form.get("kind", "")).strip()
    if kind not in _SEARCH_KINDS:
        kind = "email"
    values = {kind: str(form.get(kind, "")).strip()}

    # Build the single identifier for this tab.
    if kind == "photo":
        try:
            value = await _save_photo(form.get("photo"))
        except ValueError as e:
            return _search_error(request, kind, {}, str(e))
        identifier = Identifier(type=InputType.PHOTO, value=value, ownership_verified=True)
    else:
        raw = values[kind]
        if not raw:
            return _search_error(request, kind, values, f"Enter a {kind} to audit.")
        identifier = Identifier(type=InputType(kind), value=raw, ownership_verified=True)

    if not user.is_admin and not form.get("own"):
        return _search_error(request, kind, values,
                             "Please confirm this is yours — Arescope is self-audit only.")

    options: dict = {}
    if kind == "username" and str(form.get("maigret_scope", "")) == "top":
        options["maigret_top_sites"] = _MAIGRET_TOP_N
    name = str(form.get("scan_name", "")).strip()[:80] or None

    subject_id = create_subject([identifier], user_id=user.id)
    scan_id = create_scan(subject_id, options=options, name=name)
    try:
        run_scan_task.delay(scan_id)  # hand off to the worker
    except Exception:
        # Broker offline: the scan stays queued and can be picked up later. Never
        # fail the submission over infra — the record is already persisted.
        pass
    return RedirectResponse(f"/app/scans/{scan_id}", status_code=303)


# --- Map mode: Online Identity Mapping (no Opus; build the graph from signals) ---


@router.get("/app/map/new", response_class=HTMLResponse)
def map_new_form(request: Request):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    if not can_run_scan(user):
        return _render(request, "locked.html")
    return _render(request, "map_new.html", multi=_MAP_MULTI, single=_MAP_SINGLE,
                   cap=_MAP_PER_TYPE_CAP, error=None)


@router.post("/app/map/new", response_class=HTMLResponse)
async def map_new_submit(request: Request):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    if not can_run_scan(user):
        return _render(request, "locked.html")

    form = await request.form()
    _check_csrf(request, form.get("csrf"))

    identifiers: list[Identifier] = []
    # Multi-value types: any number of fields named e.g. "email" (capped).
    for kind in _MAP_MULTI:
        seen = 0
        for raw in form.getlist(kind):
            v = str(raw).strip()
            if v and seen < _MAP_PER_TYPE_CAP:
                identifiers.append(Identifier(type=InputType(kind), value=v,
                                              ownership_verified=True))
                seen += 1
    for kind in _MAP_SINGLE:
        v = str(form.get(kind, "")).strip()
        if v:
            identifiers.append(Identifier(type=InputType(kind), value=v,
                                          ownership_verified=True))
    photo = form.get("photo")
    if photo is not None and getattr(photo, "filename", ""):
        try:
            identifiers.append(Identifier(type=InputType.PHOTO, value=await _save_photo(photo),
                                          ownership_verified=True))
        except ValueError:
            pass  # a bad photo never blocks the rest of the map

    if not identifiers:
        return _render(request, "map_new.html", multi=_MAP_MULTI, single=_MAP_SINGLE,
                       cap=_MAP_PER_TYPE_CAP, error="Add at least one input to map.")
    if not user.is_admin and not form.get("own"):
        return _render(request, "map_new.html", multi=_MAP_MULTI, single=_MAP_SINGLE,
                       cap=_MAP_PER_TYPE_CAP,
                       error="Please confirm these are yours — Arescope is self-audit only.")

    name = str(form.get("scan_name", "")).strip()[:80] or None
    subject_id = create_subject(identifiers, user_id=user.id)
    scan_id = create_scan(subject_id, options={"mode": "map"}, name=name)
    try:
        run_map_task.delay(scan_id)
    except Exception:
        pass
    return RedirectResponse(f"/app/map/scan/{scan_id}", status_code=303)


@router.get("/app/map/scan/{scan_id}", response_class=HTMLResponse)
def map_scan_view(request: Request, scan_id: str):
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    info = _load_owned_scan(user, scan_id)
    if info is None:
        raise HTTPException(404, "map not found")
    elements = build_map_graph(scan_id, label=user.username or "you")
    return _render(request, "map.html", elements=elements, scope="map",
                   scan=scan_id, scan_status=info["status"], scan_name=info.get("name"),
                   analysis=info.get("analysis"))


@router.get("/app/map/scan/{scan_id}/status")
def map_scan_status(request: Request, scan_id: str) -> dict:
    user = current_user(request)
    if user is None:
        return {"status": "unknown"}
    info = _load_owned_scan(user, scan_id)
    if info is None:
        return {"status": "unknown"}
    return {"status": info["status"], "phase": info.get("phase")}


@router.get("/app/map/scan/{scan_id}/graph")
def map_scan_graph(request: Request, scan_id: str) -> dict:
    """Live graph snapshot — polled while the map builds so the client can add the
    new nodes/edges that have landed since the last poll (streaming)."""
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    info = _load_owned_scan(user, scan_id)
    if info is None:
        raise HTTPException(404)
    return {"status": info["status"], "phase": info.get("phase"),
            "elements": build_map_graph(scan_id, label=user.username or "you")}


@router.post("/app/map/scan/{scan_id}/add", response_class=HTMLResponse)
async def map_scan_add(request: Request, scan_id: str):
    """Append more inputs to an existing identity map and re-run it (the graph's
    'Add to identity' action), so one map grows instead of spawning new ones."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))

    new: list[Identifier] = []
    for kind in _MAP_MULTI + _MAP_SINGLE:
        for raw in form.getlist(kind):
            v = str(raw).strip()
            if v:
                new.append(Identifier(type=InputType(kind), value=v, ownership_verified=True))
    photo = form.get("photo")
    if photo is not None and getattr(photo, "filename", ""):
        try:
            new.append(Identifier(type=InputType.PHOTO, value=await _save_photo(photo),
                                  ownership_verified=True))
        except ValueError:
            pass

    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            raise HTTPException(404, "map not found")
        subject = s.get(models.Subject, scan.subject_id)
        if subject is None or (subject.user_id != user.id and not user.is_admin):
            raise HTTPException(404, "map not found")
        for ident in new:
            s.add(models.Identifier(subject_id=subject.id, type=ident.type.value,
                                    value=ident.value, ownership_verified=True))
        # Re-run from scratch over the now-larger identity (cheap: no Opus).
        s.query(models.Signal).filter(models.Signal.scan_id == scan_id).delete()
        scan.status = "queued"
    try:
        run_map_task.delay(scan_id)
    except Exception:
        pass
    return RedirectResponse(f"/app/map/scan/{scan_id}", status_code=303)


@router.post("/app/map/scan/{scan_id}/rerun", response_class=HTMLResponse)
async def map_scan_rerun(request: Request, scan_id: str):
    """Re-run a map over the SAME inputs to see whether changes the user made (e.g.
    deleting a profile, opting out of a broker) actually shrank their footprint. A
    fresh scan is created over the existing subject, so the old map is preserved and
    the two can be compared — nothing is overwritten."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    if not can_run_scan(user):
        return _render(request, "locked.html")
    form = await request.form()
    _check_csrf(request, form.get("csrf"))

    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            raise HTTPException(404, "map not found")
        subject = s.get(models.Subject, scan.subject_id)
        if subject is None or (subject.user_id != user.id and not user.is_admin):
            raise HTTPException(404, "map not found")
        subject_id = subject.id
        name = scan.name

    new_scan_id = create_scan(subject_id, options={"mode": "map"}, name=name)
    try:
        run_map_task.delay(new_scan_id)
    except Exception:
        pass
    return RedirectResponse(f"/app/map/scan/{new_scan_id}", status_code=303)


@router.post("/app/map/scan/{scan_id}/evaluate")
async def map_scan_evaluate(request: Request, scan_id: str,
                            background_tasks: BackgroundTasks) -> dict:
    """Kick off Opus Evaluate (inference over the whole footprint). Gated — it's an LLM
    cost. Runs in the worker; the client polls /analysis for the result."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        raise HTTPException(403)
    if not can_run_scan(user):
        raise HTTPException(403, "not permitted")
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    if _load_owned_scan(user, scan_id) is None:
        raise HTTPException(404)
    try:
        evaluate_map_task.delay(scan_id)
    except BrokerError:
        # No broker (e.g. tests / single-process dev): run it as a background task so the
        # slow Opus call doesn't block the event loop. FastAPI runs it in a threadpool.
        background_tasks.add_task(evaluate_and_store_map, scan_id)
    return {"status": "running"}


@router.get("/app/map/scan/{scan_id}/analysis")
def map_scan_analysis(request: Request, scan_id: str) -> dict:
    """Poll target: returns the stored Evaluate result once ready (else ready=false)."""
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    info = _load_owned_scan(user, scan_id)
    if info is None:
        raise HTTPException(404)
    analysis = info.get("analysis")
    return {"ready": analysis is not None, "analysis": analysis}


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


# Human labels for the raw-evidence panel, and which raw fields to surface first
# per source (the rest stay in the full-JSON details). Lets a user check, e.g.,
# whether an infostealer's machine name is one of their devices (feedback #1).
_SOURCE_LABEL = {
    "hibp": "Have I Been Pwned",
    "hudsonrock": "Hudson Rock — infostealer log",
    "shodan": "Shodan",
    "holehe": "Holehe",
    "maigret": "Maigret",
    "brokers": "People-search / data-broker",
    "github": "GitHub",
    "reddit": "Reddit",
    "gravatar": "Gravatar",
    "ghunt": "Google account (GHunt)",
    "brave": "Web search (Brave)",
}
_EVIDENCE_HINTS: dict[str, list[tuple[str, str]]] = {
    "hudsonrock": [
        ("computer_name", "Machine name"),
        ("date_compromised", "Compromised"),
        ("malware_path", "Malware path"),
        ("antiviruses", "Antivirus present"),
        ("ip", "Machine IP"),
        ("url", "Login URL"),
    ],
    "hibp": [("title", "Breach"), ("breach_date", "Date"), ("data_classes", "Leaked data")],
    "shodan": [
        # service signals
        ("port", "Port"), ("product", "Service"), ("vulns", "Known CVEs"),
        # host_profile signal
        ("location", "Location"), ("isp", "ISP"), ("org", "Network"), ("asn", "ASN"),
        ("hostnames", "Hostnames"), ("open_ports", "Open ports"),
    ],
    "holehe": [("url", "Site")],
    "maigret": [("url", "Profile")],
    "github": [("url", "Profile"), ("public_repos", "Public repos"),
               ("followers", "Followers"), ("created_at", "Joined")],
    "reddit": [("url", "Profile"), ("total_karma", "Karma")],
    "gravatar": [("url", "Profile"), ("handle", "Handle")],
    "brave": [("title", "Page"), ("domain", "Site"), ("description", "Snippet")],
    "brokers": [
        ("broker", "Broker"),
        ("listing_url", "Listing"),
        ("opt_out_url", "Opt-out"),
        ("match_confidence", "Match confidence"),
        ("ca_registered", "CA-registered broker"),
    ],
}


def _humanize_signal(sig: models.Signal) -> dict:
    """One raw signal as a readable evidence row: key highlights + the full payload."""
    raw = sig.raw or {}
    highlights: list[tuple[str, str]] = []
    # Identity attributes share one shape across connectors (attribute/value/platform),
    # so render them uniformly instead of per-source hints.
    if sig.kind == "identity_attribute":
        attr = str(raw.get("attribute", "detail")).capitalize()
        val = str(raw.get("value", ""))
        highlights.append((attr, val))
        if raw.get("platform"):
            highlights.append(("Found on", str(raw["platform"])))
        return {
            "source_label": _SOURCE_LABEL.get(sig.source, sig.source),
            "locator": sig.locator,
            "highlights": highlights,
            "raw_json": json.dumps(raw, indent=2, default=str, ensure_ascii=False),
        }
    for key, label in _EVIDENCE_HINTS.get(sig.source, []):
        val = raw.get(key)
        if val in (None, "", [], {}):
            continue
        highlights.append((label, ", ".join(map(str, val)) if isinstance(val, list) else str(val)))
    return {
        "source_label": _SOURCE_LABEL.get(sig.source, sig.source),
        "locator": sig.locator,
        "highlights": highlights,
        "raw_json": json.dumps(raw, indent=2, default=str, ensure_ascii=False),
    }


def _finding_photo(f: models.Finding, signals_by_id: dict) -> dict | None:
    """If this finding has a profile-photo signal, hand the template a proxied image URL
    + whether it's a default monogram (vs a real uploaded picture), so the card can show
    the actual image instead of just saying 'a photo is public'."""
    for sid in f.signal_ids or []:
        sig = signals_by_id.get(sid)
        raw = (sig.raw or {}) if sig else {}
        if sig and sig.kind == "identity_attribute" and raw.get("attribute") == "photo":
            ref = raw.get("url") or raw.get("value")
            if not ref:
                continue
            return {
                "is_default": bool(raw.get("is_default")),
                "platform": raw.get("platform") or "the web",
                "proxy_url": "/app/photo?u=" + quote(str(ref), safe=""),
            }
    return None


def _finding_view(f: models.Finding, signals_by_id: dict | None = None) -> dict:
    """Flatten a Finding row into everything the results template needs."""
    rem = f.remediation
    signals_by_id = signals_by_id or {}
    evidence = [
        _humanize_signal(signals_by_id[sid])
        for sid in (f.signal_ids or [])
        if sid in signals_by_id
    ]
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
        "problem": f.problem,
        "rationale": f.rationale,
        "confidence": round((f.confidence or 0) * 100),
        "fix_difficulty": f.fix_difficulty,
        "easy_fix": f.easy_fix,
        "photo": _finding_photo(f, signals_by_id),
        "members": f.member_locators or [],
        "evidence": evidence,
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
            # advice exists but no request drafted yet, and this category's track
            # uses one (T1) → offer the explicit "draft the request" second step.
            "can_draft_artifact": rem.tier == "t1_artifact" and not rem.artifact,
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
        # The raw signals behind these findings, so each card can show the exact
        # entry Opus saw (feedback #1: "is this infostealer machine mine?").
        signals = s.query(models.Signal).filter(models.Signal.scan_id == scan_id).all()
        signals_by_id = {sig.id: sig for sig in signals}
        views = sorted(
            (_finding_view(f, signals_by_id) for f in findings),
            key=lambda v: (-v["rank"], -v["confidence"]),
        )
        snap = scan.config_snapshot or {}
        # Severity tabs (only those present), so a long report isn't one flat wall.
        counts: dict[str, int] = {}
        for v in views:
            counts[v["severity"]] = counts.get(v["severity"], 0) + 1
        tabs = [
            {"sev": sev, "label": _SEV_LABEL[sev], "count": counts[sev]}
            for sev in ("critical", "high", "medium", "low", "info")
            if counts.get(sev)
        ]
        return {
            "id": scan.id,
            "name": scan.name,
            "status": scan.status,
            "started_at": scan.started_at,
            "options": scan.options or {},
            "analysis": scan.analysis,
            "phase": snap.get("phase"),
            "coverage_gaps": snap.get("coverage_gaps", []),
            # Did any input actually have a source that searched it? (e.g. a name-only
            # scan searches nothing — a clean report must not claim "Nothing exposed".)
            # Missing key = legacy scan from before we tracked this → assume it searched.
            "searched_anything": (
                "searched_types" not in snap or bool(snap.get("searched_types"))
            ),
            "findings": views,
            "sev_tabs": tabs,
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


@router.post("/app/scans/{scan_id}/rename")
async def scan_rename(request: Request, scan_id: str):
    """Rename an analysis from the dashboard or results header."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    if _load_owned_scan(user, scan_id) is None:
        raise HTTPException(404, "scan not found")
    name = str(form.get("name", "")).strip()[:80] or None
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is not None:
            scan.name = name
    if _wants_json(request):
        return JSONResponse({"ok": True, "name": name or ""})
    back = _safe_next(str(form.get("next", "")) or f"/app/scans/{scan_id}")
    return RedirectResponse(back, status_code=303)


@router.post("/app/scans/{scan_id}/map-visibility")
async def scan_map_visibility(request: Request, scan_id: str):
    """Toggle whether this analysis feeds the whole-account exposure map.

    Lets a user keep a scan (e.g. a friend's, run with their consent) out of their
    own identity graph. Stored on Scan.options so build_account_graph can skip it.
    """
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    if _load_owned_scan(user, scan_id) is None:
        raise HTTPException(404, "scan not found")
    # include=='1' => part of the map; anything else => excluded.
    include = str(form.get("include", "")) == "1"
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is not None:
            opts = dict(scan.options or {})
            if include:
                opts.pop("exclude_from_map", None)
            else:
                opts["exclude_from_map"] = True
            scan.options = opts
    if _wants_json(request):
        return JSONResponse({"ok": True, "in_map": include})
    back = _safe_next(str(form.get("next", "")) or "/app")
    return RedirectResponse(back, status_code=303)


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


@router.post("/app/findings/{finding_id}/artifact")
async def finding_artifact(request: Request, finding_id: str):
    """Draft the ready-to-send request (GDPR/opt-out/takedown) on demand — the
    explicit second step after advice, so Arescope never auto-sends on the user's
    behalf."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    scan_id = _finding_scan_id(user, finding_id)
    if scan_id is None:
        raise HTTPException(404, "finding not found")
    if not can_run_scan(user):  # drafting is an LLM cost — gate it
        return _render(request, "locked.html")
    try:
        generate_finding_artifact(finding_id)
    except ValueError:
        raise HTTPException(404, "finding not found")
    return RedirectResponse(f"/app/scans/{scan_id}#f-{finding_id}", status_code=303)


@router.get("/app/findings/{finding_id}/chat")
def finding_chat_history(request: Request, finding_id: str):
    """Load the Ask-Opus thread for a finding (JSON; free)."""
    user = current_user(request)
    if user is None or _finding_scan_id(user, finding_id) is None:
        raise HTTPException(404, "finding not found")
    return JSONResponse({"messages": load_chat(user.id, f"finding:{finding_id}")})


@router.post("/app/findings/{finding_id}/chat")
async def finding_chat_send(request: Request, finding_id: str):
    """Ask Opus about a finding (JSON {reply}). Gated — it's an Opus call."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        raise HTTPException(401, "login required")
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    if _finding_scan_id(user, finding_id) is None:
        raise HTTPException(404, "finding not found")
    if not can_run_scan(user):
        raise HTTPException(403, "scan access required")
    question = str(form.get("message", "")).strip()[:2000]
    if not question:
        raise HTTPException(400, "empty message")
    return JSONResponse({"reply": send_finding_chat(user.id, finding_id, question)})


@router.get("/app/map/chat")
def map_chat_history(request: Request, scan_id: str = ""):
    """Load the Ask-Opus thread for the map (a scan's, or the account's)."""
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "login required")
    if scan_id and _load_owned_scan(user, scan_id) is None:
        raise HTTPException(404, "scan not found")
    scope = f"map:scan:{scan_id}" if scan_id else "map:account"
    return JSONResponse({"messages": load_chat(user.id, scope)})


@router.post("/app/map/chat")
async def map_chat_send(request: Request):
    """Ask Opus about the exposure map (JSON {reply}). Gated."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        raise HTTPException(401, "login required")
    form = await request.form()
    _check_csrf(request, form.get("csrf"))
    scan_id = str(form.get("scan_id", "")).strip()
    if scan_id and _load_owned_scan(user, scan_id) is None:
        raise HTTPException(404, "scan not found")
    if not can_run_scan(user):
        raise HTTPException(403, "scan access required")
    question = str(form.get("message", "")).strip()[:2000]
    if not question:
        raise HTTPException(400, "empty message")
    selection = [s for s in str(form.get("selection", "")).split("|") if s][:25]
    reply = send_map_chat(user.id, scan_id or None, question, selection)
    return JSONResponse({"reply": reply})


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


# --- exposure map (graph) ----------------------------------------------------

_LOGO_CACHE = os.path.join(APP_STATIC_DIR, "logocache")


@router.get("/app/password", response_class=HTMLResponse)
def password_check(request: Request):
    """Check a password against HIBP's Pwned Passwords.

    The check is done ENTIRELY in the browser via k-anonymity: the page SHA-1s the
    password locally and sends only the first 5 hex chars to api.pwnedpasswords.com.
    The password never touches our server, so there's no POST and nothing to store
    or log. Zero cost to us, so it's open to any verified user (not run-gated)."""
    user = _require_verified(request)
    if isinstance(user, RedirectResponse):
        return user
    return _render(request, "password.html")


def _latest_map_scan_id(user: models.User) -> str | None:
    """Most recent map-mode scan the user owns (powers the 'Identity map' nav link)."""
    with session_scope() as s:
        rows = (
            s.query(models.Scan.id, models.Scan.options)
            .join(models.Subject, models.Scan.subject_id == models.Subject.id)
            .filter(models.Subject.user_id == user.id)
            .order_by(models.Scan.started_at.desc())
            .all()
        )
    for sid, opts in rows:
        if (opts or {}).get("mode") == "map":
            return sid
    return None


@router.get("/app/map")
def map_home(request: Request):
    """Identity-map entry point: open the user's most recent map. Only fall through to
    the builder when they have none yet (feedback: the nav link dead-ended on the
    'build new' form instead of showing the map you already made)."""
    user = current_user(request)
    if user is not None:
        latest = _latest_map_scan_id(user)
        if latest:
            return RedirectResponse(f"/app/map/scan/{latest}", status_code=303)
    return RedirectResponse("/app/map/new", status_code=303)


@router.get("/app/logo/{slug}")
def logo_proxy(slug: str):
    """Serve a brand logo, cached on our own origin (no per-render third-party
    call from the user's browser). Fetched once from Simple Icons; 404 => the map
    falls back to a monogram. Slug is sanitised, source is fixed (no SSRF)."""
    safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:40]
    if not safe:
        raise HTTPException(404)
    os.makedirs(_LOGO_CACHE, exist_ok=True)
    path = os.path.join(_LOGO_CACHE, f"{safe}.svg")
    if not os.path.exists(path):
        try:
            r = httpx.get(f"https://cdn.simpleicons.org/{safe}", timeout=10)
        except httpx.HTTPError:
            raise HTTPException(404)
        if r.status_code != 200 or "svg" not in r.headers.get("content-type", ""):
            raise HTTPException(404)
        with open(path, "wb") as fh:
            fh.write(r.content)
    return FileResponse(path, media_type="image/svg+xml")


_PHOTO_CACHE = os.path.join(APP_STATIC_DIR, "photocache")
# Only proxy images from the hosts our connectors surface photos from. Fixed allow-list
# => no open proxy / SSRF, and the user's browser never calls these third parties directly.
_PHOTO_HOSTS = {
    "lh3.googleusercontent.com",            # Google account photo (GHunt)
    "avatars.githubusercontent.com",         # GitHub avatar
    "gravatar.com", "www.gravatar.com", "secure.gravatar.com",  # Gravatar
    "media.licdn.com",                       # LinkedIn profile photo (Apify enrichment)
}
# Instagram serves photos from dynamic CDN subdomains (scontent-*.cdninstagram.com,
# *.fbcdn.net), so allow by parent-domain SUFFIX rather than an exact host. Still a fixed
# set of CDNs (no open proxy / SSRF) — just not a single static hostname.
_PHOTO_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net")


def _photo_host_allowed(host: str) -> bool:
    return host in _PHOTO_HOSTS or any(
        host == s or host.endswith("." + s) for s in _PHOTO_HOST_SUFFIXES)


@router.get("/app/photo")
def photo_proxy(request: Request, u: str):
    """Serve a public profile photo through our own origin (cached), so a real face we
    found is visible in the finding/map WITHOUT the browser hitting Google/Gravatar
    directly. Auth-gated; host is allow-listed (no SSRF); cached by URL hash."""
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    host = (urlparse(u).hostname or "").lower()
    if not _photo_host_allowed(host):
        raise HTTPException(404)
    os.makedirs(_PHOTO_CACHE, exist_ok=True)
    key = hashlib.sha1(u.encode()).hexdigest()[:24]  # noqa: S324 (cache key, not security)
    for ext, mt in ((".jpg", "image/jpeg"), (".png", "image/png")):
        cached = os.path.join(_PHOTO_CACHE, key + ext)
        if os.path.exists(cached):
            return FileResponse(cached, media_type=mt)
    try:
        r = httpx.get(u, timeout=10, follow_redirects=True)
    except httpx.HTTPError:
        raise HTTPException(404)
    ct = r.headers.get("content-type", "")
    if r.status_code != 200 or not ct.startswith("image/"):
        raise HTTPException(404)
    ext, mt = (".png", "image/png") if "png" in ct else (".jpg", "image/jpeg")
    path = os.path.join(_PHOTO_CACHE, key + ext)
    with open(path, "wb") as fh:
        fh.write(r.content)
    return FileResponse(path, media_type=mt)
