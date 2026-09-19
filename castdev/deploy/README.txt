"""CASTDEV09.26 deploy notes (Ubuntu). Scope: this site only.

Production document root (existing): /var/www/castdev0926
Recommended DB path (outside web-root): /var/lib/castdev0926/castdev0926.sqlite
Permissions: directory 0700, db file 0600, owner service user.

systemd unit example: castdev0926.service
  Environment=CASTDEV_DATA_DIR=/var/lib/castdev0926
  Environment=CASTDEV_ADMIN_ACTIVATION_TOKEN=<rotate>
  Environment=CASTDEV_ADMIN_SESSION_SECRET=<rotate>
  ExecStart=/usr/bin/python3 -m gunicorn -b 127.0.0.1:8092 castdev.app:create_app()
  (or: python3 castdev/run_server.py with HOST=127.0.0.1)

nginx: proxy /api/ and /admin to 127.0.0.1:8092; static may stay in /var/www/castdev0926
or also proxied. Do NOT touch other server_name blocks.

Rollback: restore previous /var/www/castdev0926 from backup; stop new service;
restore sqlite from backups/ if needed (test restore first).
"""
