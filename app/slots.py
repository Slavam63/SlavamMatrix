import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from celery import Celery

import app
from app.models import Slot, User, JobRequest, Task


SLOT_STEP_MINUTES = 15
SLOT_HORIZON_HOURS = 24
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

_celery_sender = None


def get_celery_sender():
    global _celery_sender

    if _celery_sender is None:
        redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        _celery_sender = Celery(
            "matrix_parser_sender",
            broker=redis_url,
            backend=redis_url,
        )

    return _celery_sender


def round_up_to_next_slot(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % SLOT_STEP_MINUTES

    if remainder == 0:
        return dt

    return dt + timedelta(minutes=(SLOT_STEP_MINUTES - remainder))


def _get_slot_window_utc():
    now_moscow = datetime.now(MOSCOW_TZ)
    first_slot_moscow = round_up_to_next_slot(now_moscow)
    last_slot_moscow = first_slot_moscow + timedelta(hours=SLOT_HORIZON_HOURS)

    first_slot_utc = first_slot_moscow.astimezone(timezone.utc)
    last_slot_utc = last_slot_moscow.astimezone(timezone.utc)

    return first_slot_utc, last_slot_utc


def ensure_slots():
    db = app.db_session
    first_slot_utc, last_slot_utc = _get_slot_window_utc()

    existing_slots = {
        slot.slot_time
        for slot in db.query(Slot).filter(
            Slot.slot_time >= first_slot_utc,
            Slot.slot_time < last_slot_utc,
        ).all()
    }

    current = first_slot_utc
    created = 0

    while current < last_slot_utc:
        if current not in existing_slots:
            db.add(Slot(slot_time=current, status="free"))
            created += 1
        current += timedelta(minutes=SLOT_STEP_MINUTES)

    if created > 0:
        db.commit()

    return created


def get_slots_list():
    db = app.db_session
    first_slot_utc, last_slot_utc = _get_slot_window_utc()

    slots = (
        db.query(Slot)
        .filter(Slot.slot_time >= first_slot_utc, Slot.slot_time < last_slot_utc)
        .order_by(Slot.slot_time.asc())
        .all()
    )

    result = []
    for slot in slots:
        slot_time_utc = slot.slot_time
        slot_time_moscow = slot_time_utc.astimezone(MOSCOW_TZ)

        result.append(
            {
                "id": slot.id,
                "slot_time": slot_time_utc.isoformat(),
                "slot_time_moscow": slot_time_moscow.isoformat(),
                "time_label": slot_time_moscow.strftime("%H:%M"),
                "status": slot.status,
                "reserved_by": slot.reserved_by,
            }
        )

    return result


def _has_active_queue_before_new_task(job_request_id: int) -> bool:
    db = app.db_session

    active_task = (
        db.query(Task)
        .filter(
            Task.job_request_id != job_request_id,
            Task.status.in_(["queued", "running"]),
        )
        .order_by(Task.created_at.asc(), Task.id.asc())
        .first()
    )

    return active_task is not None


def reserve_slot(job_request_id: int, slot_id: int):
    db = app.db_session

    job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
    if not job_request:
        raise ValueError("job request not found")

    if job_request.status != "slot_selection":
        raise ValueError("job request is not ready for slot reservation")

    active_task = (
        db.query(Task)
        .filter(
            Task.job_request_id == job_request.id,
            Task.status.in_(["queued", "running"]),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .first()
    )
    if active_task:
        raise ValueError("job request already has an active task")

    user = db.query(User).filter(User.id == job_request.user_id).first()
    if not user:
        raise ValueError("user not found")

    slot = db.query(Slot).filter(Slot.id == slot_id).first()
    if not slot:
        raise ValueError("slot not found")

    if slot.status != "free":
        raise ValueError("slot is not available")

    has_queue_before = _has_active_queue_before_new_task(job_request.id)

    slot.status = "reserved"
    slot.reserved_by = user.id
    slot.job_request_id = job_request.id

    job_request.status = "queued"

    task = Task(
        job_request_id=job_request.id,
        status="queued",
        progress=0,
        found_vacancies=0,
    )
    db.add(task)
    db.commit()

    celery_client = get_celery_sender()

    async_result = celery_client.send_task(
        "app.tasks.process_job_request",
        args=[task.id],
    )

    task.celery_task_id = async_result.id
    db.commit()

    next_page = "waiting" if has_queue_before else "parsing"

    return {
        "slot_id": slot.id,
        "slot_time": slot.slot_time.isoformat(),
        "slot_time_moscow": slot.slot_time.astimezone(MOSCOW_TZ).isoformat(),
        "time_label": slot.slot_time.astimezone(MOSCOW_TZ).strftime("%H:%M"),
        "job_request_id": job_request.id,
        "task_id": task.id,
        "celery_task_id": task.celery_task_id,
        "status": job_request.status,
        "next_page": next_page,
        "start_immediately": not has_queue_before,
    }
