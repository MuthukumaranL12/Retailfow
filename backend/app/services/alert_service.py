from datetime import datetime, timezone

from app.db import db
from app.services.event_outbox import queue_business_event
from app.services.kafka_service import EventTopics


def create_alert(alert_id: str, title: str, severity: str, message: str, store_id: str | None = None, product_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    alert_doc = {
        "alert_id": alert_id,
        "title": title,
        "severity": severity,
        "message": message,
        "store_id": store_id,
        "product_id": product_id,
        "last_seen_at": now,
    }
    db.alerts.update_one(
        {"alert_id": alert_id},
        {
            "$set": alert_doc,
            "$setOnInsert": {"acknowledged": False, "resolved": False, "created_at": now},
        },
        upsert=True,
    )
    alert = db.alerts.find_one({"alert_id": alert_id}, {"_id": 0})
    if alert:
        queue_business_event(
            EventTopics.ALERT_CREATED,
            "alert.created",
            {
                "alert_id": alert_id,
                "store_id": store_id,
                "product_id": product_id,
                "severity": severity,
            },
            f"alert-created-{alert_id}",
        )
    return alert


def get_open_alerts() -> list[dict]:
    return list(db.alerts.find({"acknowledged": False, "resolved": False}).limit(20))
