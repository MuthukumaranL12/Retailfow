from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import db
from app.security import require_roles
from app.services.operations_service import optimize_route

router = APIRouter(prefix="/routes", tags=["routes"])


class RouteOptimizeRequest(BaseModel):
    route_id: str
    starting_location: dict
    stops: list[dict] = Field(min_length=1)
    vehicle_capacity_kg: float = Field(gt=0)
    cargo_weight_kg: float = Field(default=0, ge=0)


@router.get("")
async def list_routes(
    _=Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "DELIVERY_MANAGER", "ANALYST")),
):
    return {"items": list(db.routes.find({}, {"_id": 0}).sort("route_id", -1).limit(200))}


@router.post("/optimize")
async def optimize_route_endpoint(
    payload: RouteOptimizeRequest,
    _=Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "DELIVERY_MANAGER")),
):
    try:
        route = optimize_route(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.routes.replace_one({"route_id": route["route_id"]}, route, upsert=True)
    return route


@router.get("/{route_id}")
async def get_route(
    route_id: str,
    _=Depends(require_roles("ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "DELIVERY_MANAGER", "ANALYST")),
):
    route = db.routes.find_one({"route_id": route_id}, {"_id": 0})
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route
