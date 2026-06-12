import os
from celery import Celery
from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "codebase_analyzer_back_end.settings"
)

app = Celery("codebase_analyzer_back_end")

app.config_from_object(
    "django.conf:settings",
    namespace="CELERY"
)

app.autodiscover_tasks()