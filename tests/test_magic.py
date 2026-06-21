"""Magic-link token primitives + the run-lock predicate (pure logic, no DB)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from arescope.auth import can_run_scan
from arescope.magic import generate_token, hash_token, is_expired


def test_hash_is_stable_and_not_the_raw_token():
    raw = "some-secret-token"
    h = hash_token(raw)
    assert h == hash_token(raw)  # deterministic
    assert h != raw  # never store the raw value
    assert len(h) == 64  # sha-256 hex


def test_generated_tokens_are_unique_and_self_consistent():
    raw1, h1 = generate_token()
    raw2, h2 = generate_token()
    assert raw1 != raw2 and h1 != h2  # high entropy → distinct
    assert hash_token(raw1) == h1 and hash_token(raw2) == h2  # hash matches raw


def test_expiry_boundary():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert is_expired(now - timedelta(seconds=1), now=now) is True
    assert is_expired(now + timedelta(minutes=5), now=now) is False
    assert is_expired(now, now=now) is True  # exactly at expiry counts as expired


def test_expiry_tolerates_naive_datetime():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    naive_future = datetime(2026, 1, 1, 12, 30)  # no tzinfo → treated as UTC
    assert is_expired(naive_future, now=now) is False


def test_run_lock_predicate():
    assert can_run_scan(None) is False
    assert can_run_scan(SimpleNamespace(is_admin=False, can_scan=False)) is False
    assert can_run_scan(SimpleNamespace(is_admin=False, can_scan=True)) is True
    assert can_run_scan(SimpleNamespace(is_admin=True, can_scan=False)) is True
