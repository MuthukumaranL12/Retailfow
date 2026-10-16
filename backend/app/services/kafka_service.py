"""Kafka publishing and idempotent event-consumption primitives for RetailFlow."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.config import settings

logger = logging.getLogger(__name__)


class EventTopics:
    """Kafka topics used by the RetailFlow order and delivery workflows."""

    ORDER_CREATED = "retailflow.orders.created"
    ORDER_ASSIGNED = "retailflow.orders.assigned"
    ORDER_CANCELLED = "retailflow.orders.cancelled"
    INVENTORY_RESERVED = "retailflow.inventory.reserved"
    INVENTORY_RELEASED = "retailflow.inventory.released"
    FULFILLMENT_ASSIGNED = "retailflow.fulfillment.assigned"
    DELIVERY_CREATED = "retailflow.deliveries.created"
    DELIVERY_STARTED = "retailflow.deliveries.started"
    VEHICLE_LOCATION_UPDATED = "retailflow.vehicle.location_updated"
    DELIVERY_DELAYED = "retailflow.deliveries.delayed"
    DELIVERY_STATUS_UPDATED = "retailflow.deliveries.status_updated"
    DELIVERY_COMPLETED = "retailflow.deliveries.completed"
    INVENTORY_UPDATED = "retailflow.inventory.updated"
    ALERT_CREATED = "retailflow.alerts.created"
    INVENTORY_LOW_STOCK = "retailflow.inventory.low_stock"
    REPLENISHMENT_RECOMMENDED = "retailflow.replenishment.recommended"


ALL_EVENT_TOPICS = (
    EventTopics.ORDER_CREATED,
    EventTopics.INVENTORY_RESERVED,
    EventTopics.INVENTORY_RELEASED,
    EventTopics.FULFILLMENT_ASSIGNED,
    EventTopics.DELIVERY_CREATED,
    EventTopics.DELIVERY_STARTED,
    EventTopics.VEHICLE_LOCATION_UPDATED,
    EventTopics.DELIVERY_DELAYED,
    EventTopics.DELIVERY_COMPLETED,
    EventTopics.INVENTORY_UPDATED,
    EventTopics.ALERT_CREATED,
    EventTopics.ORDER_ASSIGNED,
    EventTopics.ORDER_CANCELLED,
    EventTopics.DELIVERY_STATUS_UPDATED,
    EventTopics.INVENTORY_LOW_STOCK,
    EventTopics.REPLENISHMENT_RECOMMENDED,
)

EVENT_LEDGER_COLLECTION = "kafka_event_ledger"
EVENT_LEDGER_INDEX = "event_id"
INVALID_EVENT_TYPE = "retailflow.invalid_event"


def ensure_kafka_topics(
    bootstrap_servers: str | None = None,
    partitions: int = 3,
    replication_factor: int = 1,
) -> None:
    if partitions < 1 or replication_factor < 1:
        raise ValueError("Kafka topic partition and replication counts must be positive")
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError

    admin = KafkaAdminClient(
        bootstrap_servers=bootstrap_servers or settings.kafka_bootstrap_servers,
        client_id="retailflow-topic-provisioner",
    )
    try:
        existing = set(admin.list_topics())
        required_topics = set(ALL_EVENT_TOPICS)
        required_topics.update(f"{topic}.dlq" for topic in ALL_EVENT_TOPICS)
        missing = sorted(required_topics - existing)
        if missing:
            results = admin.create_topics(
                [NewTopic(topic, num_partitions=partitions, replication_factor=replication_factor) for topic in missing],
                validate_only=False,
            )
            for topic, future in results.items():
                try:
                    future.get(timeout=30)
                except TopicAlreadyExistsError:
                    logger.info("Kafka topic %s was concurrently provisioned", topic)
    finally:
        admin.close()


@dataclass(frozen=True)
class EventEnvelope:
    """Versioned, JSON-serializable event shape shared by publishers and consumers."""

    id: str
    type: str
    occurred_at: str
    payload: Mapping[str, Any]
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "occurred_at": self.occurred_at,
            "version": self.version,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_value(cls, value: bytes | str | Mapping[str, Any]) -> EventEnvelope:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, Mapping):
            raise ValueError("Event envelope must be a JSON object")
        event_id = value.get("id")
        event_type = value.get("type")
        occurred_at = value.get("occurred_at")
        payload = value.get("payload")
        version = value.get("version", 1)
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Event envelope requires a non-empty string id")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Event envelope requires a non-empty string type")
        if not isinstance(occurred_at, str) or not occurred_at.strip():
            raise ValueError("Event envelope requires an occurred_at timestamp")
        if not isinstance(payload, Mapping):
            raise ValueError("Event envelope payload must be a JSON object")
        if not isinstance(version, int) or version < 1:
            raise ValueError("Event envelope version must be a positive integer")
        return cls(
            id=event_id,
            type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            version=version,
        )


class EventPublishError(RuntimeError):
    """Raised when Kafka does not acknowledge an event publish."""

    def __init__(self, topic: str, event_id: str):
        super().__init__(f"Failed to publish event {event_id} to Kafka topic {topic}")
        self.topic = topic
        self.event_id = event_id


class EventProcessingError(RuntimeError):
    """Raised when an event cannot be processed or safely dead-lettered."""


class EventInProgressError(EventProcessingError):
    """Raised when another consumer currently owns the event's ledger lease."""


