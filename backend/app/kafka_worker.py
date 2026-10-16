from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.db import db
from pymongo.errors import DuplicateKeyError
from app.services.event_outbox import ensure_outbox_indexes, flush_pending_events
from app.services.kafka_service import (
    ALL_EVENT_TOPICS,
    EVENT_LEDGER_COLLECTION,
    EventPublisher,
    KafkaEventConsumer,
    ensure_kafka_topics,
)

logger = logging.getLogger(__name__)
GROUP_PREFIX = "retailflow-business-projections-v1"


def process_business_event(envelope: dict[str, Any]) -> None:
    """Validate committed domain state, update materialized views, and roll up analytics."""
    event_id = envelope["id"]
    event_type = envelope["type"]
    payload = envelope["payload"]
    occurred_at = _parse_event_time(envelope["occurred_at"])

    if event_type in {"order.created", "order.assigned", "fulfillment.assigned", "order.cancelled"}:
        order_id = payload.get("order_id")
        order = db.orders.find_one({"order_id": order_id}, {"_id": 0}) if order_id else None
        if not order:
            raise LookupError(f"Order {order_id} referenced by {event_type} does not exist")
        db.order_fulfillment_views.update_one(
            {"order_id": order_id},
            {
                "$set": {
                    "order_id": order_id,
                    "customer_id": order.get("customer_id"),
                    "status": order.get("status"),
                    "location_id": order.get("fulfillment_location"),
                    "fulfillment_decision": order.get("fulfillment_decision"),
                    "items": order.get("items", []),
                    "delivery_id": order.get("delivery_id"),
                    "delivery_details": order.get("delivery_details"),
                    "last_event_type": event_type,
                    "last_event_id": event_id,
                    "updated_at": occurred_at,
                }
            },
            upsert=True,
        )
    elif event_type in {"inventory.reserved", "inventory.released", "inventory.updated"}:
        product_id = payload.get("product_id")
        store_id = payload.get("store_id")
        inventory = db.inventory.find_one({"product_id": product_id, "store_id": store_id}, {"_id": 0})
        if not inventory:
            raise LookupError(f"Inventory {product_id} at {store_id} referenced by {event_type} does not exist")
        movement_id = payload.get("movement_id")
        if event_type != "inventory.updated" and not db.inventory_movements.find_one({"movement_id": movement_id}):
            raise LookupError(f"Inventory movement {movement_id} referenced by {event_type} does not exist")
        db.inventory_availability_views.update_one(
            {"store_id": store_id, "product_id": product_id},
            {
                "$set": {
                    **inventory,
                    "available": inventory.get("on_hand", 0) - inventory.get("reserved", 0),
                    "last_event_type": event_type,
                    "last_event_id": event_id,
                    "updated_at": occurred_at,
                }
            },
            upsert=True,
        )
    elif event_type in {
        "delivery.created",
        "delivery.started",
        "vehicle.location.updated",
        "delivery.delayed",
        "delivery.completed",
        "delivery.status_updated",
    }:
        delivery_id = payload.get("delivery_id")
        delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0}) if delivery_id else None
        if not delivery:
            raise LookupError(f"Delivery {delivery_id} referenced by {event_type} does not exist")
        db.delivery_tracking_views.update_one(
            {"delivery_id": delivery_id},
            {
                "$set": {
                    **delivery,
                    "last_event_type": event_type,
                    "last_event_id": event_id,
                    "view_updated_at": occurred_at,
                }
            },
            upsert=True,
        )
    elif event_type == "alert.created":
        alert_id = payload.get("alert_id")
        alert = db.alerts.find_one({"alert_id": alert_id}, {"_id": 0}) if alert_id else None
        if not alert:
            raise LookupError(f"Alert {alert_id} referenced by alert.created does not exist")
        db.alert_views.update_one(
            {"alert_id": alert_id},
            {
                "$set": {
                    **alert,
                    "last_event_id": event_id,
                    "view_updated_at": occurred_at,
                }
            },
            upsert=True,
        )
    else:
        raise ValueError(f"Unsupported RetailFlow business event type: {event_type}")

    try:
        db.kafka_event_facts.insert_one(
            {
                "event_id": event_id,
                "day": occurred_at.date().isoformat(),
                "event_type": event_type,
                "occurred_at": occurred_at,
                "processed_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        # A handler replay after a crash must not double-count analytics.
        pass


def run_worker() -> None:
    ensure_outbox_indexes()
    db[EVENT_LEDGER_COLLECTION].create_index("event_id", unique=True)
    db.order_fulfillment_views.create_index("order_id", unique=True)
    db.inventory_availability_views.create_index([("store_id", 1), ("product_id", 1)], unique=True)
    db.delivery_tracking_views.create_index("delivery_id", unique=True)
    db.alert_views.create_index("alert_id", unique=True)
    db.kafka_event_facts.create_index("event_id", unique=True)
    ensure_kafka_topics()

    publisher = EventPublisher()
    stopping = threading.Event()
    consumers: list[threading.Thread] = []

    def publish_outbox() -> None:
        while not stopping.is_set():
            try:
                flush_pending_events(publisher)
            except Exception:
                logger.exception("Kafka outbox dispatcher failed")
            stopping.wait(1)

    dispatcher = threading.Thread(target=publish_outbox, name="retailflow-kafka-outbox", daemon=True)
    dispatcher.start()

    def consume_topic(topic: str) -> None:
        while not stopping.is_set():
            try:
                consumer = KafkaEventConsumer(
                    topic=topic,
                    group_id=f"{GROUP_PREFIX}-{topic.replace('.', '-')}",
                    handler=process_business_event,
                    event_ledger=db[EVENT_LEDGER_COLLECTION],
                    publisher=publisher,
                )
                consumer.run_forever()
                if not stopping.is_set():
                    logger.error("Kafka consumer for %s stopped unexpectedly", topic)
            except Exception:
                logger.exception("Kafka consumer for %s failed; restarting", topic)
                stopping.wait(2)

    for topic in ALL_EVENT_TOPICS:
        thread = threading.Thread(target=consume_topic, args=(topic,), name=f"consumer-{topic}", daemon=True)
        thread.start()
        consumers.append(thread)

    def stop_worker(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s; stopping Kafka worker", signum)
        stopping.set()

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    try:
        while not stopping.wait(1):
            time.sleep(0)
    finally:
        stopping.set()
        dispatcher.join(timeout=5)
        for thread in consumers:
            thread.join(timeout=5)
        publisher.close()


def _parse_event_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
