"""WSGI config for the Speedrun Hub project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "speedrun_hub.settings")

application = get_wsgi_application()