class EventPublisher:
    """Publish JSON event envelopes and surface broker acknowledgement failures."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        producer: Any | None = None,
        acknowledgement_timeout: float = 10.0,
    ) -> None:
        self._owns_producer = producer is None
        if producer is None:
            from kafka import KafkaProducer

            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers or settings.kafka_bootstrap_servers,
                acks="all",
                retries=0,
            )
        self.producer = producer
        self.acknowledgement_timeout = acknowledgement_timeout

    def publish(
        self,
        topic: str,
        event_type: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            id=event_id or str(uuid4()),
            type=event_type,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )
        return self.publish_envelope(topic, envelope)

    def publish_envelope(self, topic: str, envelope: EventEnvelope | Mapping[str, Any]) -> EventEnvelope:
        normalized = envelope if isinstance(envelope, EventEnvelope) else EventEnvelope.from_value(envelope)
        serialized_envelope = (
            normalized.to_dict()
            if isinstance(envelope, EventEnvelope)
            else {**dict(envelope), **normalized.to_dict()}
        )
        try:
            future = self.producer.send(
                topic,
                key=normalized.id.encode("utf-8"),
                value=json.dumps(
                    serialized_envelope, separators=(",", ":"), default=_json_default
                ).encode("utf-8"),
            )
            future.get(timeout=self.acknowledgement_timeout)
        except Exception as exc:
            raise EventPublishError(topic, normalized.id) from exc
        return normalized

    def close(self, timeout: float = 10.0) -> None:
        if self._owns_producer:
            self.producer.flush(timeout=timeout)
            self.producer.close(timeout=timeout)


class KafkaEventConsumer:
    """Consume one topic, retry handlers, deduplicate through Mongo, and route failures to a DLQ.

    The event ledger prevents duplicate deliveries from invoking a handler again once its
    prior execution has completed or been dead-lettered. An expiring lease avoids permanently
    blocking an event if a worker exits while it owns the ledger entry.
    """

    def __init__(
        self,
        topic: str,
        group_id: str,
        handler: Callable[[dict[str, Any]], Any],
        event_ledger: Any,
        bootstrap_servers: str | None = None,
        consumer: Any | None = None,
        publisher: EventPublisher | None = None,
        dlq_topic: str | None = None,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
        lease_seconds: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        self.topic = topic
        self.group_id = group_id
        self.handler = handler
        self.event_ledger = event_ledger
        self.dlq_topic = dlq_topic or f"{topic}.dlq"
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.lease_seconds = lease_seconds
        self.sleep = sleep
        self._owns_consumer = consumer is None
        if consumer is None:
            from kafka import KafkaConsumer

            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=bootstrap_servers or settings.kafka_bootstrap_servers,
                group_id=group_id,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )
        self.consumer = consumer
        self._owns_publisher = publisher is None
        self.publisher = publisher or EventPublisher(bootstrap_servers=bootstrap_servers)
        self.event_ledger.create_index(EVENT_LEDGER_INDEX, unique=True)

    def process_message(self, value: bytes | str | Mapping[str, Any], source_topic: str | None = None) -> str:
        source_topic = source_topic or self.topic
        try:
            envelope = EventEnvelope.from_value(value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._dead_letter_invalid(value, source_topic, exc)
            return "dead_lettered"

        if not self._claim(envelope.id):
            return "duplicate"

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.event_ledger.update_one(
                {"event_id": envelope.id, "status": "processing"},
                {"$set": {"attempts": attempt, "updated_at": datetime.now(timezone.utc)}},
            )
            try:
                self.handler(envelope.to_dict())
            except Exception as exc:
                last_error = exc
                logger.exception(
                    "Event handler failed (event_id=%s topic=%s attempt=%s/%s)",
                    envelope.id,
                    source_topic,
                    attempt,
                    self.max_attempts,
                )
                if attempt < self.max_attempts:
                    self.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                continue

            self.event_ledger.update_one(
                {"event_id": envelope.id, "status": "processing"},
                {
                    "$set": {
                        "status": "processed",
                        "processed_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$unset": {"lease_expires_at": ""},
                },
            )
            return "processed"

        assert last_error is not None
        dead_letter = envelope.to_dict()
        dead_letter["dead_letter"] = self._dead_letter_metadata(source_topic, last_error)
        try:
            self.publisher.publish_envelope(self.dlq_topic, dead_letter)
        except Exception as publish_error:
            self._mark_failed(envelope.id, last_error, publish_error)
            raise EventProcessingError(
                f"Event {envelope.id} failed processing and could not be delivered to the DLQ"
            ) from publish_error

        self.event_ledger.update_one(
            {"event_id": envelope.id, "status": "processing"},
            {
                "$set": {
                    "status": "dead_lettered",
                    "last_error": _error_text(last_error),
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {"lease_expires_at": ""},
            },
        )
        return "dead_lettered"

    def run_forever(self) -> None:
        """Process messages and commit only each successfully handled/DLQed offset."""
        try:
            for record in self.consumer:
                self.process_message(record.value, source_topic=record.topic)
                from kafka.structs import OffsetAndMetadata, TopicPartition

                self.consumer.commit(
                    {
                        TopicPartition(record.topic, record.partition): OffsetAndMetadata(
                            record.offset + 1, ""
                        )
                    }
                )
        finally:
            self.close()

    def close(self) -> None:
        if self._owns_consumer:
            self.consumer.close()
        if self._owns_publisher:
            self.publisher.close()

    def _claim(self, event_id: str) -> bool:
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=self.lease_seconds)
        try:
            self.event_ledger.insert_one(
                {
                    "event_id": event_id,
                    "status": "processing",
                    "attempts": 0,
                    "started_at": now,
                    "updated_at": now,
                    "lease_expires_at": lease_expiry,
                }
            )
            return True
        except DuplicateKeyError:
            current = self.event_ledger.find_one({"event_id": event_id})
            if current is None:
                raise EventProcessingError(f"Ledger claim for event {event_id} was lost")
            if current.get("status") in {"processed", "dead_lettered"}:
                return False
            old_lease = current.get("lease_expires_at")
            lease_deadline = _utc_datetime(old_lease) if isinstance(old_lease, datetime) else None
            if current.get("status") == "processing" and lease_deadline and lease_deadline > now:
                raise EventInProgressError(f"Event {event_id} is already being processed")

            result = self.event_ledger.update_one(
                {
                    "event_id": event_id,
                    "status": current.get("status"),
                    "lease_expires_at": old_lease,
                },
                {
                    "$set": {
                        "status": "processing",
                        "started_at": now,
                        "updated_at": now,
                        "lease_expires_at": lease_expiry,
                    },
                    "$unset": {"last_error": ""},
                    "$inc": {"attempts": 0},
                },
            )
            if result.matched_count == 1:
                return True

            latest = self.event_ledger.find_one({"event_id": event_id})
            if latest and latest.get("status") in {"processed", "dead_lettered"}:
                return False
            raise EventInProgressError(f"Event {event_id} is already being processed")

    def _mark_failed(self, event_id: str, handler_error: Exception, publish_error: Exception) -> None:
        self.event_ledger.update_one(
            {"event_id": event_id, "status": "processing"},
            {
                "$set": {
                    "status": "failed",
                    "last_error": _error_text(handler_error),
                    "dlq_error": _error_text(publish_error),
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {"lease_expires_at": ""},
            },
        )

    def _dead_letter_invalid(self, value: Any, source_topic: str, error: Exception) -> None:
        if isinstance(value, bytes):
            raw_value = value.decode("utf-8", errors="replace")
        elif isinstance(value, str):
            raw_value = value
        else:
            raw_value = json.dumps(value, default=_json_default)
        envelope = EventEnvelope(
            id=str(uuid4()),
            type=INVALID_EVENT_TYPE,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload={"raw_value": raw_value},
        ).to_dict()
        envelope["dead_letter"] = self._dead_letter_metadata(source_topic, error)
        self.publisher.publish_envelope(self.dlq_topic, envelope)

    @staticmethod
    def _dead_letter_metadata(source_topic: str, error: Exception) -> dict[str, Any]:
        return {
            "source_topic": source_topic,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error": _error_text(error),
        }


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _utc_datetime(value: datetime) -> datetime:
    """Normalize PyMongo's default naive UTC datetimes before lease comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
