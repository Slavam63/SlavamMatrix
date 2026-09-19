CASTDEV09.26 deploy notes (Ubuntu). Scope: this site only.

Production document root (existing): /var/www/castdev0926
Recommended DB path (outside web-root): /var/lib/castdev0926/castdev0926.sqlite
Permissions: directory 0700, db file 0600, owner service user.

=== PRODUCTION WSGI (gunicorn) ===
Unit file: castdev/deploy/castdev0926.service
WSGI module: castdev.wsgi:app

Install/switch (ssh myserver) — ONE MANUAL ACTION if cloud agent has no SSH:

  ssh myserver
  cd /opt/castdev0926
  sudo git fetch origin
  sudo git checkout <COMMIT_OR_BRANCH_WITH_WSGI>
  sudo .venv/bin/pip install -r requirements-castdev.txt
  sudo cp castdev/deploy/castdev0926.service /etc/systemd/system/castdev0926.service
  # Keep existing /etc/castdev0926.env (activation token) — do NOT reset token
  sudo systemctl daemon-reload
  sudo systemctl restart castdev0926.service
  sudo systemctl status castdev0926.service --no-pager
  curl -sS http://127.0.0.1:8092/api/castdev/health
  curl -sS https://castdev0926.labinfluences.su/api/castdev/health
  # Confirm journal no longer shows Werkzeug "development server" warning:
  sudo journalctl -u castdev0926.service -n 40 --no-pager

EnvironmentFile=/etc/castdev0926.env should already set:
  CASTDEV_DATA_DIR=/var/lib/castdev0926
  CASTDEV_ADMIN_ACTIVATION_TOKEN=<kept by Vyacheslav>
  CASTDEV_ADMIN_SESSION_SECRET=<existing>

=== WIPE ACCEPTANCE TEST ROWS ===
Test submissions are marked with literal marker [TEST-ACCEPTANCE-WIPE] in q1–q4.
Dry-run then apply:

  cd /opt/castdev0926
  sudo CASTDEV_DATA_DIR=/var/lib/castdev0926 \
    .venv/bin/python -m castdev.scripts.wipe_acceptance_test_rows
  sudo CASTDEV_DATA_DIR=/var/lib/castdev0926 \
    .venv/bin/python -m castdev.scripts.wipe_acceptance_test_rows --apply

Also safe: wipe dedicated test DB file only (never production file):
  rm -f /var/lib/castdev0926/castdev0926_test.sqlite

nginx: proxy /api/ and /admin to 127.0.0.1:8092; static may stay in /var/www/castdev0926
or also proxied. Do NOT touch other server_name blocks.

Rollback: restore previous /var/www/castdev0926 from backup; stop new service;
restore sqlite from backups/ if needed (test restore first).

Backup known: /root/backups/castdev0926/pre-op9-20260919T130510Z.tar.gz
