from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.db import db
from app.services.alert_service import create_alert
from app.services.event_outbox import queue_business_event
from app.services.fulfillment_service import NoFulfillmentCandidate, rank_fulfillment_locations
from app.services.inventory_service import (
    InsufficientInventory,
    confirm_reservation,
    release_reservation,
    reserve_inventory,
)
from app.services.operations_service import optimize_route
from app.services.kafka_service import EventTopics


class OrderWorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _queue_order_events(order: dict[str, Any]) -> list[dict[str, str]]:
    order_id = order["order_id"]
    events = [
        queue_business_event(
            EventTopics.ORDER_CREATED,
            "order.created",
            {
                "order_id": order_id,
                "items": order.get("items", []),
                "created_at": order.get("created_at", datetime.now(timezone.utc)).isoformat(),
            },
            f"order-created-{order_id}",
        )
    ]
    if order.get("status") in {"ASSIGNED", "FULFILLED", "CANCELLED"}:
        decision = order.get("fulfillment_decision", {})
        events.append(
            queue_business_event(
                EventTopics.FULFILLMENT_ASSIGNED,
                "fulfillment.assigned",
                {
                    "order_id": order_id,
                    "location_id": order.get("fulfillment_location"),
                    "score": decision.get("score"),
                    "reasons": decision.get("reasons", []),
                },
                f"fulfillment-assigned-{order_id}",
            )
        )
        if order.get("delivery_id"):
            events.append(
                queue_business_event(
                    EventTopics.DELIVERY_CREATED,
                    "delivery.created",
                    {
                        "delivery_id": order["delivery_id"],
                        "order_id": order_id,
                        "vehicle_id": order.get("vehicle_id"),
                        "route_id": order.get("route_id"),
                        "fulfillment_location": order.get("fulfillment_location"),
                    },
                    f"delivery-created-{order['delivery_id']}",
                )
            )
    if order.get("status") == "CANCELLED":
        events.append(
            queue_business_event(
                EventTopics.ORDER_CANCELLED,
                "order.cancelled",
                {"order_id": order_id, "location_id": order.get("fulfillment_location")},
                f"order-cancelled-{order_id}",
            )
        )
    return events


