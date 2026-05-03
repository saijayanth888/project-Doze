"""ASGI entry point.

Production runs ``uvicorn main:app`` directly via the ``Dockerfile.api``
``CMD`` (see Dockerfile). For local dev with auto-reload use::

    make api          # foreground
    # or
    scripts/start_api.sh
"""

from app import create_app

app = create_app()
