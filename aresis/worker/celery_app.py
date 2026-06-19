"""Celery app — Redis broker/backend, mirrors the InsureAI api+worker split."""

from __future__ import annotations

from celery import Celery

from aresis.config import get_settings

_cfg = get_settings()

celery_app = Celery(
    "aresis",
    broker=_cfg.redis_url,
    backend=_cfg.redis_url,
    include=["aresis.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
