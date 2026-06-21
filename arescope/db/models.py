"""Persistence model (ARCHITECTURE.md §3) — portability-first.

Portability rules baked in so the private->service shift is additive:
  * user_id is a NULLABLE FK everywhere (P1 just starts populating + enforcing it).
  * subject identity is a row, never a singleton (multi-tenant = filter by user_id).
  * ownership_verified exists from day one (gate flips from always-true to must-be-true).
  * config_snapshot records which sources ran (reproducibility + honest coverage).
  * notable PII columns use EncryptedString; every scan carries expires_at (TTL).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from arescope.config import get_settings
from arescope.db.crypto import EncryptedString


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry() -> datetime:
    return _now() + timedelta(days=get_settings().retention_days)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # Account identity. email/username are unique; lookups use the lowercased form.
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)  # profile
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # email_verified flips when magic-link / verification lands (additive, P1).
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Run-lock: may this account start a (cost-incurring) scan? Default off — admins
    # always may; admins grant it per-user from the dashboard. Becomes the paywall
    # hook later (plan/quota slot in here without a restructure).
    can_scan: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    subjects: Mapped[list["Subject"]] = relationship(back_populates="user")


class LoginToken(Base):
    """Single-use, hashed magic-link token — passwordless login + email verification.

    We persist only a SHA-256 of the raw token (the raw value lives only in the
    emailed URL), so a DB read can't mint a working link. Each token is single-use
    (used_at) and time-boxed (expires_at); purpose separates 'login' from 'verify'.
    """

    __tablename__ = "login_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String)  # "login" | "verify"
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Subject(Base):
    """The person/identity being scanned (you, in P0)."""

    __tablename__ = "subjects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    label: Mapped[str] = mapped_column(String, default="self")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User | None"] = relationship(back_populates="subjects")
    identifiers: Mapped[list["Identifier"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    scans: Mapped[list["Scan"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class Identifier(Base):
    __tablename__ = "identifiers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"))
    type: Mapped[str] = mapped_column(String)  # InputType value
    value: Mapped[str] = mapped_column(EncryptedString)  # PII — encrypted at rest
    ownership_verified: Mapped[bool] = mapped_column(default=True)  # asserted in P0

    subject: Mapped["Subject"] = relationship(back_populates="identifiers")


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"))
    status: Mapped[str] = mapped_column(String, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_expiry)
    # which connectors/keys ran + coverage gaps — reproducibility + honest reporting
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # per-scan run options chosen at submit time (e.g. {"maigret_top_sites": 50}).
    options: Mapped[dict] = mapped_column(JSON, default=dict)

    subject: Mapped["Subject"] = relationship(back_populates="scans")
    signals: Mapped[list["Signal"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"))
    source: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    locator: Mapped[str] = mapped_column(String)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scan: Mapped["Scan"] = relationship(back_populates="signals")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"))
    signal_ids: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Verdict fields (AI_PIPELINE.md): action bucket, inline easy fix, contingency
    # questions, and the clustered locators this finding rolls up.
    action: Mapped[str] = mapped_column(String, default="no_action")
    fix_difficulty: Mapped[str | None] = mapped_column(String, nullable=True)
    easy_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    member_locators: Mapped[list] = mapped_column(JSON, default=list)
    # The cluster's subject — needed to reconstruct a Verdict+cluster for the
    # on-demand involved remediation (subject_value is PII -> encrypted at rest).
    subject_type: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_value: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)

    scan: Mapped["Scan"] = relationship(back_populates="findings")
    remediation: Mapped["Remediation | None"] = relationship(
        back_populates="finding", cascade="all, delete-orphan", uselist=False
    )


class Remediation(Base):
    __tablename__ = "remediations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    tier: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    artifact: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)  # PII
    status: Mapped[str] = mapped_column(String, default="proposed")  # P2 execution state

    finding: Mapped["Finding"] = relationship(back_populates="remediation")
