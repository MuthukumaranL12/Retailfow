from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import db
from app.security import get_current_user
from app.services.workflow_service import OrderWorkflowError, cancel_order, create_order_workflow

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class DeliveryAddress(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    city: str | None = None
    state: str | None = None
    label: str | None = None


class OrderCreateRequest(BaseModel):
    customer_id: str
    items: list[OrderItem] = Field(min_length=1)
    delivery_address: DeliveryAddress


@router.get("")
async def list_orders(
    status: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status.upper()
    if current_user.get("role") == "CUSTOMER":
        filters["customer_id"] = current_user["email"]
    elif current_user.get("role") == "STORE_MANAGER":
        filters["fulfillment_location"] = current_user.get("store_id")
    orders = list(db.orders.find(filters, {"_id": 0}).sort("created_at", -1).limit(200))
    return {"items": orders}


@router.post("", status_code=201)
async def create_order(
    payload: OrderCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    customer_id = payload.customer_id
    if current_user.get("role") == "CUSTOMER":
        customer_id = current_user["email"]
    request_data = payload.model_dump()
    request_data["customer_id"] = customer_id
    try:
        order = create_order_workflow(request_data, idempotency_key)
    except OrderWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "message": "Order created and assigned; business events are queued for Kafka delivery",
        "order": order,
    }


@router.get("/{order_id}")
async def get_order(order_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    order = db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.get("role") == "CUSTOMER" and order.get("customer_id") != current_user["email"]:
        raise HTTPException(status_code=403, detail="Not allowed to view this order")
    if current_user.get("role") == "STORE_MANAGER" and order.get("fulfillment_location") != current_user.get("store_id"):
        raise HTTPException(status_code=403, detail="Not allowed to view this order")
    return {"order": order}


@router.get("/{order_id}/fulfillment")
async def get_fulfillment_decision(order_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    order = db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.get("role") == "CUSTOMER" and order.get("customer_id") != current_user["email"]:
        raise HTTPException(status_code=403, detail="Not allowed to view this order")
    if current_user.get("role") == "STORE_MANAGER" and order.get("fulfillment_location") != current_user.get("store_id"):
        raise HTTPException(status_code=403, detail="Not allowed to view this order")
    return {"order_id": order_id, "decision": order.get("fulfillment_decision")}


@router.post("/{order_id}/cancel")
async def cancel_order_endpoint(order_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    order = db.orders.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    role = current_user.get("role")
    if role == "CUSTOMER" and order.get("customer_id") != current_user["email"]:
        raise HTTPException(status_code=403, detail="Not allowed to cancel this order")
    if role == "STORE_MANAGER" and order.get("fulfillment_location") != current_user.get("store_id"):
        raise HTTPException(status_code=403, detail="Not allowed to cancel this order")
    if role not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "STORE_MANAGER", "CUSTOMER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        cancelled = cancel_order(order_id)
    except OrderWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"order": cancelled}
