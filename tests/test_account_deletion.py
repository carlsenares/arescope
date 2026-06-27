from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_delete_account_rows_removes_owned_data(monkeypatch):
    monkeypatch.setenv("ARESCOPE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from arescope.config import get_settings
    from arescope.db import models
    from arescope.web.routes import _delete_account_rows

    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        user = models.User(
            email="owner@example.com",
            username="owner",
            password_hash="hash",
            email_verified=True,
        )
        other = models.User(
            email="other@example.com",
            username="other",
            password_hash="hash",
            email_verified=True,
        )
        session.add_all([user, other])
        session.flush()

        subject = models.Subject(user_id=user.id, label="self")
        other_subject = models.Subject(user_id=other.id, label="self")
        session.add_all([subject, other_subject])
        session.flush()

        scan = models.Scan(subject_id=subject.id, status="complete")
        other_scan = models.Scan(subject_id=other_subject.id, status="complete")
        identifier = models.Identifier(
            subject_id=subject.id,
            type="email",
            value="owner@example.com",
            ownership_verified=True,
        )
        session.add_all([scan, other_scan, identifier])
        session.flush()

        signal = models.Signal(scan_id=scan.id, source="test", kind="account", locator="x")
        finding = models.Finding(
            scan_id=scan.id,
            signal_ids=[],
            category="account",
            severity="low",
            title="Finding",
            rationale="Because",
        )
        session.add_all([signal, finding])
        session.flush()

        session.add_all([
            models.Remediation(finding_id=finding.id, tier="t1_artifact", summary="Fix"),
            models.ChatMessage(user_id=user.id, scope="map:account", role="user", content="hi"),
            models.LoginToken(
                user_id=user.id,
                purpose="login",
                token_hash="token",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            ),
        ])
        session.commit()
        user_id = user.id
        other_id = other.id
        scan_id = scan.id
        other_scan_id = other_scan.id

        _delete_account_rows(session, user_id)
        session.commit()

        assert session.get(models.User, user_id) is None
        assert session.get(models.User, other_id) is not None
        assert session.query(models.Subject).filter_by(user_id=user_id).count() == 0
        assert session.query(models.Scan).filter_by(id=scan_id).count() == 0
        assert session.query(models.Signal).filter_by(scan_id=scan_id).count() == 0
        assert session.query(models.Finding).filter_by(scan_id=scan_id).count() == 0
        assert session.query(models.Remediation).count() == 0
        assert session.query(models.ChatMessage).filter_by(user_id=user_id).count() == 0
        assert session.query(models.LoginToken).filter_by(user_id=user_id).count() == 0
        assert session.query(models.Scan).filter_by(id=other_scan_id).count() == 1
    finally:
        session.close()
        get_settings.cache_clear()
