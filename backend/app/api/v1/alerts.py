from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.db import db
from app.security import require_roles
from fastapi import Depends

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    severity: str | None = None,
    resolved: bool | None = None,
    current_user: dict = Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "WAREHOUSE_MANAGER", "DELIVERY_MANAGER", "ANALYST")),
):
    filters = {}
    if severity:
        filters["severity"] = severity.upper()
    if resolved is not None:
        filters["resolved"] = resolved
    if current_user.get("role") == "STORE_MANAGER":
        filters["store_id"] = current_user.get("store_id")
    alerts = list(db.alerts.find(filters, {"_id": 0}).sort("created_at", -1).limit(200))
    return {"items": alerts}


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, _=Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "WAREHOUSE_MANAGER"))):
    result = db.alerts.update_one(
        {"alert_id": alert_id}, {"$set": {"acknowledged": True, "acknowledged_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert acknowledged", "alert_id": alert_id}


@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: str, _=Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "WAREHOUSE_MANAGER"))):
    result = db.alerts.update_one(
        {"alert_id": alert_id, "resolved": {"$ne": True}},
        {"$set": {"resolved": True, "resolved_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count != 1:
        if not db.alerts.find_one({"alert_id": alert_id}):
            raise HTTPException(status_code=404, detail="Alert not found")
        raise HTTPException(status_code=409, detail="Alert is already resolved")
    return {"message": "Alert resolved", "alert_id": alert_id}
