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
app.conf.task_allow_error_cb_on_chord_header = True
app.autodiscover_tasks()