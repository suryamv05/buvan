from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings

settings.validate_runtime()

celery_app = Celery("valorant_backend", broker=settings.celery_broker_url)
celery_app.conf.update(
    task_default_queue="valorant",
    task_default_exchange="valorant",
    task_default_exchange_type="direct",
    task_default_routing_key="valorant",
    task_queues=(
        Queue(
            "valorant",
            exchange=Exchange("valorant", type="direct", durable=True),
            routing_key="valorant",
            durable=True,
        ),
    ),
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_send_task_events=False,
    task_send_sent_event=False,
    worker_enable_remote_control=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_timeout=5,
    worker_hijack_root_logger=False,
    broker_heartbeat=30,
)
