"""Production WSGI entrypoint for gunicorn/waitress.

Usage:
  gunicorn -b 127.0.0.1:8092 -w 2 --timeout 60 castdev.wsgi:app
"""

from castdev.app import create_app

app = create_app()
