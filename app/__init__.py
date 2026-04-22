from flask import Flask, redirect, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from app.config import Config
try:
    from app.routes import register_routes
except ModuleNotFoundError:  # pragma: no cover
    # Позволяет импортировать пакет `app` в изолированных unit-тестах.
    def register_routes(_app):  # type: ignore[no-redef]
        return None

db_engine = None
db_session = None


def create_app():
    global db_engine, db_session

    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["DATABASE_URL"] = Config.DATABASE_URL
    app.config["REDIS_URL"] = Config.REDIS_URL
    app.config["APP_NAME"] = Config.APP_NAME
    app.config["SLOT_STEP_MINUTES"] = Config.SLOT_STEP_MINUTES
    app.config["SLOT_HORIZON_HOURS"] = Config.SLOT_HORIZON_HOURS
    app.config["PARSER_DEFAULT_SOURCES"] = Config.PARSER_DEFAULT_SOURCES
    app.config["PARSER_RESULTS_LIMIT"] = Config.PARSER_RESULTS_LIMIT
    app.config["ENABLE_MOCK_SOURCE"] = Config.ENABLE_MOCK_SOURCE
    app.config["ENABLE_HH_SOURCE"] = Config.ENABLE_HH_SOURCE

    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DATABASE_URL is not set in .env")

    db_engine = create_engine(
        app.config["DATABASE_URL"],
        pool_pre_ping=True,
        future=True,
    )
    db_session = scoped_session(
        sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    )

    @app.route("/")
    def index():
        return redirect(url_for("job_search_page"))

    @app.route("/health")
    def health():
        try:
            with db_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {
                "status": "ok",
                "app": app.config["APP_NAME"],
                "database": "ok",
            }, 200
        except Exception as exc:
            return {
                "status": "error",
                "app": app.config["APP_NAME"],
                "database": "error",
                "message": str(exc),
            }, 500

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session is not None:
            db_session.remove()

    register_routes(app)

    return app
