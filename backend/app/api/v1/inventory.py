from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import db
from app.security import get_current_user, require_roles
from app.services.inventory_service import (
    InsufficientInventory,
    confirm_reservation,
    release_reservation,
    reserve_inventory,
    restock_inventory,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])
INVENTORY_ROLES = ("ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "WAREHOUSE_MANAGER")


def _scope_store(current_user: dict, requested_store_id: str | None) -> str | None:
    if current_user.get("role") == "STORE_MANAGER":
        own_store = current_user.get("store_id")
        if requested_store_id and requested_store_id != own_store:
            raise HTTPException(status_code=403, detail="Not authorized for this store")
        return own_store
    return requested_store_id


class InventoryReserveRequest(BaseModel):
    product_id: str
    store_id: str
    quantity: int = Field(gt=0)
    order_id: str = "manual"


class InventoryMovementRequest(BaseModel):
    product_id: str
    store_id: str
    quantity: int = Field(gt=0)
    order_id: str = "manual"


@router.get("")
async def list_inventory(
    store_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    current_user: dict = Depends(require_roles(*INVENTORY_ROLES)),
):
    store_id = _scope_store(current_user, store_id)
    filters = {}
    if store_id:
        filters["store_id"] = store_id
    if product_id:
        filters["product_id"] = product_id
    docs = list(db.inventory.find(filters, {"_id": 0}).limit(200))
    return {"items": docs}


@router.get("/{product_id}/availability")
async def inventory_availability(
    product_id: str,
    store_id: str | None = None,
    current_user: dict = Depends(require_roles(*INVENTORY_ROLES)),
):
    store_id = _scope_store(current_user, store_id)
    filters = {"product_id": product_id}
    if store_id:
        filters["store_id"] = store_id
    docs = list(db.inventory.find(filters, {"_id": 0}).limit(100))
    results = []
    for doc in docs:
        available = doc.get("on_hand", 0) - doc.get("reserved", 0)
        results.append({"store_id": doc["store_id"], "product_id": doc["product_id"], "available": available, "on_hand": doc.get("on_hand", 0), "reserved": doc.get("reserved", 0)})
    return {"items": results}


@router.post("/reserve")
async def reserve_inventory(payload: InventoryReserveRequest, current_user: dict = Depends(require_roles(*INVENTORY_ROLES))):
    if _scope_store(current_user, payload.store_id) != payload.store_id:
        raise HTTPException(status_code=403, detail="Not authorized for this store")
    try:
        reserve_inventory(payload.product_id, payload.store_id, payload.quantity, payload.order_id)
    except InsufficientInventory as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    inventory = db.inventory.find_one({"product_id": payload.product_id, "store_id": payload.store_id}, {"_id": 0})
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    return {
        "message": "Inventory reserved",
        "available_after": inventory.get("on_hand", 0) - inventory.get("reserved", 0),
        "reserved_after": inventory.get("reserved", 0),
    }


@router.post("/release")
async def release_inventory(payload: InventoryMovementRequest, current_user: dict = Depends(require_roles(*INVENTORY_ROLES))):
    if _scope_store(current_user, payload.store_id) != payload.store_id:
        raise HTTPException(status_code=403, detail="Not authorized for this store")
    try:
        release_reservation(payload.product_id, payload.store_id, payload.quantity, payload.order_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Reservation released"}


@router.post("/confirm")
async def confirm_inventory(payload: InventoryMovementRequest, current_user: dict = Depends(require_roles(*INVENTORY_ROLES))):
    if _scope_store(current_user, payload.store_id) != payload.store_id:
        raise HTTPException(status_code=403, detail="Not authorized for this store")
    try:
        confirm_reservation(payload.product_id, payload.store_id, payload.quantity, payload.order_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Reservation confirmed and inventory deducted"}


@router.post("/restock")
async def restock(payload: InventoryMovementRequest, current_user: dict = Depends(require_roles(*INVENTORY_ROLES))):
    if _scope_store(current_user, payload.store_id) != payload.store_id:
        raise HTTPException(status_code=403, detail="Not authorized for this store")
    try:
        movement = restock_inventory(payload.product_id, payload.store_id, payload.quantity, payload.order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": "Inventory restocked", "movement": movement}


@router.get("/movements")
async def inventory_movements(
    product_id: str | None = None,
    store_id: str | None = None,
    current_user: dict = Depends(require_roles(*INVENTORY_ROLES)),
):
    store_id = _scope_store(current_user, store_id)
    query = {}
    if product_id:
        query["product_id"] = product_id
    if store_id:
        query["store_id"] = store_id
    return {"items": list(db.inventory_movements.find(query, {"_id": 0}).sort("created_at", -1).limit(200))}


@router.get("/replenishment")
async def replenishment_recommendations(
    store_id: str | None = None,
    current_user: dict = Depends(require_roles(*INVENTORY_ROLES)),
):
    store_id = _scope_store(current_user, store_id)
    docs = list(db.inventory.find({"store_id": store_id} if store_id else {}).limit(200))
    recommendations = []
    for doc in docs:
        available = doc.get("on_hand", 0) - doc.get("reserved", 0)
        forecast = db.forecasts.find_one({"product_id": doc["product_id"], "store_id": doc["store_id"]})
        forecast_7d = float(forecast.get("forecast_7d", 0)) if forecast else 0
        lead_time_days = int(doc.get("lead_time_days", 4))
        recommended = max(
            0,
            int(forecast_7d + doc.get("safety_stock", 0) + lead_time_days * (forecast_7d / 7) - available - doc.get("incoming", 0)),
        )
        if recommended > 0:
            recommendations.append({"store_id": doc["store_id"], "product_id": doc["product_id"], "current_available": available, "recommended_qty": recommended, "forecast_7d": forecast_7d})
    return {"recommendations": recommendations}
