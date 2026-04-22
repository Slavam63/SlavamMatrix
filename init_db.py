import app
from app.models import Base

flask_app = app.create_app()

with flask_app.app_context():
    Base.metadata.create_all(bind=app.db_engine)
    print("База данных и таблицы созданы.")
