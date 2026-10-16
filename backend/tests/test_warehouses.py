from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import warehouses
from app.services import warehouse_service


class Cursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, key, direction=1):
        self.documents.sort(key=lambda item: item.get(key, ""), reverse=direction < 0)
        return self

    def skip(self, count):
        self.documents = self.documents[count:]
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self, documents=None):
        self.documents = deepcopy(documents or [])

    @staticmethod
    def _matches(document, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(Collection._matches(document, clause) for clause in expected):
                    return False
            elif isinstance(expected, dict):
                actual = document.get(key)
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                    return False
            elif document.get(key) != expected:
                return False
        return True

    def find(self, query=None, projection=None):
        return Cursor(
            deepcopy([item for item in self.documents if self._matches(item, query or {})])
        )

    def find_one(self, query, projection=None):
        return next(
            (deepcopy(item) for item in self.documents if self._matches(item, query)),
            None,
        )

    def count_documents(self, query):
        return sum(self._matches(item, query) for item in self.documents)

    def insert_one(self, document):
        self.documents.append(deepcopy(document))

    def update_one(self, query, update):
        for item in self.documents:
            if self._matches(item, query):
                item.update(deepcopy(update.get("$set", {})))
                return

    def delete_one(self, query):
        for index, item in enumerate(self.documents):
            if self._matches(item, query):
                del self.documents[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


def _fake_db():
    return SimpleNamespace(
        warehouses=Collection(
            [
                {
                    "warehouse_id": "wh-east",
                    "name": "East DC",
                    "status": "ACTIVE",
                    "city": "Boston",
                }
            ]
        ),
        inventory=Collection(
            [
                {
                    "warehouse_id": "wh-east",
                    "product_id": "p1",
                    "on_hand": 8,
                    "reserved": 3,
                    "reorder_point": 6,
                },
                {
                    "warehouse_id": "wh-east",
                    "product_id": "p2",
                    "on_hand": 4,
                    "reserved": 4,
                    "reorder_point": 2,
                },
            ]
        ),
        orders=Collection(
            [
                {
                    "order_id": "o1",
                    "fulfillment_location": "wh-east",
                    "status": "FULFILLED",
                    "fulfillment_decision": {"selected_location": "wh-east", "score": 76},
                    "items": [{"product_id": "p1", "quantity": 1}],
                },
                {
                    "order_id": "o2",
                    "fulfillment_location": "wh-east",
                    "status": "PROCESSING",
                },
            ]
        ),
        deliveries=Collection(
            [
                {
                    "delivery_id": "d1",
                    "order_id": "o1",
                    "fulfillment_location": "wh-east",
                    "status": "COMPLETED",
                }
            ]
        ),
        alerts=Collection(
            [
                {
                    "alert_id": "a1",
                    "warehouse_id": "wh-east",
                    "severity": "CRITICAL",
                    "acknowledged": False,
                }
            ]
        ),
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(warehouse_service, "db", _fake_db())
    app = FastAPI()
    app.include_router(warehouses.router, prefix="/api/v1")
    app.dependency_overrides[warehouses.get_current_user] = lambda: {
        "email": "admin@example.com",
        "role": "ADMIN",
    }
    return TestClient(app)


def test_warehouse_dashboard_uses_persisted_operational_records(client):
    response = client.get("/api/v1/warehouses/wh-east")
    assert response.status_code == 200
    body = response.json()
    assert body["warehouse"]["name"] == "East DC"
    assert body["summary"]["inventory"] == {
        "product_count": 2,
        "on_hand_units": 12,
        "reserved_units": 7,
        "available_units": 5,
        "low_stock_items": 1,
        "stockout_items": 1,
    }
    assert body["summary"]["orders"]["total"] == 2
    assert body["summary"]["orders"]["completion_rate"] == 50
    assert body["summary"]["deliveries"]["average_duration_minutes"] is None
    assert body["summary"]["alerts"]["critical"] == 1
    assert body["orders"][0]["fulfillment_decision"]["score"] == 76

    decisions = client.get("/api/v1/warehouses/wh-east/decisions")
    assert decisions.status_code == 200
    assert decisions.json()["items"][0]["decision"]["selected_location"] == "wh-east"


def test_warehouse_crud_and_status_validation(client):
    created = client.post(
        "/api/v1/warehouses",
        json={"warehouse_id": "wh-west", "name": "West DC", "status": "ACTIVE"},
    )
    assert created.status_code == 201
    assert created.json()["warehouse"]["warehouse_id"] == "wh-west"

    updated = client.patch("/api/v1/warehouses/wh-west", json={"city": "Portland"})
    assert updated.status_code == 200
    assert updated.json()["warehouse"]["city"] == "Portland"

    invalid = client.patch(
        "/api/v1/warehouses/wh-west/status", json={"status": "BROKEN"}
    )
    assert invalid.status_code == 422

    status_update = client.patch(
        "/api/v1/warehouses/wh-west/status", json={"status": "MAINTENANCE"}
    )
    assert status_update.status_code == 200
    assert status_update.json()["warehouse"]["status"] == "MAINTENANCE"

    deleted = client.delete("/api/v1/warehouses/wh-west")
    assert deleted.status_code == 200
    assert client.get("/api/v1/warehouses/wh-west").status_code == 404


def test_role_scope_and_delete_guard(client):
    client.app.dependency_overrides[warehouses.get_current_user] = lambda: {
        "email": "manager@example.com",
        "role": "WAREHOUSE_MANAGER",
        "warehouse_id": "wh-east",
    }
    assert client.get("/api/v1/warehouses").status_code == 200
    assert client.get("/api/v1/warehouses/other").status_code == 403
    assert client.post("/api/v1/warehouses", json={"name": "Not allowed"}).status_code == 403
    assert client.delete("/api/v1/warehouses/wh-east").status_code == 403

    client.app.dependency_overrides[warehouses.get_current_user] = lambda: {
        "email": "admin@example.com",
        "role": "ADMIN",
    }
    assert client.delete("/api/v1/warehouses/wh-east").status_code == 409
