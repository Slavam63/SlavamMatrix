from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    String,
    func,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_requests = relationship("JobRequest", back_populates="user", cascade="all, delete-orphan")
    search_sessions = relationship("SearchSession", back_populates="user")


class JobRequest(Base):
    __tablename__ = "job_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    query_text = Column(Text, nullable=True)
    position = Column(String(255), nullable=True)
    keywords = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)

    salary_min = Column(Numeric(12, 2), nullable=True)
    salary_max = Column(Numeric(12, 2), nullable=True)

    employment_type = Column(String(100), nullable=True)
    work_format = Column(String(100), nullable=True)
    display_period = Column(String(100), nullable=True)
    sort_order = Column(String(100), nullable=True)
    vacancy_source = Column(String(100), nullable=True)

    remote = Column(Boolean, nullable=False, default=False)
    status = Column(String(50), nullable=False, default="created", index=True)

    resume_file_name = Column(String(255), nullable=True)
    resume_file_path = Column(Text, nullable=True)
    resume_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="job_requests")
    tasks = relationship("Task", back_populates="job_request", cascade="all, delete-orphan")
    vacancies = relationship("Vacancy", back_populates="job_request", cascade="all, delete-orphan")
    search_sessions = relationship("SearchSession", back_populates="job_request", cascade="all, delete-orphan")

    vacancy_intakes = relationship("VacancyIntake", back_populates="job_request", cascade="all, delete-orphan")
    vacancy_matches = relationship("VacancyMatch", back_populates="job_request", cascade="all, delete-orphan")
    generated_artifacts = relationship("GeneratedArtifact", back_populates="job_request", cascade="all, delete-orphan")
    vacancy_action_tasks = relationship("VacancyActionTask", back_populates="job_request", cascade="all, delete-orphan")


class Slot(Base):
    __tablename__ = "slots"

    id = Column(Integer, primary_key=True)
    slot_time = Column(DateTime(timezone=True), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default="free", index=True)
    reserved_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)
    celery_task_id = Column(String(255), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0)
    found_vacancies = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="tasks")


class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True)
    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)

    source = Column(String(100), nullable=False, index=True)
    external_id = Column(String(255), nullable=True, index=True)

    title = Column(String(500), nullable=False)
    company = Column(String(255), nullable=True)
    location = Column(String(255), nullable=True)
    salary = Column(String(255), nullable=True)
    url = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)

    employment_type = Column(String(100), nullable=True)
    remote = Column(Boolean, nullable=False, default=False)

    ai_score = Column(Numeric(5, 2), nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_tags = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="vacancies")
    feedback_items = relationship("VacancyFeedback", back_populates="vacancy", cascade="all, delete-orphan")


class SearchSession(Base):
    __tablename__ = "search_sessions"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)

    initial_query = Column(Text, nullable=True)
    normalized_query = Column(Text, nullable=True)
    normalized_position = Column(String(255), nullable=True)
    normalized_industry = Column(String(255), nullable=True)
    normalized_seniority = Column(String(100), nullable=True)
    normalized_location = Column(String(255), nullable=True)
    strategy_version = Column(String(50), nullable=True)

    status = Column(String(50), nullable=False, default="created", index=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="search_sessions")
    job_request = relationship("JobRequest", back_populates="search_sessions")
    attempts = relationship("SearchAttempt", back_populates="search_session", cascade="all, delete-orphan")
    feedback_items = relationship("VacancyFeedback", back_populates="search_session", cascade="all, delete-orphan")


class SearchAttempt(Base):
    __tablename__ = "search_attempts"

    id = Column(Integer, primary_key=True)

    search_session_id = Column(Integer, ForeignKey("search_sessions.id"), nullable=False, index=True)

    source = Column(String(100), nullable=False, index=True)
    query_variant = Column(Text, nullable=True)
    filters_json = Column(Text, nullable=True)

    results_count = Column(Integer, nullable=False, default=0)
    relevant_results_count = Column(Integer, nullable=False, default=0)

    avg_ai_score = Column(Numeric(5, 2), nullable=True)
    top_ai_score = Column(Numeric(5, 2), nullable=True)

    was_successful = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    search_session = relationship("SearchSession", back_populates="attempts")


