from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace

import pytest

from app.services import alert_service, fulfillment_service, inventory_service, workflow_service
from app.services.inventory_service import InsufficientInventory
from app.services.operations_service import optimize_route


class UpdateResult:
    def __init__(self, matched_count: int):
        self.matched_count = matched_count


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = deepcopy(documents or [])
        self.lock = Lock()

    @staticmethod
    def _matches(document, query):
        def evaluate(expression):
            if isinstance(expression, dict):
                if "$ifNull" in expression:
                    value = evaluate(expression["$ifNull"][0])
                    return expression["$ifNull"][1] if value is None else value
                if "$subtract" in expression:
                    left, right = expression["$subtract"]
                    return evaluate(left) - evaluate(right)
            if isinstance(expression, str) and expression.startswith("$"):
                return document.get(expression[1:], 0)
            return expression

        for key, expected in query.items():
            if key == "$expr":
                left, right = expected["$gte"]
                if evaluate(left) < right:
                    return False
                continue
            actual = document.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                    return False
                if "$in" not in expected and "$gte" not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def find(self, query=None, *args, **kwargs):
        return [deepcopy(row) for row in self.documents if self._matches(row, query or {})]

    def find_one(self, query=None, *args, **kwargs):
        for row in self.documents:
            if self._matches(row, query or {}):
                return deepcopy(row)
        return None

    def count_documents(self, query=None):
        return sum(self._matches(row, query or {}) for row in self.documents)

    def insert_one(self, document):
        self.documents.append(deepcopy(document))

    def update_one(self, query, update):
        with self.lock:
            for row in self.documents:
                if self._matches(row, query):
                    for key, value in update.get("$set", {}).items():
                        row[key] = value
                    for key, value in update.get("$inc", {}).items():
                        row[key] = row.get(key, 0) + value
                    return UpdateResult(1)
        return UpdateResult(0)


def make_database(inventory_rows):
    return SimpleNamespace(
        inventory=MemoryCollection(inventory_rows),
        inventory_movements=MemoryCollection(),
        products=MemoryCollection([{"product_id": "P-1001", "name": "Drill", "weight_kg": 2.8}]),
        stores=MemoryCollection(
            [
                {"store_id": "store-01", "name": "Seattle", "city": "Seattle", "lat": 47.6062, "lng": -122.3321},
                {"store_id": "store-14", "name": "Denver", "city": "Denver", "lat": 39.7392, "lng": -104.9903},
            ]
        ),
        vehicles=MemoryCollection(
            [
                {"vehicle_id": "veh-10", "driver_id": "DRV-10", "status": "AVAILABLE", "capacity_kg": 350},
                {"vehicle_id": "veh-11", "driver_id": "DRV-11", "status": "AVAILABLE", "capacity_kg": 500},
            ]
        ),
        drivers=MemoryCollection(
            [
                {"driver_id": "DRV-10", "status": "AVAILABLE"},
                {"driver_id": "DRV-11", "status": "AVAILABLE"},
            ]
        ),
        deliveries=MemoryCollection(),
        orders=MemoryCollection(),
        routes=MemoryCollection(),
    )


@pytest.fixture(autouse=True)
def mock_business_event_outbox(monkeypatch):
    def queued(*args, **kwargs):
        return {"event_id": kwargs.get("event_id", "test-event"), "status": "pending"}

    monkeypatch.setattr(inventory_service, "queue_business_event", queued)
    monkeypatch.setattr(workflow_service, "queue_business_event", queued)
    monkeypatch.setattr(alert_service, "queue_business_event", queued)


def test_atomic_reservation_allows_only_available_quantity(monkeypatch):
    database = make_database(
        [{"store_id": "store-14", "product_id": "P-1001", "on_hand": 5, "reserved": 0, "safety_stock": 0}]
    )
    monkeypatch.setattr(inventory_service, "db", database)

    def try_reserve(number):
        try:
            inventory_service.reserve_inventory("P-1001", "store-14", 1, f"order-{number}")
            return True
        except InsufficientInventory:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(try_reserve, range(10)))

    assert sum(results) == 5
    assert database.inventory.documents[0]["reserved"] == 5
    assert len(database.inventory_movements.documents) == 5


