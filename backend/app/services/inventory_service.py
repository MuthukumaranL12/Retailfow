from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.db import db
from app.services.event_outbox import queue_business_event
from app.services.kafka_service import EventTopics


class InsufficientInventory(Exception):
    pass


def _queue_movement_events(
    movement: dict[str, Any],
    event_type: str | None = None,
    event_topic: str | None = None,
) -> None:
    common_payload = {
        "movement_id": movement["movement_id"],
        "product_id": movement["product_id"],
        "store_id": movement["store_id"],
        "order_id": movement.get("order_id"),
        "quantity": movement["quantity"],
    }
    if event_type and event_topic:
        queue_business_event(
            event_topic,
            event_type,
            common_payload,
            f"{movement['movement_id']}-{event_type}",
        )
    inventory = db.inventory.find_one(
        {"product_id": movement["product_id"], "store_id": movement["store_id"]},
        {"_id": 0},
    )
    if inventory:
        queue_business_event(
            EventTopics.INVENTORY_UPDATED,
            "inventory.updated",
            {
                **common_payload,
                "on_hand": inventory.get("on_hand", 0),
                "reserved": inventory.get("reserved", 0),
                "available": inventory.get("on_hand", 0) - inventory.get("reserved", 0),
            },
            f"{movement['movement_id']}-inventory-updated",
        )


def reserve_inventory(product_id: str, store_id: str, quantity: int, order_id: str) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")
    now = datetime.now(timezone.utc)
    result = db.inventory.update_one(
        {
            "product_id": product_id,
            "store_id": store_id,
            "$expr": {
                "$gte": [
                    {
                        "$subtract": [
                            {"$subtract": [{"$ifNull": ["$on_hand", 0]}, {"$ifNull": ["$reserved", 0]}]},
                            {"$ifNull": ["$safety_stock", 0]},
                        ]
                    },
                    quantity,
                ]
            },
        },
        {"$inc": {"reserved": quantity}, "$set": {"updated_at": now}},
    )
    if result.matched_count != 1:
        raise InsufficientInventory(f"Insufficient inventory for {product_id} at {store_id}")
    movement = {
        "movement_id": uuid4().hex,
        "product_id": product_id,
        "store_id": store_id,
        "order_id": order_id,
        "quantity": quantity,
        "type": "RESERVATION",
        "created_at": now,
    }
    try:
        db.inventory_movements.insert_one(movement)
        _queue_movement_events(movement, "inventory.reserved", EventTopics.INVENTORY_RESERVED)
    except Exception as exc:
        rollback = db.inventory.update_one(
            {"product_id": product_id, "store_id": store_id, "reserved": {"$gte": quantity}},
            {"$inc": {"reserved": -quantity}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        if rollback.matched_count != 1:
            raise RuntimeError("Reservation movement failed and inventory rollback also failed") from exc
        db.inventory_movements.delete_one({"movement_id": movement["movement_id"]})
        raise


def release_reservation(product_id: str, store_id: str, quantity: int, order_id: str) -> None:
    result = db.inventory.update_one(
        {"product_id": product_id, "store_id": store_id, "reserved": {"$gte": quantity}},
        {"$inc": {"reserved": -quantity}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count != 1:
        raise RuntimeError(f"Could not release reservation for {product_id} at {store_id}")
    movement = {
        "movement_id": uuid4().hex,
        "product_id": product_id,
        "store_id": store_id,
        "order_id": order_id,
        "quantity": -quantity,
        "type": "RESERVATION_RELEASE",
        "created_at": datetime.now(timezone.utc),
    }
    try:
        db.inventory_movements.insert_one(movement)
        _queue_movement_events(movement, "inventory.released", EventTopics.INVENTORY_RELEASED)
    except Exception as exc:
        rollback = db.inventory.update_one(
            {"product_id": product_id, "store_id": store_id},
            {"$inc": {"reserved": quantity}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        if rollback.matched_count != 1:
            raise RuntimeError("Reservation release movement failed and inventory rollback also failed") from exc
        db.inventory_movements.delete_one({"movement_id": movement["movement_id"]})
        raise


def confirm_reservation(
    product_id: str,
    store_id: str,
    quantity: int,
    order_id: str,
    publish_update_event: bool = True,
) -> None:
    now = datetime.now(timezone.utc)
    result = db.inventory.update_one(
        {
            "product_id": product_id,
            "store_id": store_id,
            "reserved": {"$gte": quantity},
            "on_hand": {"$gte": quantity},
        },
        {
            "$inc": {"reserved": -quantity, "on_hand": -quantity},
            "$set": {"updated_at": now},
        },
    )
    if result.matched_count != 1:
        raise RuntimeError(f"Could not confirm reservation for {product_id} at {store_id}")
    movement = {
        "movement_id": uuid4().hex,
        "product_id": product_id,
        "store_id": store_id,
        "order_id": order_id,
        "quantity": -quantity,
        "type": "FULFILLMENT",
        "created_at": now,
    }
    try:
        db.inventory_movements.insert_one(movement)
        if publish_update_event:
            _queue_movement_events(movement)
    except Exception as exc:
        rollback = db.inventory.update_one(
            {"product_id": product_id, "store_id": store_id},
            {"$inc": {"reserved": quantity, "on_hand": quantity}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        if rollback.matched_count != 1:
            raise RuntimeError("Fulfillment movement failed and inventory rollback also failed") from exc
        db.inventory_movements.delete_one({"movement_id": movement["movement_id"]})
        raise


def restock_inventory(product_id: str, store_id: str, quantity: int, reference: str | None = None) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")
    now = datetime.now(timezone.utc)
    result = db.inventory.update_one(
        {"product_id": product_id, "store_id": store_id},
        {"$inc": {"on_hand": quantity}, "$set": {"updated_at": now}},
    )
    if result.matched_count != 1:
        raise LookupError(f"Inventory record not found for {product_id} at {store_id}")
    movement = {
        "movement_id": uuid4().hex,
        "product_id": product_id,
        "store_id": store_id,
        "quantity": quantity,
        "type": "RESTOCK",
        "reference": reference,
        "created_at": now,
    }
    try:
        db.inventory_movements.insert_one(movement)
        _queue_movement_events(movement)
    except Exception as exc:
        rollback = db.inventory.update_one(
            {"product_id": product_id, "store_id": store_id},
            {"$inc": {"on_hand": -quantity}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        if rollback.matched_count != 1:
            raise RuntimeError("Restock movement failed and inventory rollback also failed") from exc
        db.inventory_movements.delete_one({"movement_id": movement["movement_id"]})
        raise
    return movement
