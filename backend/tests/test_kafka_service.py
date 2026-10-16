from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from app.services.kafka_service import (
    EventInProgressError,
    EventProcessingError,
    EventPublishError,
    EventPublisher,
    EventTopics,
    KafkaEventConsumer,
)


class FakeFuture:
    def __init__(self, error=None):
        self.error = error

    def get(self, timeout=None):
        if self.error:
            raise self.error
        return SimpleNamespace(offset=0)


class FakeProducer:
    def __init__(self, error=None):
        self.error = error
        self.messages = []

    def send(self, topic, key, value):
        self.messages.append((topic, key, value))
        return FakeFuture(self.error)


class FakeLedger:
    def __init__(self):
        self.documents = {}
        self.lock = Lock()
        self.indexes = []

    def create_index(self, field, unique=False):
        self.indexes.append((field, unique))

    def insert_one(self, document):
        with self.lock:
            event_id = document["event_id"]
            if event_id in self.documents:
                raise DuplicateKeyError("event already exists")
            self.documents[event_id] = deepcopy(document)

    def find_one(self, query):
        row = self.documents.get(query["event_id"])
        if row is None:
            return None
        return deepcopy(row)

    def update_one(self, query, update):
        with self.lock:
            row = self.documents.get(query["event_id"])
            if row is None:
                return SimpleNamespace(matched_count=0)
            for key, expected in query.items():
                if key != "event_id" and row.get(key) != expected:
                    return SimpleNamespace(matched_count=0)
            row.update(deepcopy(update.get("$set", {})))
            for key in update.get("$unset", {}):
                row.pop(key, None)
            for key, value in update.get("$inc", {}).items():
                row[key] = row.get(key, 0) + value
            return SimpleNamespace(matched_count=1)


def test_publisher_serializes_json_event_envelope():
    producer = FakeProducer()
    publisher = EventPublisher(producer=producer)

    event = publisher.publish(
        EventTopics.ORDER_CREATED,
        "order.created",
        {"order_id": "ORD-1", "count": 2},
        event_id="event-123",
    )

    topic, key, value = producer.messages[0]
    assert topic == "retailflow.orders.created"
    assert key == b"event-123"
    decoded = json.loads(value)
    assert decoded == event.to_dict()
    assert decoded["id"] == "event-123"
    assert decoded["payload"]["order_id"] == "ORD-1"
    assert decoded["version"] == 1


def test_publish_failure_is_surfaced_to_caller():
    publisher = EventPublisher(producer=FakeProducer(error=TimeoutError("broker timeout")))

    with pytest.raises(EventPublishError, match="event-123") as error:
        publisher.publish(EventTopics.ORDER_CREATED, "order.created", {}, event_id="event-123")

    assert error.value.topic == EventTopics.ORDER_CREATED
    assert isinstance(error.value.__cause__, TimeoutError)


def test_duplicate_delivery_runs_handler_once_and_is_ledgered():
    ledger = FakeLedger()
    handled = []
    producer = FakeProducer()
    consumer = KafkaEventConsumer(
        EventTopics.ORDER_CREATED,
        "test-group",
        handled.append,
        ledger,
        consumer=object(),
        publisher=EventPublisher(producer=producer),
        sleep=lambda _: None,
    )
    message = {
        "id": "event-1",
        "type": "order.created",
        "occurred_at": "2026-10-07T00:00:00+00:00",
        "version": 1,
        "payload": {"order_id": "ORD-1"},
    }

    assert consumer.process_message(json.dumps(message)) == "processed"
    assert consumer.process_message(json.dumps(message)) == "duplicate"
    assert len(handled) == 1
    assert ledger.documents["event-1"]["status"] == "processed"
    assert ledger.indexes == [("event_id", True)]


def test_mongo_naive_lease_prevents_concurrent_duplicate_processing():
    ledger = FakeLedger()
    ledger.documents["event-active"] = {
        "event_id": "event-active",
        "status": "processing",
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).replace(tzinfo=None),
    }
    consumer = KafkaEventConsumer(
        EventTopics.ORDER_CREATED,
        "test-group",
        lambda _: None,
        ledger,
        consumer=object(),
        publisher=EventPublisher(producer=FakeProducer()),
    )
    message = {
        "id": "event-active",
        "type": "order.created",
        "occurred_at": "2026-10-07T00:00:00+00:00",
        "payload": {},
    }

    with pytest.raises(EventInProgressError):
        consumer.process_message(message)


def test_handler_retries_then_dead_letters_and_duplicate_is_suppressed():
    ledger = FakeLedger()
    attempts = []
    producer = FakeProducer()

    def fail(event):
        attempts.append(event)
        raise ValueError("handler unavailable")

    consumer = KafkaEventConsumer(
        EventTopics.DELIVERY_COMPLETED,
        "test-group",
        fail,
        ledger,
        consumer=object(),
        publisher=EventPublisher(producer=producer),
        max_attempts=2,
        retry_backoff_seconds=0,
        sleep=lambda _: None,
    )
    message = {
        "id": "event-2",
        "type": "delivery.completed",
        "occurred_at": "2026-10-07T00:00:00+00:00",
        "payload": {"delivery_id": "DEL-1"},
    }

    assert consumer.process_message(message) == "dead_lettered"
    assert consumer.process_message(message) == "duplicate"
    assert len(attempts) == 2
    assert ledger.documents["event-2"]["status"] == "dead_lettered"
    dlq_topic, _, dlq_value = producer.messages[0]
    assert dlq_topic == f"{EventTopics.DELIVERY_COMPLETED}.dlq"
    assert json.loads(dlq_value)["dead_letter"]["source_topic"] == EventTopics.DELIVERY_COMPLETED


def test_dlq_publish_failure_leaves_event_retryable_and_surfaces_error():
    ledger = FakeLedger()
    consumer = KafkaEventConsumer(
        EventTopics.ORDER_ASSIGNED,
        "test-group",
        lambda _: (_ for _ in ()).throw(ValueError("handler failure")),
        ledger,
        consumer=object(),
        publisher=EventPublisher(producer=FakeProducer(error=TimeoutError("broker unavailable"))),
        max_attempts=1,
        retry_backoff_seconds=0,
        sleep=lambda _: None,
    )
    message = {
        "id": "event-3",
        "type": "order.assigned",
        "occurred_at": "2026-10-07T00:00:00+00:00",
        "payload": {"order_id": "ORD-3"},
    }

    with pytest.raises(EventProcessingError, match="could not be delivered to the DLQ"):
        consumer.process_message(message)

    assert ledger.documents["event-3"]["status"] == "failed"
