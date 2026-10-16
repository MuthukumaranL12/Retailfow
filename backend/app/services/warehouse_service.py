from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.db import db

WAREHOUSE_STATUSES = {"ACTIVE", "INACTIVE", "MAINTENANCE", "CLOSED"}
ACTIVE_DELIVERY_STATUSES = {"ASSIGNED", "IN_TRANSIT", "DELAYED"}
COMPLETED_STATUSES = {"COMPLETED", "FULFILLED"}


class WarehouseConflict(Exception):
    pass


def _warehouse_key(warehouse_id: str) -> dict[str, Any]:
    return {"$or": [{"warehouse_id": warehouse_id}, {"store_id": warehouse_id}]}


def _sort_limit(collection: Any, query: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    cursor = collection.find(query, {"_id": 0})
    try:
        cursor = cursor.sort("created_at", -1)
    except (AttributeError, TypeError):
        pass
    try:
        cursor = cursor.limit(limit)
    except (AttributeError, TypeError):
        pass
    return list(cursor)


def get_warehouse(warehouse_id: str) -> dict[str, Any] | None:
    return db.warehouses.find_one({"warehouse_id": warehouse_id}, {"_id": 0})


def list_warehouses(
    status: str | None = None,
    warehouse_ids: list[str] | None = None,
    limit: int = 100,
    skip: int = 0,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if status:
        query["status"] = status.upper()
    if warehouse_ids is not None:
        query["warehouse_id"] = {"$in": warehouse_ids}
    cursor = db.warehouses.find(query, {"_id": 0}).sort("name", 1).skip(skip).limit(limit)
    return list(cursor)


def create_warehouse(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    warehouse = {
        **data,
        "warehouse_id": data.get("warehouse_id") or f"WH-{uuid4().hex[:12].upper()}",
        "status": data.get("status", "ACTIVE").upper(),
        "created_at": now,
        "updated_at": now,
    }
    if db.warehouses.find_one({"warehouse_id": warehouse["warehouse_id"]}):
        raise WarehouseConflict("Warehouse ID already exists")
    db.warehouses.insert_one(warehouse)
    return get_warehouse(warehouse["warehouse_id"]) or warehouse


def update_warehouse(warehouse_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    if not get_warehouse(warehouse_id):
        return None
    if "status" in changes:
        changes["status"] = changes["status"].upper()
    changes["updated_at"] = datetime.now(timezone.utc)
    db.warehouses.update_one({"warehouse_id": warehouse_id}, {"$set": changes})
    return get_warehouse(warehouse_id)


def delete_warehouse(warehouse_id: str) -> bool:
    if not get_warehouse(warehouse_id):
        return False
    if (
        db.inventory.count_documents(_warehouse_key(warehouse_id))
        or db.orders.count_documents({"fulfillment_location": warehouse_id, "status": {"$in": list(ACTIVE_DELIVERY_STATUSES)}})
        or db.deliveries.count_documents({"fulfillment_location": warehouse_id, "status": {"$in": list(ACTIVE_DELIVERY_STATUSES)}})
    ):
        raise WarehouseConflict("Warehouse has inventory or active fulfillment and cannot be deleted")
    return db.warehouses.delete_one({"warehouse_id": warehouse_id}).deleted_count == 1


def update_warehouse_status(warehouse_id: str, status: str) -> dict[str, Any] | None:
    return update_warehouse(warehouse_id, {"status": status})


def _orders_for(warehouse_id: str, limit: int) -> list[dict[str, Any]]:
    return _sort_limit(db.orders, {"fulfillment_location": warehouse_id}, limit)


def _deliveries_for(warehouse_id: str, order_ids: list[str], limit: int) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"fulfillment_location": warehouse_id}
    deliveries = _sort_limit(db.deliveries, query, limit)
    if order_ids:
        seen = {item.get("delivery_id") for item in deliveries}
        linked = _sort_limit(db.deliveries, {"order_id": {"$in": order_ids}}, limit)
        deliveries.extend(
            item for item in linked if item.get("delivery_id") not in seen
        )
    return deliveries[:limit]


def _alerts_for(warehouse_id: str, limit: int) -> list[dict[str, Any]]:
    alerts = _sort_limit(db.alerts, {"warehouse_id": warehouse_id}, limit)
    seen = {item.get("alert_id") for item in alerts}
    linked = _sort_limit(db.alerts, {"store_id": warehouse_id}, limit)
    alerts.extend(item for item in linked if item.get("alert_id") not in seen)
    return alerts[:limit]


def get_warehouse_dashboard(warehouse_id: str, include_records: bool = True) -> dict[str, Any]:
    warehouse = get_warehouse(warehouse_id)
    if not warehouse:
        raise LookupError("Warehouse not found")

    inventory = list(db.inventory.find(_warehouse_key(warehouse_id), {"_id": 0}).limit(1000))
    orders = _orders_for(warehouse_id, 1000)
    order_ids = [order["order_id"] for order in orders if order.get("order_id")]
    deliveries = _deliveries_for(warehouse_id, order_ids, 1000)
    alerts = _alerts_for(warehouse_id, 1000)
    available_values = [
        float(row.get("on_hand", 0) or 0) - float(row.get("reserved", 0) or 0)
        for row in inventory
    ]
    low_stock = sum(
        0 < available <= float(row.get("reorder_point", 0) or 0)
        for row, available in zip(inventory, available_values)
    )
    stockouts = sum(value <= 0 for value in available_values)
    completed_orders = sum(str(order.get("status", "")).upper() in COMPLETED_STATUSES for order in orders)
    completed_deliveries = [
        delivery
        for delivery in deliveries
        if str(delivery.get("status", "")).upper() in COMPLETED_STATUSES
    ]
    active_orders = sum(str(order.get("status", "")).upper() in ACTIVE_DELIVERY_STATUSES for order in orders)
    active_deliveries = sum(
        str(delivery.get("status", "")).upper() in ACTIVE_DELIVERY_STATUSES for delivery in deliveries
    )
    durations = []
    for delivery in completed_deliveries:
        started, completed = delivery.get("started_at"), delivery.get("completed_at")
        if isinstance(started, datetime) and isinstance(completed, datetime):
            duration = (completed - started).total_seconds() / 60
            if duration >= 0:
                durations.append(duration)
    total_orders = len(orders)
    summary = {
        "inventory": {
            "product_count": len(inventory),
            "on_hand_units": sum(float(row.get("on_hand", 0) or 0) for row in inventory),
            "reserved_units": sum(float(row.get("reserved", 0) or 0) for row in inventory),
            "available_units": sum(available_values),
            "low_stock_items": low_stock,
            "stockout_items": stockouts,
        },
        "orders": {
            "total": total_orders,
            "active": active_orders,
            "completed": completed_orders,
            "completion_rate": round(completed_orders * 100 / total_orders, 2) if total_orders else None,
        },
        "deliveries": {
            "total": len(deliveries),
            "active": active_deliveries,
            "completed": len(completed_deliveries),
            "delayed": sum(str(row.get("status", "")).upper() == "DELAYED" for row in deliveries),
            "average_duration_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        },
        "alerts": {
            "total": len(alerts),
            "open": sum(not row.get("acknowledged", False) and not row.get("resolved", False) for row in alerts),
            "critical": sum(str(row.get("severity", "")).upper() == "CRITICAL" for row in alerts),
        },
    }
    result: dict[str, Any] = {"warehouse": warehouse, "summary": summary}
    if include_records:
        result["inventory_items"] = inventory
        result["orders"] = orders[:100]
        result["deliveries"] = deliveries[:100]
        result["alerts"] = alerts[:100]
    return result


def get_warehouse_decisions(warehouse_id: str, limit: int = 100) -> list[dict[str, Any]]:
    orders = _sort_limit(db.orders, {"fulfillment_location": warehouse_id}, limit)
    return [
        {
            "order_id": order.get("order_id"),
            "status": order.get("status"),
            "created_at": order.get("created_at"),
            "fulfillment_location": order.get("fulfillment_location"),
            "decision": order.get("fulfillment_decision"),
            "items": order.get("items", []),
        }
        for order in orders
    ]


def compare_warehouses(warehouse_ids: list[str]) -> list[dict[str, Any]]:
    results = []
    for warehouse_id in warehouse_ids:
        if get_warehouse(warehouse_id):
            dashboard = get_warehouse_dashboard(warehouse_id, include_records=False)
            results.append(
                {
                    "warehouse": dashboard["warehouse"],
                    "summary": dashboard["summary"],
                }
            )
    return results
