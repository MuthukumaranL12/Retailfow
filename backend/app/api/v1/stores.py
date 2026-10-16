from typing import Any

from fastapi import APIRouter, Depends

from app.db import db
from app.security import require_roles

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("")
async def list_stores(
    current_user: dict[str, Any] = Depends(
        require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "STORE_MANAGER", "ANALYST")
    ),
):
    query = {"store_id": current_user.get("store_id")} if current_user.get("role") == "STORE_MANAGER" else {}
    stores = list(db.stores.find(query, {"_id": 0}).limit(1000))
    for store in stores:
        inventory = list(db.inventory.find({"store_id": store["store_id"]}, {"_id": 0}))
        store["product_count"] = len(inventory)
        store["low_stock_count"] = sum(
            row.get("on_hand", 0) - row.get("reserved", 0) <= row.get("reorder_point", 0)
            for row in inventory
        )
    return {"items": stores}
