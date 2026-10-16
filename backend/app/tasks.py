from app.worker import celery_app


@celery_app.task
def process_order_event(order_id: str) -> str:
    return f'Processed order event for {order_id}'
