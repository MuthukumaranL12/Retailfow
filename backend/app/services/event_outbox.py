from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.db import db
from app.services.kafka_service import EventEnvelope, EventPublishError, EventPublisher

logger = logging.getLogger(__name__)
OUTBOX_COLLECTION = "kafka_outbox"
PUBLISH_LEASE_SECONDS = 60


class EventOutboxError(RuntimeError):
    """Raised when a business event cannot be durably added to the outbox."""


def ensure_outbox_indexes() -> None:
    outbox = db[OUTBOX_COLLECTION]
    outbox.create_index([("status", 1), ("next_attempt_at", 1), ("created_at", 1)])
    outbox.create_index(
        "created_at",
        expireAfterSeconds=30 * 24 * 60 * 60,
        partialFilterExpression={"status": "published"},
    )


def queue_business_event(
    topic: str,
    event_type: str,
    payload: Mapping[str, Any],
    event_id: str | None = None,
) -> dict[str, str]:
    event_id = event_id or str(uuid4())
    envelope = EventEnvelope(
        id=event_id,
        type=event_type,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        payload=payload,
    ).to_dict()
    now = datetime.now(timezone.utc)
    document = {
        "_id": event_id,
        "event_id": event_id,
        "topic": topic,
        "envelope": envelope,
        "status": "pending",
        "attempts": 0,
        "created_at": now,
        "updated_at": now,
        "next_attempt_at": now,
    }
    try:
        db[OUTBOX_COLLECTION].update_one(
            {"_id": event_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        existing = db[OUTBOX_COLLECTION].find_one({"_id": event_id}, {"status": 1})
    except PyMongoError as exc:
        raise EventOutboxError(f"Could not durably queue event {event_id}") from exc
    return {"event_id": event_id, "status": existing.get("status", "pending") if existing else "pending"}


def flush_pending_events(publisher: EventPublisher, limit: int = 100) -> int:
    """Publish due events; retries retain the same event ID for consumer deduplication."""
    now = datetime.now(timezone.utc)
    outbox = db[OUTBOX_COLLECTION]
    due_query = {
        "$or": [
            {"status": "pending", "next_attempt_at": {"$lte": now}},
            {"status": "publishing", "lease_expires_at": {"$lte": now}},
        ]
    }
    pending = list(outbox.find(due_query, {"_id": 1}).sort("created_at", 1).limit(limit))
    published_count = 0
    for row in pending:
        claimed_at = datetime.now(timezone.utc)
        event = outbox.find_one_and_update(
            {
                "_id": row["_id"],
                "$or": [
                    {"status": "pending", "next_attempt_at": {"$lte": claimed_at}},
                    {"status": "publishing", "lease_expires_at": {"$lte": claimed_at}},
                ],
            },
            {
                "$set": {
                    "status": "publishing",
                    "lease_expires_at": claimed_at + timedelta(seconds=PUBLISH_LEASE_SECONDS),
                    "updated_at": claimed_at,
                },
                "$inc": {"attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not event:
            continue
        try:
            publisher.publish_envelope(event["topic"], event["envelope"])
        except EventPublishError as exc:
            attempts = int(event.get("attempts", 1))
            retry_seconds = min(300, 2 ** min(attempts, 8))
            outbox.update_one(
                {"_id": event["_id"], "status": "publishing"},
                {
                    "$set": {
                        "status": "pending",
                        "last_error": f"{type(exc).__name__}: {exc}",
                        "next_attempt_at": datetime.now(timezone.utc) + timedelta(seconds=retry_seconds),
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$unset": {"lease_expires_at": ""},
                },
            )
            logger.warning(
                "Kafka event retained for retry (event_id=%s topic=%s)",
                event["event_id"],
                event["topic"],
                exc_info=True,
            )
            continue

        outbox.update_one(
            {"_id": event["_id"], "status": "publishing"},
            {
                "$set": {
                    "status": "published",
                    "published_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {"lease_expires_at": "", "last_error": ""},
            },
        )
        published_count += 1
    return published_count
