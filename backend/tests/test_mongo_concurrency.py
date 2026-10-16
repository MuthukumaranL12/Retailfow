import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.services import alert_service, chatbot_service, event_outbox, fulfillment_service, inventory_service, workflow_service
from app.services.inventory_service import InsufficientInventory


def test_mongodb_event_outbox_retries_without_losing_event(monkeypatch):
    uri = os.getenv("RETAILFLOW_TEST_MONGODB_URI", "mongodb://localhost:27017")
    client = MongoClient(uri, serverSelectionTimeoutMS=500)
    try:
        client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"MongoDB integration service is unavailable: {exc}")

    database = client[f"retailflow_outbox_{uuid4().hex}"]
    monkeypatch.setattr(event_outbox, "db", database)
    event_outbox.ensure_outbox_indexes()
    queued = event_outbox.queue_business_event(
        "retailflow.test.events",
        "inventory.updated",
        {"product_id": "P-OUTBOX", "store_id": "S-OUTBOX"},
        "outbox-retry-event",
    )

    class FailedPublisher:
        def publish_envelope(self, *_args):
            from app.services.kafka_service import EventPublishError

            raise EventPublishError("retailflow.test.events", "outbox-retry-event")

    class AcceptedPublisher:
        def publish_envelope(self, _topic, envelope):
            return envelope

    try:
        assert queued["status"] == "pending"
        assert event_outbox.flush_pending_events(FailedPublisher()) == 0
        retained = database.kafka_outbox.find_one({"_id": "outbox-retry-event"})
        assert retained["status"] == "pending"
        assert "EventPublishError" in retained["last_error"]

        database.kafka_outbox.update_one(
            {"_id": "outbox-retry-event"},
            {"$set": {"next_attempt_at": datetime.now(timezone.utc)}},
        )
        assert event_outbox.flush_pending_events(AcceptedPublisher()) == 1
        assert database.kafka_outbox.find_one({"_id": "outbox-retry-event"})["status"] == "published"
        assert event_outbox.queue_business_event(
            "retailflow.test.events",
            "inventory.updated",
            {"product_id": "P-OUTBOX", "store_id": "S-OUTBOX"},
            "outbox-retry-event",
        )["status"] == "published"
        assert database.kafka_outbox.count_documents({"_id": "outbox-retry-event"}) == 1
    finally:
        client.drop_database(database.name)
        client.close()


def test_mongodb_atomic_reservation_concurrency(monkeypatch):
    uri = os.getenv("RETAILFLOW_TEST_MONGODB_URI", "mongodb://localhost:27017")
    client = MongoClient(uri, serverSelectionTimeoutMS=500)
    try:
        client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"MongoDB integration service is unavailable: {exc}")

    database = client[f"retailflow_test_{uuid4().hex}"]
    monkeypatch.setattr(inventory_service, "db", database)
    monkeypatch.setattr(event_outbox, "db", database)
    stock = {"store_id": "concurrency-store", "product_id": "concurrency-product", "on_hand": 5, "reserved": 0}
    database.inventory.insert_one(stock)

    def reserve(index):
        try:
            inventory_service.reserve_inventory(
                "concurrency-product", "concurrency-store", 1, f"concurrency-order-{index}"
            )
            return True
        except InsufficientInventory:
            return False

    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(reserve, range(10)))
        record = database.inventory.find_one(
            {"store_id": "concurrency-store", "product_id": "concurrency-product"}
        )
        assert sum(results) == 5
        assert record["reserved"] == 5
    finally:
        client.drop_database(database.name)
        client.close()


