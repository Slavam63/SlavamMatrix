#!/usr/bin/env python3
"""Run CASTDEV09.26 local server."""

from castdev.app import create_app
from castdev import config

app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
