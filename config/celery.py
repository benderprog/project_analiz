import os

from celery import Celery

from config.worker_torch_threads import configure_torch_threads

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
configure_torch_threads()

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

