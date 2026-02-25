import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sporttracker.settings")

import django
django.setup()

# Run outstanding migrations on every cold start. This is a no-op when the
# schema is already up to date, so re-deployments are safe and fast.
from django.core.management import call_command
call_command("migrate", "--no-input", verbosity=0)

from django.core.wsgi import get_wsgi_application
app = get_wsgi_application()
application = app
