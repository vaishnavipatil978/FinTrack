from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("fintrack", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=("app.workers.tasks",),
)

# Daily sweep for due recurring transactions - docs/architecture/background-jobs.md.
celery_app.conf.beat_schedule = {
    "process-due-recurring-rules-daily": {
        "task": "app.workers.tasks.process_due_recurring_rules_task",
        "schedule": crontab(hour=0, minute=15),
    },
}
