from datetime import datetime, timezone
from decimal import Decimal
import re

from celery import Celery
from sqlalchemy import desc

import app
from app import create_app
from app.models import JobRequest, SearchAttempt, SearchSession, Slot, Task, Vacancy
from app.parser import run_parser


flask_app = create_app()

celery_app = Celery(
    "matrix_parser",
    broker=flask_app.config["REDIS_URL"],
    backend=flask_app.config["REDIS_URL"],
)

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="celery",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    enable_utc=True,
)


def _get_reserved_slot_for_job_request(job_request_id: int):
    db = app.db_session

    return (
        db.query(Slot)
        .filter(
            Slot.job_request_id == job_request_id,
            Slot.status == "reserved",
        )
        .order_by(Slot.id.desc())
        .first()
    )


def _normalize_ai_text(value):
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_ai_tags(item: dict):
    text = " ".join([
        str(item.get("title") or ""),
        str(item.get("description") or ""),
        str(item.get("salary") or ""),
        str(item.get("location") or ""),
        str(item.get("company") or ""),
    ]).lower()

    tags = []

    tag_rules = [
        ("remote", ["remote", "удален", "удалён"]),
        ("fastapi", ["fastapi"]),
        ("django", ["django"]),
        ("flask", ["flask"]),
        ("postgresql", ["postgresql", "postgres"]),
        ("redis", ["redis"]),
        ("kafka", ["kafka"]),
        ("docker", ["docker"]),
        ("fullstack", ["fullstack", "full stack", "full-stack"]),
        ("backend", ["backend", "back-end", "бэкенд", "backend-разработчик", "backend developer"]),
        ("senior", ["senior", "lead", "старший", "ведущий"]),
        ("office", ["офис", "office"]),
        ("moscow", ["москва", "moscow"]),
    ]

    for tag, markers in tag_rules:
        if any(marker in text for marker in markers):
            tags.append(tag)

    return ",".join(tags)


def _calculate_ai_score(item: dict):
    score = Decimal("50.00")

    title_text = _normalize_ai_text(item.get("title"))
    description_text = _normalize_ai_text(item.get("description"))
    salary_text = _normalize_ai_text(item.get("salary"))
    location_text = _normalize_ai_text(item.get("location"))
    url_text = _normalize_ai_text(item.get("url"))

    if "python" in title_text:
        score += Decimal("15.00")
    if "backend" in title_text or "back-end" in title_text or "бэкенд" in title_text:
        score += Decimal("12.00")
    if "fastapi" in title_text or "django" in title_text or "flask" in title_text:
        score += Decimal("8.00")

    if "python" in description_text:
        score += Decimal("5.00")
    if any(token in description_text for token in ["fastapi", "django", "flask", "postgresql", "postgres", "redis", "kafka", "docker"]):
        score += Decimal("4.00")

    if salary_text:
        score += Decimal("3.00")
    if location_text:
        score += Decimal("1.00")
    if url_text.startswith("https://hh.ru/"):
        score += Decimal("2.00")

    if any(token in title_text for token in ["fullstack", "full stack", "full-stack"]):
        score -= Decimal("6.00")
    if any(token in description_text for token in ["javascript", "typescript", "node", "node.js", "php", "java", "golang"]):
        score -= Decimal("5.00")

    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("100.00"):
        score = Decimal("100.00")

    return score.quantize(Decimal("0.01"))


