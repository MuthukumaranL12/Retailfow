import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError

from app.db import db, redis_client
from app.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])
CACHE_SECONDS = 60


def _period_filter(start: datetime | None, end: datetime | None) -> dict:
    bounds = {}
    if start:
        bounds["$gte"] = start
    if end:
        bounds["$lte"] = end
    return {"created_at": bounds} if bounds else {}


def _cached_summary(cache_key: str):
    try:
        value = redis_client.get(cache_key)
    except RedisError:
        logger.warning("Analytics cache read failed; calculating from MongoDB", exc_info=True)
        return None
    return json.loads(value) if value else None


def _save_summary(cache_key: str, value: dict) -> None:
    try:
        redis_client.setex(cache_key, CACHE_SECONDS, json.dumps(value))
    except RedisError:
        logger.warning("Analytics cache write failed", exc_info=True)


@router.get("/dashboard")
async def dashboard_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    store_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    if role == "CUSTOMER" or role not in {
        "ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "STORE_MANAGER", "ANALYST"
    }:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if role == "STORE_MANAGER":
        if store_id and store_id != current_user.get("store_id"):
            raise HTTPException(status_code=403, detail="Not authorized for this store")
        if warehouse_id:
            raise HTTPException(status_code=403, detail="Not authorized for this warehouse")
        store_id = current_user.get("store_id")
    normalized_start = start.astimezone(timezone.utc) if start and start.tzinfo else start
    normalized_end = end.astimezone(timezone.utc) if end and end.tzinfo else end
    cache_key = "analytics:dashboard:" + hashlib.sha256(
        json.dumps(
            {
                "start": normalized_start.isoformat() if normalized_start else None,
                "end": normalized_end.isoformat() if normalized_end else None,
                "store": store_id,
                "warehouse": warehouse_id,
                "product": product_id,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cached = _cached_summary(cache_key)
    if cached is not None:
        return cached

    period = _period_filter(normalized_start, normalized_end)
    order_filter = {**period}
    if store_id:
        order_filter["fulfillment_location"] = store_id
    if warehouse_id:
        order_filter["fulfillment_location"] = warehouse_id
    if product_id:
        order_filter["items.product_id"] = product_id
    total_orders = db.orders.count_documents(order_filter)
    fulfilled_orders = db.orders.count_documents({**order_filter, "status": {"$in": ["FULFILLED", "fulfilled"]}})
    delayed_orders = db.orders.count_documents({**order_filter, "status": {"$in": ["DELAYED", "delayed"]}})

    delivery_filter = _period_filter(normalized_start, normalized_end)
    if store_id:
        delivery_filter["fulfillment_location"] = store_id
    if warehouse_id:
        delivery_filter["fulfillment_location"] = warehouse_id
    delayed_deliveries = db.deliveries.count_documents(
        {**delivery_filter, "status": {"$in": ["DELAYED", "delayed"]}}
    )
    completed_deliveries = db.deliveries.count_documents(
        {**delivery_filter, "status": {"$in": ["COMPLETED", "completed"]}}
    )

    inventory_filter = {}
    if store_id:
        inventory_filter["store_id"] = store_id
    if warehouse_id:
        inventory_filter["warehouse_id"] = warehouse_id
    if product_id:
        inventory_filter["product_id"] = product_id
    inventory_total = db.inventory.count_documents(inventory_filter)
    low_stock = db.inventory.count_documents(
        {
            **inventory_filter,
            "$expr": {
                "$lte": [
                    {"$subtract": ["$on_hand", "$reserved"]},
                    {"$ifNull": ["$reorder_point", 0]},
                ]
            },
        }
    )
    stockouts = db.inventory.count_documents(
        {**inventory_filter, "$expr": {"$lte": [{"$subtract": ["$on_hand", "$reserved"]}, 0]}}
    )
    total_vehicles = db.vehicles.count_documents({})
    active_vehicles = db.vehicles.count_documents({"status": {"$in": ["ASSIGNED", "IN_TRANSIT", "DELAYED"]}})
    duration_rows = list(
        db.deliveries.aggregate(
            [
                {
                    "$match": {
                        **delivery_filter,
                        "started_at": {"$exists": True},
                        "completed_at": {"$exists": True},
                        "status": {"$in": ["COMPLETED", "completed"]},
                    }
                },
                {
                    "$project": {
                        "duration_minutes": {
                            "$divide": [{"$subtract": ["$completed_at", "$started_at"]}, 60000]
                        }
                    }
                },
                {"$group": {"_id": None, "average": {"$avg": "$duration_minutes"}}},
            ]
        )
    )
    average_delivery = round(float(duration_rows[0]["average"]), 1) if duration_rows else 0

    summary = {
        "summary": {
            "total_orders": total_orders,
            "fulfilled_orders": fulfilled_orders,
            "delayed_orders": delayed_orders,
            "fulfillment_rate": round(fulfilled_orders / total_orders * 100, 2) if total_orders else 0,
            "average_delivery_time_minutes": average_delivery,
            "inventory_turnover": round(
                db.inventory_movements.count_documents({"type": "FULFILLMENT"}) / inventory_total, 2
            )
            if inventory_total
            else 0,
            "stockout_rate": round(stockouts / inventory_total * 100, 2) if inventory_total else 0,
            "low_stock_items": low_stock,
            "completed_deliveries": completed_deliveries,
            "delayed_deliveries": delayed_deliveries,
            "vehicle_utilization": round(active_vehicles / total_vehicles * 100, 2) if total_vehicles else 0,
            "warehouse_utilization": None,
            "business_events_processed_today": db.kafka_event_facts.count_documents(
                {"day": datetime.now(timezone.utc).date().isoformat()}
            ),
        },
        "filters": {
            "start": normalized_start.isoformat() if normalized_start else None,
            "end": normalized_end.isoformat() if normalized_end else None,
            "store_id": store_id,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
        },
    }
    _save_summary(cache_key, summary)
    return summary
