from sqlalchemy import asc, desc

import app
from app.models import JobRequest, Task, Vacancy


def _get_latest_task(job_request_id: int):
    db = app.db_session

    return (
        db.query(Task)
        .filter(Task.job_request_id == job_request_id)
        .order_by(desc(Task.created_at), desc(Task.id))
        .first()
    )


def _get_queue_position(job_request_id: int):
    db = app.db_session

    current_task = _get_latest_task(job_request_id)
    if not current_task:
        return None

    if current_task.status == "running":
        return 0

    if current_task.status != "queued":
        return None

    queued_tasks = (
        db.query(Task)
        .filter(Task.status == "queued")
        .order_by(asc(Task.created_at), asc(Task.id))
        .all()
    )

    for index, task in enumerate(queued_tasks, start=0):
        if task.id == current_task.id:
            return index

    return None


def get_job_request_status(job_request_id: int):
    db = app.db_session

    job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
    if not job_request:
        raise ValueError("job request not found")

    latest_task = _get_latest_task(job_request.id)

    vacancies_count = (
        db.query(Vacancy)
        .filter(Vacancy.job_request_id == job_request.id)
        .count()
    )

    result = {
        "job_request_id": job_request.id,
        "status": job_request.status,
        "progress": 0,
        "found_vacancies": vacancies_count,
        "queue_position": None,
    }

    if latest_task:
        result["task_id"] = latest_task.id
        result["task_status"] = latest_task.status
        result["progress"] = latest_task.progress
        result["found_vacancies"] = latest_task.found_vacancies
        result["queue_position"] = _get_queue_position(job_request.id)

    return result