def create_order_workflow(payload: dict, idempotency_key: str | None = None) -> dict[str, Any]:
    if idempotency_key:
        existing = db.orders.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if existing:
            existing["event_dispatch"] = _queue_order_events(existing)
            return existing

    now = datetime.now(timezone.utc)
    order_id = f"ORD-{uuid4().hex[:12].upper()}"
    order = {
        "order_id": order_id,
        "customer_id": payload["customer_id"],
        "items": payload["items"],
        "delivery_address": payload["delivery_address"],
        "status": "PROCESSING",
        "payment_status": "paid",
        "created_at": now,
    }
    if idempotency_key:
        order["idempotency_key"] = idempotency_key
    try:
        db.orders.insert_one(order)
    except DuplicateKeyError:
        if idempotency_key:
            existing = db.orders.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
            if existing:
                existing["event_dispatch"] = _queue_order_events(existing)
                return existing
        raise
    order["event_dispatch"] = _queue_order_events(order)

    try:
        candidates = rank_fulfillment_locations(order["items"], order["delivery_address"])
    except NoFulfillmentCandidate as exc:
        db.orders.update_one({"order_id": order_id}, {"$set": {"status": "REJECTED", "failure_reason": str(exc)}})
        raise OrderWorkflowError(str(exc), 422) from exc
    if not candidates:
        message = "No location can fulfill the complete order above safety stock with an available vehicle"
        db.orders.update_one({"order_id": order_id}, {"$set": {"status": "REJECTED", "failure_reason": message}})
        raise OrderWorkflowError(message, 409)

    selected: dict | None = None
    assigned_vehicle: dict | None = None
    reserved_lines: list[dict] = []
    last_reservation_error: InsufficientInventory | None = None

    for candidate in candidates:
        reserved_lines = []
        try:
            for item in order["items"]:
                reserve_inventory(item["product_id"], candidate["location"]["store_id"], item["quantity"], order_id)
                reserved_lines.append(item)
        except InsufficientInventory as exc:
            last_reservation_error = exc
            for reserved in reversed(reserved_lines):
                release_reservation(
                    reserved["product_id"], candidate["location"]["store_id"], reserved["quantity"], order_id
                )
            continue

        for vehicle_id in candidate["vehicle_ids"]:
            assigned = db.vehicles.update_one(
                {"vehicle_id": vehicle_id, "status": "AVAILABLE", "capacity_kg": {"$gte": candidate["cargo_weight_kg"]}},
                {"$set": {"status": "ASSIGNED", "active_order_id": order_id, "updated_at": now}},
            )
            if assigned.matched_count == 1:
                assigned_vehicle = db.vehicles.find_one({"vehicle_id": vehicle_id})
                if assigned_vehicle and assigned_vehicle.get("driver_id"):
                    db.drivers.update_one(
                        {"driver_id": assigned_vehicle["driver_id"]},
                        {"$set": {"status": "ASSIGNED", "active_order_id": order_id, "updated_at": now}},
                    )
                selected = candidate
                break
        if assigned_vehicle:
            break

        for reserved in reversed(reserved_lines):
            release_reservation(
                reserved["product_id"], candidate["location"]["store_id"], reserved["quantity"], order_id
            )

    if selected is None or assigned_vehicle is None:
        message = (
            str(last_reservation_error)
            if last_reservation_error
            else "No eligible vehicle remained available for this order"
        )
        db.orders.update_one({"order_id": order_id}, {"$set": {"status": "REJECTED", "failure_reason": message}})
        raise OrderWorkflowError(message)

    location = selected["location"]
    destination = order["delivery_address"]
    route_destination = {
        "stop_id": f"{order_id}-STOP-1",
        "name": destination.get("label") or destination.get("city") or "Customer",
        "lat": float(destination["lat"]),
        "lng": float(destination["lng"]),
    }
    route_id = f"R-{uuid4().hex[:8].upper()}"
    delivery_id = f"DEL-{uuid4().hex[:10].upper()}"

    try:
        route = optimize_route(
            route_id=route_id,
            stops=[route_destination],
            starting_location={"name": location["name"], "lat": location["lat"], "lng": location["lng"]},
            vehicle_capacity_kg=float(assigned_vehicle["capacity_kg"]),
            cargo_weight_kg=selected["cargo_weight_kg"],
        )
        route["order_id"] = order_id
        route["delivery_id"] = delivery_id
        db.routes.insert_one(route)

        delivery = {
            "delivery_id": delivery_id,
            "order_id": order_id,
            "vehicle_id": assigned_vehicle["vehicle_id"],
            "driver_id": assigned_vehicle.get("driver_id"),
            "route_id": route_id,
            "fulfillment_location": location["store_id"],
            "status": "ASSIGNED",
            "current_location": route["starting_location"],
            "progress": 0.0,
            "eta_minutes": route["estimated_minutes"],
            "created_at": now,
            "updated_at": now,
        }
        db.deliveries.insert_one(delivery)
        decision = {
            "selected_location": location["store_id"],
            "score": selected["score"],
            "reasons": selected["reasons"],
            "alternatives": [
                {
                    "location_id": candidate["location"]["store_id"],
                    "score": candidate["score"],
                    "distance_km": candidate["distance_km"],
                }
                for candidate in candidates
                if candidate["location"]["store_id"] != location["store_id"]
            ],
        }
        db.orders.update_one(
            {"order_id": order_id},
            {
                "$set": {
                    "status": "ASSIGNED",
                    "fulfillment_location": location["store_id"],
                    "vehicle_id": assigned_vehicle["vehicle_id"],
                    "route_id": route_id,
                    "delivery_id": delivery_id,
                    "fulfillment_decision": decision,
                    "delivery_details": {
                        "eta_minutes": route["estimated_minutes"],
                        "distance_km": route["optimized_distance_km"],
                    },
                    "updated_at": now,
                }
            },
        )
    except Exception:
        for reserved in reversed(reserved_lines):
            release_reservation(
                reserved["product_id"], location["store_id"], reserved["quantity"], order_id
            )
        db.vehicles.update_one(
            {"vehicle_id": assigned_vehicle["vehicle_id"]},
            {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": datetime.now(timezone.utc)}},
        )
        if assigned_vehicle.get("driver_id"):
            db.drivers.update_one(
                {"driver_id": assigned_vehicle["driver_id"]},
                {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": datetime.now(timezone.utc)}},
            )
        raise

    assigned_order = db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if assigned_order:
        assigned_order["event_dispatch"] = _queue_order_events(assigned_order)
    return assigned_order


def complete_delivery(delivery_id: str) -> dict[str, Any]:
    delivery = db.deliveries.find_one({"delivery_id": delivery_id})
    if not delivery:
        raise OrderWorkflowError("Delivery not found", 404)
    if delivery["status"] == "COMPLETED":
        _queue_delivery_completed_events(delivery)
        return db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
    if delivery["status"] not in {"IN_TRANSIT", "DELAYED"} or delivery.get("progress", 0) < 1:
        raise OrderWorkflowError("Delivery must be started and all route stops completed")
    previous_status = delivery["status"]
    claimed = db.deliveries.update_one(
        {"delivery_id": delivery_id, "status": previous_status, "progress": {"$gte": 1}},
        {"$set": {"status": "COMPLETING", "updated_at": datetime.now(timezone.utc)}},
    )
    if claimed.matched_count != 1:
        raise OrderWorkflowError("Delivery is already being completed")
    order = db.orders.find_one({"order_id": delivery["order_id"]})
    confirmed: list[dict] = []
    try:
        for item in order["items"]:
            confirm_reservation(
                item["product_id"],
                delivery["fulfillment_location"],
                item["quantity"],
                order["order_id"],
                publish_update_event=False,
            )
            confirmed.append(item)
    except Exception as exc:
        for item in reversed(confirmed):
            result = db.inventory.update_one(
                {"product_id": item["product_id"], "store_id": delivery["fulfillment_location"]},
                {
                    "$inc": {"on_hand": item["quantity"], "reserved": item["quantity"]},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
            )
            if result.matched_count != 1:
                raise RuntimeError("Delivery failure could not restore inventory") from exc
            db.inventory_movements.insert_one(
                {
                    "product_id": item["product_id"],
                    "store_id": delivery["fulfillment_location"],
                    "order_id": order["order_id"],
                    "quantity": item["quantity"],
                    "type": "FULFILLMENT_ROLLBACK",
                    "created_at": datetime.now(timezone.utc),
                }
            )
        db.deliveries.update_one(
            {"delivery_id": delivery_id, "status": "COMPLETING"},
            {"$set": {"status": previous_status, "updated_at": datetime.now(timezone.utc)}},
        )
        raise
    now = datetime.now(timezone.utc)
    db.deliveries.update_one(
        {"delivery_id": delivery_id, "status": "COMPLETING"},
        {"$set": {"status": "COMPLETED", "progress": 1.0, "completed_at": now, "updated_at": now}},
    )
    db.orders.update_one({"order_id": order["order_id"]}, {"$set": {"status": "FULFILLED", "updated_at": now}})
    db.vehicles.update_one(
        {"vehicle_id": delivery["vehicle_id"]},
        {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": now}},
    )
    if delivery.get("driver_id"):
        db.drivers.update_one(
            {"driver_id": delivery["driver_id"]},
            {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": now}},
        )
    completed_delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
    if completed_delivery:
        _queue_delivery_completed_events(completed_delivery)
    return completed_delivery


def _queue_delivery_completed_events(delivery: dict[str, Any]) -> list[dict[str, str]]:
    delivery_id = delivery["delivery_id"]
    order = db.orders.find_one({"order_id": delivery["order_id"]}, {"_id": 0}) or {}
    events = [
        queue_business_event(
            EventTopics.DELIVERY_COMPLETED,
            "delivery.completed",
            {
                "delivery_id": delivery_id,
                "order_id": delivery["order_id"],
                "fulfillment_location": delivery.get("fulfillment_location"),
            },
            f"delivery-completed-{delivery_id}",
        )
    ]
    for item in order.get("items", []):
        inventory = db.inventory.find_one(
            {"product_id": item["product_id"], "store_id": delivery["fulfillment_location"]},
            {"_id": 0},
        )
        if inventory:
            events.append(
                queue_business_event(
                    EventTopics.INVENTORY_UPDATED,
                    "inventory.updated",
                    {
                        "product_id": inventory["product_id"],
                        "store_id": inventory["store_id"],
                        "order_id": delivery["order_id"],
                        "movement_id": None,
                        "on_hand": inventory.get("on_hand", 0),
                        "reserved": inventory.get("reserved", 0),
                        "available": inventory.get("on_hand", 0) - inventory.get("reserved", 0),
                    },
                    f"inventory-updated-{delivery_id}-{item['product_id']}",
                )
            )
            available = inventory.get("on_hand", 0) - inventory.get("reserved", 0)
            if available <= inventory.get("reorder_point", 0):
                create_alert(
                    alert_id=f"LOWSTOCK-{delivery['fulfillment_location']}-{item['product_id']}",
                    title="Inventory at or below reorder point",
                    severity="CRITICAL" if available <= 0 else "WARNING",
                    message=f"Available quantity is {available}; reorder point is {inventory.get('reorder_point', 0)}.",
                    store_id=delivery["fulfillment_location"],
                    product_id=item["product_id"],
                )
    return events


def cancel_order(order_id: str) -> dict[str, Any]:
    order = db.orders.find_one({"order_id": order_id})
    if not order:
        raise OrderWorkflowError("Order not found", 404)
    if order["status"] == "CANCELLED":
        return db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if order["status"] != "ASSIGNED":
        raise OrderWorkflowError(f"Cannot cancel order in {order['status']} state")
    delivery = db.deliveries.find_one({"delivery_id": order["delivery_id"]})
    if delivery:
        cancelled_delivery = db.deliveries.update_one(
            {"delivery_id": delivery["delivery_id"], "status": "ASSIGNED"},
            {"$set": {"status": "CANCELLED", "updated_at": datetime.now(timezone.utc)}},
        )
        if cancelled_delivery.matched_count != 1:
            raise OrderWorkflowError("An order cannot be cancelled after its delivery has started")
    for item in order["items"]:
        release_reservation(item["product_id"], order["fulfillment_location"], item["quantity"], order_id)
    now = datetime.now(timezone.utc)
    if delivery:
        db.vehicles.update_one(
            {"vehicle_id": delivery["vehicle_id"]},
            {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": now}},
        )
        if delivery.get("driver_id"):
            db.drivers.update_one(
                {"driver_id": delivery["driver_id"]},
                {"$set": {"status": "AVAILABLE", "active_order_id": None, "updated_at": now}},
            )
    db.orders.update_one(
        {"order_id": order_id, "status": "ASSIGNED"}, {"$set": {"status": "CANCELLED", "updated_at": now}}
    )
    cancelled_order = db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if cancelled_order:
        cancelled_order["event_dispatch"] = _queue_order_events(cancelled_order)
    return cancelled_order