def test_atomic_reservation_preserves_safety_stock(monkeypatch):
    database = make_database(
        [{"store_id": "store-14", "product_id": "P-1001", "on_hand": 5, "reserved": 0, "safety_stock": 2}]
    )
    monkeypatch.setattr(inventory_service, "db", database)

    with pytest.raises(InsufficientInventory):
        inventory_service.reserve_inventory("P-1001", "store-14", 4, "order-too-large")
    inventory_service.reserve_inventory("P-1001", "store-14", 3, "order-exact")

    assert database.inventory.documents[0]["reserved"] == 3


def test_workflow_reserves_selects_location_generates_route_and_completes(monkeypatch):
    database = make_database(
        [
            {"store_id": "store-01", "product_id": "P-1001", "on_hand": 18, "reserved": 4, "safety_stock": 6},
            {"store_id": "store-14", "product_id": "P-1001", "on_hand": 7, "reserved": 3, "safety_stock": 1},
        ]
    )
    monkeypatch.setattr(inventory_service, "db", database)
    monkeypatch.setattr(fulfillment_service, "db", database)
    monkeypatch.setattr(workflow_service, "db", database)
    request = {
        "customer_id": "customer@example.test",
        "items": [{"product_id": "P-1001", "quantity": 1}],
        "delivery_address": {"lat": 39.7392, "lng": -104.9903, "city": "Denver"},
    }

    order = workflow_service.create_order_workflow(request, "checkout-123")
    assert order["status"] == "ASSIGNED"
    assert order["fulfillment_location"] == "store-14"
    assert order["fulfillment_decision"]["score"] > 0
    assert database.inventory.documents[1]["reserved"] == 4
    assert len(database.routes.documents) == 1
    assert database.routes.documents[0]["optimized_distance_km"] == 0

    duplicate = workflow_service.create_order_workflow(request, "checkout-123")
    assert duplicate["order_id"] == order["order_id"]
    assert len(database.deliveries.documents) == 1

    delivery = database.deliveries.documents[0]
    delivery["status"] = "IN_TRANSIT"
    delivery["progress"] = 1
    completed = workflow_service.complete_delivery(delivery["delivery_id"])
    assert completed["status"] == "COMPLETED"
    assert database.inventory.documents[1]["on_hand"] == 6
    assert database.inventory.documents[1]["reserved"] == 3
    assert database.orders.documents[0]["status"] == "FULFILLED"
    assert all(vehicle["status"] == "AVAILABLE" for vehicle in database.vehicles.documents)

    second_order = workflow_service.create_order_workflow(request)
    assert database.inventory.documents[1]["reserved"] == 4
    cancelled = workflow_service.cancel_order(second_order["order_id"])
    assert cancelled["status"] == "CANCELLED"
    assert database.inventory.documents[1]["reserved"] == 3
    assert all(vehicle["status"] == "AVAILABLE" for vehicle in database.vehicles.documents)


def test_route_optimizer_returns_capacity_and_stop_eta():
    route = optimize_route(
        route_id="R-TEST",
        starting_location={"lat": 39.7392, "lng": -104.9903},
        stops=[
            {"stop_id": "B", "name": "B", "lat": 39.75, "lng": -104.98},
            {"stop_id": "A", "name": "A", "lat": 39.74, "lng": -104.99},
        ],
        vehicle_capacity_kg=20,
        cargo_weight_kg=5,
    )
    assert route["baseline_distance_km"] >= route["optimized_distance_km"]
    assert len(route["stops"]) == 2
    assert route["stops"][0]["eta_minutes"] > 0
    with pytest.raises(ValueError, match="capacity"):
        optimize_route(
            route_id="R-OVER",
            stops=[{"stop_id": "A", "lat": 39.74, "lng": -104.99}],
            starting_location={"lat": 39.7392, "lng": -104.9903},
            vehicle_capacity_kg=2,
            cargo_weight_kg=5,
        )
