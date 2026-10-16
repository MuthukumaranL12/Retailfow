from datetime import datetime, timezone
from typing import Any

from app.db import db
from app.services.event_outbox import queue_business_event
from app.services.kafka_service import EventTopics


class ReplenishmentNotFound(Exception):
    pass


class ReplenishmentForbidden(Exception):
    pass


class ReplenishmentConflict(Exception):
    pass


def approve_recommendation(recommendation_id: str, current_user: dict[str, Any]) -> dict[str, str]:
    recommendation = db.replenishment_recommendations.find_one(
        {"recommendation_id": recommendation_id}
    )
    if not recommendation:
        raise ReplenishmentNotFound("Replenishment recommendation not found")

    role = current_user.get("role")
    if role not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "STORE_MANAGER"}:
        raise ReplenishmentForbidden("Insufficient permissions")
    if role == "STORE_MANAGER" and current_user.get("store_id") != recommendation["store_id"]:
        raise ReplenishmentForbidden("Not authorized for this store")

    now = datetime.now(timezone.utc)
    result = db.replenishment_recommendations.update_one(
        {"recommendation_id": recommendation_id, "status": "PENDING"},
        {
            "$set": {
                "status": "APPROVED",
                "approved_by": current_user["email"],
                "approved_at": now,
            }
        },
    )
    if result.matched_count != 1:
        raise ReplenishmentConflict("Recommendation is no longer pending")

    inventory_update = db.inventory.update_one(
        {"store_id": recommendation["store_id"], "product_id": recommendation["product_id"]},
        {"$inc": {"incoming": recommendation["recommended_qty"]}},
    )
    if inventory_update.matched_count != 1:
        db.replenishment_recommendations.update_one(
            {"recommendation_id": recommendation_id, "status": "APPROVED"},
            {"$set": {"status": "PENDING"}, "$unset": {"approved_by": "", "approved_at": ""}},
        )
        raise ReplenishmentConflict(
            "Inventory record no longer exists for this recommendation"
        )

    inventory = db.inventory.find_one(
        {"store_id": recommendation["store_id"], "product_id": recommendation["product_id"]},
        {"_id": 0},
    )
    if inventory:
        queue_business_event(
            EventTopics.INVENTORY_UPDATED,
            "inventory.updated",
            {
                "product_id": inventory["product_id"],
                "store_id": inventory["store_id"],
                "recommendation_id": recommendation_id,
                "movement_id": None,
                "on_hand": inventory.get("on_hand", 0),
                "reserved": inventory.get("reserved", 0),
                "incoming": inventory.get("incoming", 0),
                "available": inventory.get("on_hand", 0) - inventory.get("reserved", 0),
            },
            f"inventory-updated-replenishment-{recommendation_id}",
        )
    return {"recommendation_id": recommendation_id, "status": "APPROVED"}
