from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.security import get_current_user
from app.services import warehouse_service
from app.services.warehouse_service import WarehouseConflict, WAREHOUSE_STATUSES

router = APIRouter(prefix="/warehouses", tags=["warehouses"])

READ_ROLES = {
    "ADMIN",
    "SUPPLY_CHAIN_MANAGER",
    "WAREHOUSE_MANAGER",
    "DELIVERY_MANAGER",
    "ANALYST",
}
WRITE_ROLES = {"ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER"}


class WarehouseCreate(BaseModel):
    warehouse_id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    capacity_units: int | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "INACTIVE", "MAINTENANCE", "CLOSED"] = "ACTIVE"


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    capacity_units: int | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "INACTIVE", "MAINTENANCE", "CLOSED"] | None = None


class WarehouseStatusUpdate(BaseModel):
    status: Literal["ACTIVE", "INACTIVE", "MAINTENANCE", "CLOSED"]


def _check_read(current_user: dict[str, Any]) -> None:
    if current_user.get("role") not in READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _check_write(current_user: dict[str, Any], warehouse_id: str | None = None) -> None:
    role = current_user.get("role")
    if role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if role == "WAREHOUSE_MANAGER" and warehouse_id:
        assigned = set(current_user.get("warehouse_ids") or [])
        if current_user.get("warehouse_id"):
            assigned.add(current_user["warehouse_id"])
        if warehouse_id not in assigned:
            raise HTTPException(status_code=403, detail="Not authorized for this warehouse")
    elif role == "WAREHOUSE_MANAGER" and not (
        current_user.get("warehouse_id") or current_user.get("warehouse_ids")
    ):
        raise HTTPException(status_code=403, detail="No warehouse is assigned to this manager")


def _manager_scope(current_user: dict[str, Any]) -> list[str] | None:
    if current_user.get("role") != "WAREHOUSE_MANAGER":
        return None
    assigned = set(current_user.get("warehouse_ids") or [])
    if current_user.get("warehouse_id"):
        assigned.add(current_user["warehouse_id"])
    return sorted(assigned)


@router.get("/compare")
async def compare_warehouse_analytics(
    warehouse_ids: list[str] = Query(min_length=2, max_length=10),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_read(current_user)
    scope = _manager_scope(current_user)
    if scope is not None and any(warehouse_id not in scope for warehouse_id in warehouse_ids):
        raise HTTPException(status_code=403, detail="Not authorized for one or more warehouses")
    items = warehouse_service.compare_warehouses(warehouse_ids)
    return {"items": items}


@router.get("")
async def list_warehouses(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_read(current_user)
    if status_filter and status_filter.upper() not in WAREHOUSE_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid warehouse status")
    warehouses = warehouse_service.list_warehouses(
        status=status_filter,
        warehouse_ids=_manager_scope(current_user),
        limit=limit,
        skip=skip,
    )
    items = []
    for warehouse in warehouses:
        summary = warehouse_service.get_warehouse_dashboard(
            warehouse["warehouse_id"], include_records=False
        )["summary"]
        items.append({**warehouse, "summary": summary})
    return {"items": items, "limit": limit, "skip": skip}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    if current_user.get("role") not in {"ADMIN", "SUPPLY_CHAIN_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        warehouse = warehouse_service.create_warehouse(payload.model_dump(exclude_none=True))
    except WarehouseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"warehouse": warehouse}


@router.get("/{warehouse_id}")
async def get_warehouse(
    warehouse_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_read(current_user)
    _check_write_scope_read(current_user, warehouse_id)
    try:
        return warehouse_service.get_warehouse_dashboard(warehouse_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{warehouse_id}/analytics")
async def warehouse_analytics(
    warehouse_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_read(current_user)
    _check_write_scope_read(current_user, warehouse_id)
    try:
        dashboard = warehouse_service.get_warehouse_dashboard(warehouse_id, include_records=False)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"warehouse_id": warehouse_id, "summary": dashboard["summary"]}


@router.get("/{warehouse_id}/decisions")
async def warehouse_fulfillment_decisions(
    warehouse_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_read(current_user)
    _check_write_scope_read(current_user, warehouse_id)
    if not warehouse_service.get_warehouse(warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"items": warehouse_service.get_warehouse_decisions(warehouse_id, limit)}


@router.patch("/{warehouse_id}")
async def update_warehouse(
    warehouse_id: str,
    payload: WarehouseUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_write(current_user, warehouse_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field must be provided")
    warehouse = warehouse_service.update_warehouse(warehouse_id, changes)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"warehouse": warehouse}


@router.patch("/{warehouse_id}/status")
async def update_warehouse_status(
    warehouse_id: str,
    payload: WarehouseStatusUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    _check_write(current_user, warehouse_id)
    warehouse = warehouse_service.update_warehouse_status(warehouse_id, payload.status)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"warehouse": warehouse}


@router.delete("/{warehouse_id}")
async def delete_warehouse(
    warehouse_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    if current_user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Only administrators can delete warehouses")
    try:
        deleted = warehouse_service.delete_warehouse(warehouse_id)
    except WarehouseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"message": "Warehouse deleted", "warehouse_id": warehouse_id}


def _check_write_scope_read(current_user: dict[str, Any], warehouse_id: str) -> None:
    if current_user.get("role") == "WAREHOUSE_MANAGER":
        _check_write(current_user, warehouse_id)
