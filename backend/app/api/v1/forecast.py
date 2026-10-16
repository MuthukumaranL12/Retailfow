from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.db import db
from app.security import require_roles
from app.services.forecast_service import build_forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])
FORECAST_ROLES = ("ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "WAREHOUSE_MANAGER", "ANALYST")


def calculate_and_save_forecast(product_id: str, store_id: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {"product_id": product_id}
    if store_id:
        query["store_id"] = store_id
    sales = list(db.sales.find(query, {"_id": 0}).sort("date", 1).limit(365))
    daily: dict[str, float] = {}
    for sale in sales:
        date_value = sale["date"]
        day = date_value.date().isoformat() if isinstance(date_value, datetime) else str(date_value)[:10]
        daily[day] = daily.get(day, 0.0) + float(sale.get("quantity", 0))

    if sales:
        end_date = datetime.now(timezone.utc).date()
        start_date = max(end_date - timedelta(days=29), min(datetime.fromisoformat(day).date() for day in daily))
        history = [daily.get((start_date + timedelta(days=index)).isoformat(), 0.0) for index in range((end_date - start_date).days)]
    else:
        history = []

    forecast = build_forecast(product_id, store_id, history)
    forecast["generated_at"] = datetime.now(timezone.utc)
    db.forecasts.update_one(
        {"product_id": product_id, "store_id": store_id},
        {"$set": forecast},
        upsert=True,
    )
    return forecast


@router.get("/risks")
async def stockout_risks(
    store_id: str | None = None,
    product_id: str | None = None,
    current_user: dict = Depends(require_roles(*FORECAST_ROLES)),
):
    if current_user.get("role") == "STORE_MANAGER":
        own_store = current_user.get("store_id")
        if store_id and store_id != own_store:
            raise HTTPException(status_code=403, detail="Not authorized for this store")
        store_id = own_store
    filters: dict[str, Any] = {}
    if store_id:
        filters["store_id"] = store_id
    if product_id:
        filters["product_id"] = product_id
    inventory_rows = list(db.inventory.find(filters, {"_id": 0}).limit(5000))
    results = []
    today = datetime.now(timezone.utc).date()
    for inventory in inventory_rows:
        forecast = calculate_and_save_forecast(inventory["product_id"], inventory["store_id"])
        available = max(0, inventory.get("on_hand", 0) - inventory.get("reserved", 0))
        daily_demand = forecast["forecast_daily"]
        lead_time = int(inventory.get("lead_time_days", 4))
        protected_stock = available + inventory.get("incoming", 0) - inventory.get("safety_stock", 0)
        days_to_stockout = max(0.0, protected_stock / daily_demand) if daily_demand > 0 else None
        if daily_demand == 0:
            risk = "LOW"
            stockout_date = None
        else:
            stockout_date = (today + timedelta(days=int(days_to_stockout))).isoformat()
            if days_to_stockout <= lead_time:
                risk = "CRITICAL"
            elif days_to_stockout <= lead_time + 3:
                risk = "HIGH"
            elif days_to_stockout <= lead_time + 7:
                risk = "MEDIUM"
            else:
                risk = "LOW"
        results.append(
            {
                "store_id": inventory["store_id"],
                "product_id": inventory["product_id"],
                "available": available,
                "incoming": inventory.get("incoming", 0),
                "safety_stock": inventory.get("safety_stock", 0),
                "lead_time_days": lead_time,
                "forecast_daily": daily_demand,
                "days_to_stockout": round(days_to_stockout, 1) if days_to_stockout is not None else None,
                "estimated_stockout_date": stockout_date,
                "risk": risk,
            }
        )
    priority = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return {"items": sorted(results, key=lambda item: priority[item["risk"]])}


@router.get("/{product_id}")
async def product_forecast(
    product_id: str,
    store_id: str | None = None,
    current_user: dict = Depends(require_roles(*FORECAST_ROLES)),
):
    if current_user.get("role") == "STORE_MANAGER":
        own_store = current_user.get("store_id")
        if store_id and store_id != own_store:
            raise HTTPException(status_code=403, detail="Not authorized for this store")
        store_id = own_store
    if not db.products.find_one({"product_id": product_id}, {"_id": 0}):
        raise HTTPException(status_code=404, detail="Product not found")
    return {"forecast": calculate_and_save_forecast(product_id, store_id)}
