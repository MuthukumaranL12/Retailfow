from celery import Celery

from app.config import settings

celery_app = Celery(
    'retailflow_tasks',
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=['app.tasks'],
)

celery_app.conf.update(task_serializer='json', accept_content=['json'])


@celery_app.task
def health_check_task() -> str:
    return 'RetailFlow Celery worker is healthy'