def _safe_join_query_parts(*parts):
    cleaned = []
    seen = set()

    for part in parts:
        value = str(part or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(value)

    return " | ".join(cleaned)


def _get_or_create_search_session(db, job_request: JobRequest) -> SearchSession:
    existing = (
        db.query(SearchSession)
        .filter(SearchSession.job_request_id == job_request.id)
        .order_by(desc(SearchSession.created_at), desc(SearchSession.id))
        .first()
    )
    if existing:
        return existing

    normalized_query = _safe_join_query_parts(
        job_request.position,
        job_request.query_text,
        job_request.keywords,
    )

    session = SearchSession(
        user_id=job_request.user_id,
        job_request_id=job_request.id,
        initial_query=job_request.query_text or job_request.position or job_request.keywords,
        normalized_query=normalized_query,
        normalized_position=job_request.position,
        normalized_industry=job_request.query_text,
        normalized_location=job_request.location,
        strategy_version="v1_memory_bootstrap",
        status="running",
    )
    db.add(session)
    db.flush()
    return session


def _guess_primary_source(job_request: JobRequest, vacancies_data: list[dict]) -> str:
    configured_source = (job_request.vacancy_source or "").strip()
    if configured_source:
        return configured_source

    for item in vacancies_data:
        source = (item.get("source") or "").strip()
        if source:
            return source

    return "hh"


def _create_search_attempt(db, search_session: SearchSession, source: str, job_request: JobRequest) -> SearchAttempt:
    query_variant = _safe_join_query_parts(
        job_request.position,
        job_request.query_text,
        job_request.keywords,
        job_request.location,
    )

    filters_json = {
        "location": job_request.location,
        "employment_type": job_request.employment_type,
        "work_format": job_request.work_format,
        "remote": bool(job_request.remote),
        "salary_min": str(job_request.salary_min) if job_request.salary_min is not None else None,
        "salary_max": str(job_request.salary_max) if job_request.salary_max is not None else None,
        "display_period": job_request.display_period,
        "sort_order": job_request.sort_order,
    }

    attempt = SearchAttempt(
        search_session_id=search_session.id,
        source=source or "unknown",
        query_variant=query_variant,
        filters_json=str(filters_json),
        results_count=0,
        relevant_results_count=0,
        was_successful=False,
        started_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.flush()
    return attempt


def _finalize_search_attempt(attempt: SearchAttempt, vacancies_data: list[dict], saved_scores: list[Decimal]):
    attempt.results_count = len(vacancies_data)

    relevant_count = 0
    for score in saved_scores:
        if score is not None and score >= Decimal("60.00"):
            relevant_count += 1

    attempt.relevant_results_count = relevant_count

    if saved_scores:
        attempt.top_ai_score = max(saved_scores)
        attempt.avg_ai_score = (sum(saved_scores) / Decimal(len(saved_scores))).quantize(Decimal("0.01"))
    else:
        attempt.top_ai_score = None
        attempt.avg_ai_score = None

    attempt.was_successful = attempt.results_count > 0
    attempt.finished_at = datetime.now(timezone.utc)


@celery_app.task(bind=True, name="app.tasks.process_job_request")
def process_job_request(self, task_id: int):
    db = app.db_session
    task_record = None
    search_session = None
    search_attempt = None

    try:
        task_record = db.query(Task).filter(Task.id == task_id).first()
        if not task_record:
            raise ValueError("task not found")

        job_request = (
            db.query(JobRequest)
            .filter(JobRequest.id == task_record.job_request_id)
            .first()
        )
        if not job_request:
            raise ValueError("job request not found")

        if task_record.status == "completed":
            return {
                "task_id": task_record.id,
                "job_request_id": task_record.job_request_id,
                "status": task_record.status,
                "found_vacancies": task_record.found_vacancies,
            }

        if task_record.status == "running" and task_record.started_at is not None:
            return {
                "task_id": task_record.id,
                "job_request_id": task_record.job_request_id,
                "status": task_record.status,
                "found_vacancies": task_record.found_vacancies,
            }

        task_record.celery_task_id = self.request.id
        task_record.status = "running"
        task_record.progress = 10
        task_record.started_at = datetime.now(timezone.utc)
        task_record.error_message = None

        job_request.status = "processing"

        search_session = _get_or_create_search_session(db, job_request)
        search_session.status = "running"

        db.commit()

        parser_result = run_parser(task_record.job_request_id)
        vacancies_data = parser_result.get("vacancies_found", [])

        source = _guess_primary_source(job_request, vacancies_data)
        search_attempt = _create_search_attempt(db, search_session, source, job_request)

        task_record.progress = 70
        db.commit()

        db.query(Vacancy).filter(
            Vacancy.job_request_id == task_record.job_request_id
        ).delete(synchronize_session=False)

        saved_scores = []

        for item in vacancies_data:
            ai_tags = _build_ai_tags(item)
            ai_score = _calculate_ai_score(item)
            saved_scores.append(ai_score)

            vacancy = Vacancy(
                job_request_id=task_record.job_request_id,
                source=item.get("source") or "unknown",
                external_id=item.get("external_id"),
                title=item.get("title") or "Untitled vacancy",
                company=item.get("company"),
                location=item.get("location"),
                salary=item.get("salary"),
                url=item.get("url") or "",
                description=item.get("description"),
                employment_type=item.get("employment_type"),
                remote=bool(item.get("remote", False)),
                ai_score=ai_score,
                ai_tags=ai_tags or None,
            )
            db.add(vacancy)

        if search_attempt is not None:
            _finalize_search_attempt(search_attempt, vacancies_data, saved_scores)

        if search_session is not None:
            search_session.status = "completed"
            if not (search_session.normalized_query or "").strip():
                search_session.normalized_query = _safe_join_query_parts(
                    job_request.position,
                    job_request.query_text,
                    job_request.keywords,
                )

        reserved_slot = _get_reserved_slot_for_job_request(task_record.job_request_id)
        if reserved_slot is not None:
            reserved_slot.status = "completed"

        task_record.status = "completed"
        task_record.progress = 100
        task_record.found_vacancies = len(vacancies_data)
        task_record.finished_at = datetime.now(timezone.utc)

        job_request.status = "completed"
        db.commit()

        return {
            "task_id": task_record.id,
            "job_request_id": task_record.job_request_id,
            "status": task_record.status,
            "found_vacancies": task_record.found_vacancies,
        }

    except Exception as exc:
        db.rollback()

        if task_record is not None:
            try:
                job_request = (
                    db.query(JobRequest)
                    .filter(JobRequest.id == task_record.job_request_id)
                    .first()
                )

                if search_session is None and job_request is not None:
                    search_session = _get_or_create_search_session(db, job_request)

                if search_session is not None:
                    search_session.status = "failed"
                    if search_session.notes:
                        search_session.notes = f"{search_session.notes}\n{str(exc)}"
                    else:
                        search_session.notes = str(exc)

                if search_attempt is not None:
                    search_attempt.was_successful = False
                    search_attempt.error_message = str(exc)
                    search_attempt.finished_at = datetime.now(timezone.utc)

                reserved_slot = _get_reserved_slot_for_job_request(task_record.job_request_id)
                if reserved_slot is not None:
                    reserved_slot.status = "failed"

                task_record.status = "failed"
                task_record.error_message = str(exc)
                task_record.finished_at = datetime.now(timezone.utc)

                if job_request is not None:
                    job_request.status = "failed"

                db.commit()
            except Exception:
                db.rollback()

        raise

    finally:
        if app.db_session is not None:
            app.db_session.remove()