class VacancyFeedback(Base):
    __tablename__ = "vacancy_feedback"

    id = Column(Integer, primary_key=True)

    search_session_id = Column(Integer, ForeignKey("search_sessions.id"), nullable=False, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"), nullable=False, index=True)

    action_type = Column(String(50), nullable=False, index=True)
    action_value = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    search_session = relationship("SearchSession", back_populates="feedback_items")
    vacancy = relationship("Vacancy", back_populates="feedback_items")


class VacancyIntake(Base):
    __tablename__ = "vacancy_intakes"

    id = Column(Integer, primary_key=True)

    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)

    source_type = Column(String(50), nullable=False, index=True)  # email / manual / url / api
    source_name = Column(String(100), nullable=True, index=True)  # linkedin / hh / telegram / etc.
    external_ref = Column(String(255), nullable=True, index=True)

    status = Column(String(50), nullable=False, default="received", index=True)

    raw_subject = Column(String(500), nullable=True)
    raw_text = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    sender_email = Column(String(255), nullable=True)

    parsed_title = Column(String(500), nullable=True)
    parsed_company = Column(String(255), nullable=True)
    parsed_location = Column(String(255), nullable=True)
    parsed_employment_type = Column(String(100), nullable=True)
    parsed_remote = Column(Boolean, nullable=False, default=False)

    parsed_payload_json = Column(Text, nullable=True)
    parser_version = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)

    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="vacancy_intakes")
    matches = relationship("VacancyMatch", back_populates="vacancy_intake", cascade="all, delete-orphan")
    artifacts = relationship("GeneratedArtifact", back_populates="vacancy_intake", cascade="all, delete-orphan")
    action_tasks = relationship("VacancyActionTask", back_populates="vacancy_intake", cascade="all, delete-orphan")


class VacancyMatch(Base):
    __tablename__ = "vacancy_matches"

    id = Column(Integer, primary_key=True)

    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)
    vacancy_intake_id = Column(Integer, ForeignKey("vacancy_intakes.id"), nullable=False, index=True)

    status = Column(String(50), nullable=False, default="created", index=True)
    relevance_score = Column(Numeric(5, 2), nullable=True)

    matched_skills_json = Column(Text, nullable=True)
    missing_skills_json = Column(Text, nullable=True)
    red_flags_json = Column(Text, nullable=True)

    agent_summary = Column(Text, nullable=True)
    agent_rationale = Column(Text, nullable=True)
    decision = Column(String(50), nullable=True, index=True)  # apply / review / ignore / follow_up

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="vacancy_matches")
    vacancy_intake = relationship("VacancyIntake", back_populates="matches")


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"

    id = Column(Integer, primary_key=True)

    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)
    vacancy_intake_id = Column(Integer, ForeignKey("vacancy_intakes.id"), nullable=False, index=True)

    artifact_type = Column(String(50), nullable=False, index=True)  # adapted_resume / recruiter_message / cover_letter / follow_up
    status = Column(String(50), nullable=False, default="created", index=True)

    language = Column(String(20), nullable=True)
    tone = Column(String(50), nullable=True)

    content_text = Column(Text, nullable=True)
    content_json = Column(Text, nullable=True)

    generator_version = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="generated_artifacts")
    vacancy_intake = relationship("VacancyIntake", back_populates="artifacts")


class VacancyActionTask(Base):
    __tablename__ = "vacancy_action_tasks"

    id = Column(Integer, primary_key=True)

    job_request_id = Column(Integer, ForeignKey("job_requests.id"), nullable=False, index=True)
    vacancy_intake_id = Column(Integer, ForeignKey("vacancy_intakes.id"), nullable=False, index=True)

    task_type = Column(String(50), nullable=False, index=True)  # apply / recruiter_message / follow_up / save / ignore
    priority = Column(String(20), nullable=False, default="medium", index=True)
    status = Column(String(50), nullable=False, default="open", index=True)

    due_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_request = relationship("JobRequest", back_populates="vacancy_action_tasks")
    vacancy_intake = relationship("VacancyIntake", back_populates="action_tasks")
