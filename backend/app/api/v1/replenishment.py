from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import db
from app.security import get_current_user
from app.services.forecast_service import build_replenishment_recommendation
from app.api.v1.forecast import calculate_and_save_forecast
from app.services.replenishment_service import (
    ReplenishmentConflict,
    ReplenishmentForbidden,
    ReplenishmentNotFound,
    approve_recommendation as approve_recommendation_service,
)

router = APIRouter(prefix="/replenishment", tags=["replenishment"])


def _authorized_store(current_user: dict[str, Any], store_id: str) -> None:
    role = current_user.get("role")
    if role not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "STORE_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if role == "STORE_MANAGER" and current_user.get("store_id") != store_id:
        raise HTTPException(status_code=403, detail="Not authorized for this store")


@router.get("")
async def list_recommendations(
    store_id: str | None = None,
    status: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    inventory_query: dict[str, Any] = {}
    if store_id:
        inventory_query["store_id"] = store_id
    if current_user.get("role") == "STORE_MANAGER":
        inventory_query["store_id"] = current_user.get("store_id")
    recommendations = []
    for row in db.inventory.find(inventory_query, {"_id": 0}).limit(2000):
        forecast = calculate_and_save_forecast(row["product_id"], row["store_id"])
        quantity = build_replenishment_recommendation(
            available=max(0, row.get("on_hand", 0) - row.get("reserved", 0)),
            incoming=row.get("incoming", 0),
            safety_stock=row.get("safety_stock", 0),
            forecast_7d=forecast["forecast_7d"],
            reorder_point=row.get("reorder_point", 0),
            lead_time_days=row.get("lead_time_days", 4),
        )
        if quantity <= 0:
            continue
        recommendation_id = f"RR-{row['store_id']}-{row['product_id']}"
        now = datetime.now(timezone.utc)
        db.replenishment_recommendations.update_one(
            {"recommendation_id": recommendation_id},
            {
                "$set": {
                    "store_id": row["store_id"],
                    "product_id": row["product_id"],
                    "recommended_qty": quantity,
                    "forecast_7d": forecast["forecast_7d"],
                    "current_available": max(0, row.get("on_hand", 0) - row.get("reserved", 0)),
                    "incoming": row.get("incoming", 0),
                    "safety_stock": row.get("safety_stock", 0),
                    "updated_at": now,
                },
                "$setOnInsert": {"status": "PENDING", "created_at": now},
            },
            upsert=True,
        )
    query: dict[str, Any] = {}
    if store_id:
        query["store_id"] = store_id
    if current_user.get("role") == "STORE_MANAGER":
        query["store_id"] = current_user.get("store_id")
    if status:
        query["status"] = status.upper()
    recommendations = list(
        db.replenishment_recommendations.find(query, {"_id": 0}).sort("updated_at", -1).limit(500)
    )
    return {"items": recommendations}


@router.post("/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    try:
        result = approve_recommendation_service(recommendation_id, current_user)
    except ReplenishmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReplenishmentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReplenishmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Replenishment approved", **result}


@router.post("/{recommendation_id}/reject")
async def reject_recommendation(
    recommendation_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    recommendation = db.replenishment_recommendations.find_one({"recommendation_id": recommendation_id})
    if not recommendation:
        raise HTTPException(status_code=404, detail="Replenishment recommendation not found")
    _authorized_store(current_user, recommendation["store_id"])
    result = db.replenishment_recommendations.update_one(
        {"recommendation_id": recommendation_id, "status": "PENDING"},
        {
            "$set": {
                "status": "REJECTED",
                "rejected_by": current_user["email"],
                "rejected_at": datetime.now(timezone.utc),
            }
        },
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=409, detail="Recommendation is no longer pending")
    return {"message": "Replenishment rejected", "recommendation_id": recommendation_id}


class ModifyRecommendationRequest(BaseModel):
    quantity: int = Field(gt=0)


@router.post("/{recommendation_id}/modify")
async def modify_recommendation(
    recommendation_id: str,
    payload: ModifyRecommendationRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    recommendation = db.replenishment_recommendations.find_one({"recommendation_id": recommendation_id})
    if not recommendation:
        raise HTTPException(status_code=404, detail="Replenishment recommendation not found")
    _authorized_store(current_user, recommendation["store_id"])
    result = db.replenishment_recommendations.update_one(
        {"recommendation_id": recommendation_id, "status": "PENDING"},
        {"$set": {"recommended_qty": payload.quantity, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=409, detail="Only pending recommendations can be modified")
    return {"message": "Replenishment quantity updated", "recommendation_id": recommendation_id, "quantity": payload.quantity}