def test_mongodb_order_to_delivery_websocket_workflow(monkeypatch):
    uri = os.getenv("RETAILFLOW_TEST_MONGODB_URI", "mongodb://localhost:27017")
    client = MongoClient(uri, serverSelectionTimeoutMS=500)
    try:
        client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"MongoDB integration service is unavailable: {exc}")

    database = client[f"retailflow_e2e_{uuid4().hex}"]
    from app import main
    from app.api.v1 import deliveries as deliveries_api
    from app.api.v1 import inventory as inventory_api
    from app.api.v1 import orders as orders_api
    from app.api.v1 import routes as routes_api
    from app.api.v1 import analytics as analytics_api
    from app.api.v1 import alerts as alerts_api
    from app.api.v1 import chatbot as chatbot_api
    from app.api.v1 import forecast as forecast_api
    from app.api.v1 import replenishment as replenishment_api
    from app.api.v1 import auth as auth_api
    from app import kafka_worker
    from app import security_controls
    from app.services import kafka_service
    from app.services import replenishment_service
    import app.security as security_module

    database.products.insert_one({"product_id": "P-E2E", "name": "Demo item", "weight_kg": 2})
    database.stores.insert_one(
        {"store_id": "S-E2E", "name": "Origin", "city": "Denver", "lat": 39.7392, "lng": -104.9903}
    )
    database.inventory.insert_one(
        {
            "store_id": "S-E2E",
            "product_id": "P-E2E",
            "on_hand": 5,
            "reserved": 0,
            "incoming": 0,
            "safety_stock": 0,
            "reorder_point": 4,
        }
    )
    database.vehicles.insert_one(
        {"vehicle_id": "V-E2E", "driver_id": "D-E2E", "status": "AVAILABLE", "capacity_kg": 50}
    )
    database.users.insert_many(
        [
            {
                "email": "supply@example.com",
                "full_name": "Test Supply Manager",
                "password": security_module.hash_password("integration-password"),
                "role": "SUPPLY_CHAIN_MANAGER",
            },
            {
                "email": "other-customer@example.com",
                "full_name": "Test Customer",
                "password": security_module.hash_password("customer-password"),
                "role": "CUSTOMER",
            },
        ]
    )
    database.sales.insert_many(
        [
            {
                "product_id": "P-E2E",
                "store_id": "S-E2E",
                "date": datetime.now(timezone.utc) - timedelta(days=offset),
                "quantity": 1 + offset % 2,
            }
            for offset in range(1, 15)
        ]
    )
    for module in (
        inventory_service,
        fulfillment_service,
        workflow_service,
        orders_api,
        deliveries_api,
        inventory_api,
        routes_api,
        analytics_api,
        alerts_api,
        chatbot_api,
        forecast_api,
        replenishment_api,
        replenishment_service,
        chatbot_service,
        alert_service,
        auth_api,
        security_module,
        security_controls,
        event_outbox,
        kafka_worker,
    ):
        monkeypatch.setattr(module, "db", database)
    monkeypatch.setattr(
        analytics_api,
        "redis_client",
        SimpleNamespace(get=lambda _key: None, setex=lambda *_args: None),
    )
    monkeypatch.setattr(main, "ensure_indexes", lambda: None)
    monkeypatch.setattr(main, "seed_demo_data", lambda: None)

    try:
        with TestClient(main.app) as test_client:
            login = test_client.post(
                "/api/v1/auth/login",
                json={"email": "supply@example.com", "password": "integration-password"},
            )
            assert login.status_code == 200
            test_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
            response = test_client.post(
                "/api/v1/orders",
                headers={"Idempotency-Key": "e2e-order-once"},
                json={
                    "customer_id": "customer@example.com",
                    "items": [{"product_id": "P-E2E", "quantity": 1}],
                    "delivery_address": {"lat": 39.75, "lng": -104.98, "city": "Denver"},
                },
            )
            assert response.status_code == 201, response.text
            order = response.json()["order"]
            assert order["fulfillment_location"] == "S-E2E"
            assert database.inventory.find_one({"product_id": "P-E2E"})["reserved"] == 1
            assert database.routes.find_one({"route_id": order["route_id"]}) is not None
            duplicate = test_client.post(
                "/api/v1/orders",
                headers={"Idempotency-Key": "e2e-order-once"},
                json={
                    "customer_id": "customer@example.com",
                    "items": [{"product_id": "P-E2E", "quantity": 1}],
                    "delivery_address": {"lat": 39.75, "lng": -104.98, "city": "Denver"},
                },
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["order"]["order_id"] == order["order_id"]
            assert database.orders.count_documents({}) == 1

            delivery_id = order["delivery_id"]
            assert test_client.post(f"/api/v1/deliveries/{delivery_id}/start").status_code == 200
            ticket = test_client.post(f"/api/v1/deliveries/{delivery_id}/live-ticket")
            assert ticket.status_code == 200
            with test_client.websocket_connect(
                f"/api/v1/deliveries/{delivery_id}/live?ticket={ticket.json()['ticket']}"
            ) as socket:
                for expected_progress in (0.2, 0.4, 0.6, 0.8, 1.0):
                    moved = test_client.post(f"/api/v1/deliveries/{delivery_id}/advance")
                    assert moved.status_code == 200, moved.text
                    event = socket.receive_json()
                    assert event["type"] == "vehicle.location.updated"
                    assert event["progress"] == expected_progress
            completed = test_client.post(f"/api/v1/deliveries/{delivery_id}/complete")
            assert completed.status_code == 200, completed.text
            assert test_client.post(f"/api/v1/deliveries/{delivery_id}/complete").status_code == 200

            saved_order = database.orders.find_one({"order_id": order["order_id"]})
            saved_delivery = database.deliveries.find_one({"delivery_id": delivery_id})
            stock = database.inventory.find_one({"product_id": "P-E2E"})
            assert saved_order["status"] == "FULFILLED"
            assert saved_delivery["status"] == "COMPLETED"
            assert stock["on_hand"] == 4
            assert stock["reserved"] == 0
            assert database.vehicles.find_one({"vehicle_id": "V-E2E"})["status"] == "AVAILABLE"
            assert database.inventory_movements.count_documents({"order_id": order["order_id"]}) == 2
            assert database.alerts.count_documents({"store_id": "S-E2E", "product_id": "P-E2E"}) == 1

            cancellable = test_client.post(
                "/api/v1/orders",
                headers={"Idempotency-Key": "e2e-order-cancel"},
                json={
                    "customer_id": "customer@example.com",
                    "items": [{"product_id": "P-E2E", "quantity": 1}],
                    "delivery_address": {"lat": 39.75, "lng": -104.98, "city": "Denver"},
                },
            )
            assert cancellable.status_code == 201
            cancelled_order_id = cancellable.json()["order"]["order_id"]
            cancelled = test_client.post(f"/api/v1/orders/{cancelled_order_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["order"]["status"] == "CANCELLED"

            delayed_order = test_client.post(
                "/api/v1/orders",
                headers={"Idempotency-Key": "e2e-order-delayed"},
                json={
                    "customer_id": "customer@example.com",
                    "items": [{"product_id": "P-E2E", "quantity": 1}],
                    "delivery_address": {"lat": 39.75, "lng": -104.98, "city": "Denver"},
                },
            )
            assert delayed_order.status_code == 201
            delayed_delivery_id = delayed_order.json()["order"]["delivery_id"]
            assert test_client.post(f"/api/v1/deliveries/{delayed_delivery_id}/start").status_code == 200
            delayed = test_client.post(
                f"/api/v1/deliveries/{delayed_delivery_id}/delay",
                json={"reason": "Road closure reported by the driver"},
            )
            assert delayed.status_code == 200
            assert delayed.json()["delivery"]["status"] == "DELAYED"

            from app.services.event_outbox import flush_pending_events
            from app.services.kafka_service import EventTopics, KafkaEventConsumer

            class AcceptedPublisher:
                def publish_envelope(self, _topic, envelope):
                    return envelope

            assert flush_pending_events(AcceptedPublisher()) > 0
            outbox_events = list(database.kafka_outbox.find({}, {"_id": 0}).sort("created_at", 1))
            event_types = {event["envelope"]["type"] for event in outbox_events}
            assert {
                "order.created",
                "inventory.reserved",
                "inventory.released",
                "fulfillment.assigned",
                "delivery.created",
                "delivery.started",
                "vehicle.location.updated",
                "delivery.delayed",
                "delivery.completed",
                "order.cancelled",
                "inventory.updated",
                "alert.created",
            }.issubset(event_types)

            consumer = KafkaEventConsumer(
                topic=EventTopics.ORDER_CREATED,
                group_id="mongo-e2e-business-projection",
                handler=kafka_worker.process_business_event,
                event_ledger=database.kafka_event_ledger,
                consumer=object(),
                publisher=AcceptedPublisher(),
            )
            for event in outbox_events:
                assert consumer.process_message(event["envelope"], source_topic=event["topic"]) == "processed"
            first_event = outbox_events[0]["envelope"]
            assert consumer.process_message(first_event) == "duplicate"
            assert database.order_fulfillment_views.find_one({"order_id": order["order_id"]})["status"] == "FULFILLED"
            assert database.delivery_tracking_views.find_one({"delivery_id": delivery_id})["status"] == "COMPLETED"
            assert database.inventory_availability_views.find_one(
                {"store_id": "S-E2E", "product_id": "P-E2E"}
            )["on_hand"] == 4
            assert database.kafka_event_facts.count_documents({}) == len(outbox_events)

            forecast_response = test_client.get("/api/v1/forecast/P-E2E?store_id=S-E2E")
            assert forecast_response.status_code == 200
            assert forecast_response.json()["forecast"]["sample_days"] > 0
            risks = test_client.get("/api/v1/forecast/risks?store_id=S-E2E")
            assert risks.status_code == 200
            assert risks.json()["items"][0]["risk"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

            replenishment = test_client.get("/api/v1/replenishment?store_id=S-E2E")
            assert replenishment.status_code == 200
            recommendation = replenishment.json()["items"][0]
            assert recommendation["recommended_qty"] > 0
            approved = test_client.post(
                f"/api/v1/replenishment/{recommendation['recommendation_id']}/approve"
            )
            assert approved.status_code == 200
            assert database.inventory.find_one({"product_id": "P-E2E"})["incoming"] > 0

            analytics = test_client.get("/api/v1/analytics/dashboard")
            assert analytics.status_code == 200
            assert analytics.json()["summary"]["fulfilled_orders"] == 1
            assert analytics.json()["summary"]["business_events_processed_today"] == len(outbox_events)

            alerts = test_client.get("/api/v1/alerts")
            assert alerts.status_code == 200
            alert_id = alerts.json()["items"][0]["alert_id"]
            assert test_client.post(f"/api/v1/alerts/{alert_id}/acknowledge").status_code == 200
            assert test_client.post(f"/api/v1/alerts/{alert_id}/resolve").status_code == 200

            chat = test_client.post(
                "/api/v1/chat/query",
                json={
                    "question": f"Why was {order['order_id']} fulfilled from this location?",
                    "page_context": {
                        "page": "/orders",
                        "entity_type": "order",
                        "entity_id": order["order_id"],
                    },
                },
            )
            assert chat.status_code == 200
            assert chat.json()["status"] == "not_configured"
            assert "OPENAI_API_KEY" in chat.json()["answer"]
            history = test_client.get("/api/v1/chat/conversations")
            assert history.status_code == 200
            assert len(history.json()["conversations"]) == 1

            customer_login = test_client.post(
                "/api/v1/auth/login",
                json={"email": "other-customer@example.com", "password": "customer-password"},
            )
            assert customer_login.status_code == 200
            test_client.headers.update({"Authorization": f"Bearer {customer_login.json()['access_token']}"})
            denied_order = test_client.get(f"/api/v1/orders/{order['order_id']}")
            denied_alerts = test_client.get("/api/v1/alerts")
            spoofed_chat = test_client.post(
                "/api/v1/chat/query",
                json={"question": "Show me stockout risk", "user_role": "SUPPLY_CHAIN_MANAGER"},
            )
            assert denied_order.status_code == 403
            assert denied_alerts.status_code == 403
            assert spoofed_chat.status_code == 200
            assert spoofed_chat.json()["status"] == "not_configured"
    finally:
        client.drop_database(database.name)
        client.close()
