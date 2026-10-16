import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.db import db
from app.services.operations_service import haversine_km
from app.security import get_current_user
from app.services.event_outbox import queue_business_event
from app.services.kafka_service import EventTopics
from app.services.workflow_service import OrderWorkflowError, complete_delivery

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


class DeliveryConnections:
    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, delivery_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(delivery_id, []).append(websocket)

    def disconnect(self, delivery_id: str, websocket: WebSocket) -> None:
        self.connections[delivery_id] = [connection for connection in self.connections.get(delivery_id, []) if connection != websocket]
        if not self.connections[delivery_id]:
            self.connections.pop(delivery_id, None)

    async def publish(self, delivery_id: str, event: dict[str, Any]) -> None:
        failed = []
        for connection in self.connections.get(delivery_id, []):
            try:
                await connection.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                failed.append(connection)
        for connection in failed:
            self.disconnect(delivery_id, connection)


delivery_connections = DeliveryConnections()


class DeliveryDelayRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("")
async def list_deliveries(status: str | None = None, current_user: dict = Depends(get_current_user)):
    query = {"status": status.upper()} if status else {}
    role = current_user.get("role")
    if role == "CUSTOMER":
        order_ids = [
            order["order_id"]
            for order in db.orders.find({"customer_id": current_user["email"]}, {"_id": 0, "order_id": 1})
        ]
        query["order_id"] = {"$in": order_ids}
    elif role == "STORE_MANAGER":
        query["fulfillment_location"] = current_user.get("store_id")
    elif role not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "DELIVERY_MANAGER", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return {"items": list(db.deliveries.find(query, {"_id": 0}).sort("created_at", -1).limit(200))}


@router.get("/{delivery_id}")
async def get_delivery(delivery_id: str, current_user: dict = Depends(get_current_user)):
    delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    _authorize_delivery_read(delivery, current_user)
    route = db.routes.find_one({"route_id": delivery["route_id"]}, {"_id": 0})
    return {"delivery": delivery, "route": route}


@router.post("/{delivery_id}/live-ticket")
async def create_live_ticket(delivery_id: str, current_user: dict = Depends(get_current_user)):
    delivery = db.deliveries.find_one({"delivery_id": delivery_id})
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    _authorize_delivery_read(delivery, current_user)
    ticket = secrets.token_urlsafe(32)
    db.websocket_tickets.insert_one(
        {
            "ticket_hash": hashlib.sha256(ticket.encode()).hexdigest(),
            "delivery_id": delivery_id,
            "user": {
                "email": current_user["email"],
                "role": current_user["role"],
                "store_id": current_user.get("store_id"),
            },
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        }
    )
    return {"ticket": ticket, "expires_in_seconds": 60}


@router.post("/{delivery_id}/start")
async def start_delivery(delivery_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "DELIVERY_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    now = datetime.now(timezone.utc)
    result = db.deliveries.update_one(
        {"delivery_id": delivery_id, "status": "ASSIGNED"},
        {"$set": {"status": "IN_TRANSIT", "started_at": now, "updated_at": now}},
    )
    if result.matched_count != 1:
        delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        if delivery["status"] != "IN_TRANSIT":
            raise HTTPException(status_code=409, detail=f"Cannot start delivery in {delivery['status']} state")
    delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
    db.vehicles.update_one(
        {"vehicle_id": delivery["vehicle_id"], "status": "ASSIGNED"},
        {"$set": {"status": "IN_TRANSIT", "updated_at": now}},
    )
    if delivery.get("driver_id"):
        db.drivers.update_one(
            {"driver_id": delivery["driver_id"], "status": "ASSIGNED"},
            {"$set": {"status": "IN_TRANSIT", "updated_at": now}},
        )
    queue_business_event(
        EventTopics.DELIVERY_STARTED,
        "delivery.started",
        {
            "delivery_id": delivery_id,
            "order_id": delivery["order_id"],
            "vehicle_id": delivery["vehicle_id"],
            "started_at": delivery.get("started_at", now).isoformat(),
        },
        f"delivery-started-{delivery_id}",
    )
    return {"delivery": delivery}


@router.post("/{delivery_id}/advance")
async def advance_delivery(delivery_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "DELIVERY_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    delivery = db.deliveries.find_one({"delivery_id": delivery_id})
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if delivery["status"] not in {"IN_TRANSIT", "DELAYED"}:
        raise HTTPException(status_code=409, detail="Delivery must be started before tracking")
    route = db.routes.find_one({"route_id": delivery["route_id"]})
    if not route:
        raise HTTPException(status_code=409, detail="Delivery route is missing")

    progress = min(1.0, round(float(delivery.get("progress", 0)) + 0.2, 4))
    origin = route["starting_location"]
    points = [origin, *route["stops"]]
    segments = [haversine_km(left, right) for left, right in zip(points, points[1:])]
    total_distance = sum(segments)
    distance_travelled = total_distance * progress
    cumulative_distance = 0.0
    current_location = origin
    updated_stops = []
    for index, stop in enumerate(route["stops"]):
        segment_distance = segments[index]
        if distance_travelled >= cumulative_distance + segment_distance or progress >= 1:
            current_location = {"name": stop["name"], "lat": stop["lat"], "lng": stop["lng"]}
            updated_stops.append({**stop, "status": "COMPLETED"})
        elif distance_travelled > cumulative_distance:
            ratio = (distance_travelled - cumulative_distance) / segment_distance if segment_distance else 1
            left, right = points[index], points[index + 1]
            current_location = {
                "name": "In transit",
                "lat": left["lat"] + (right["lat"] - left["lat"]) * ratio,
                "lng": left["lng"] + (right["lng"] - left["lng"]) * ratio,
            }
            updated_stops.append({**stop, "status": "IN_PROGRESS"})
        else:
            updated_stops.append({**stop, "status": "PENDING"})
        cumulative_distance += segment_distance

    remaining_km = max(0.0, total_distance * (1 - progress))
    now = datetime.now(timezone.utc)
    update = {
        "progress": progress,
        "current_location": current_location,
        "eta_minutes": round(remaining_km / 32 * 60, 1),
        "updated_at": now,
    }
    updated = db.deliveries.update_one(
        {
            "delivery_id": delivery_id,
            "status": delivery["status"],
            "progress": delivery.get("progress", 0),
        },
        {"$set": update},
    )
    if updated.matched_count != 1:
        raise HTTPException(status_code=409, detail="Delivery progress changed; retry the tracking update")
    db.routes.update_one({"route_id": route["route_id"]}, {"$set": {"stops": updated_stops}})
    event = {
        "type": "vehicle.location.updated",
        "delivery_id": delivery_id,
        "vehicle_id": delivery["vehicle_id"],
        **{**update, "updated_at": now.isoformat()},
    }
    await delivery_connections.publish(delivery_id, event)
    queue_business_event(
        EventTopics.VEHICLE_LOCATION_UPDATED,
        "vehicle.location.updated",
        {
            "delivery_id": delivery_id,
            "order_id": delivery["order_id"],
            "vehicle_id": delivery["vehicle_id"],
            "current_location": current_location,
            "progress": progress,
            "eta_minutes": update["eta_minutes"],
            "updated_at": now.isoformat(),
        },
        f"vehicle-location-{delivery_id}-{progress:.4f}",
    )
    return {"delivery_id": delivery_id, **update, "stops": updated_stops}


@router.post("/{delivery_id}/delay")
async def mark_delivery_delayed(
    delivery_id: str,
    payload: DeliveryDelayRequest,
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "DELIVERY_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    now = datetime.now(timezone.utc)
    result = db.deliveries.update_one(
        {"delivery_id": delivery_id, "status": {"$in": ["IN_TRANSIT", "DELAYED"]}},
        {"$set": {"status": "DELAYED", "delay_reason": payload.reason.strip(), "updated_at": now}},
    )
    if result.matched_count != 1:
        delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        raise HTTPException(status_code=409, detail=f"Cannot mark delivery delayed in {delivery['status']} state")
    delivery = db.deliveries.find_one({"delivery_id": delivery_id}, {"_id": 0})
    queue_business_event(
        EventTopics.DELIVERY_DELAYED,
        "delivery.delayed",
        {
            "delivery_id": delivery_id,
            "order_id": delivery["order_id"],
            "reason": payload.reason.strip(),
            "updated_at": now.isoformat(),
        },
        f"delivery-delayed-{delivery_id}",
    )
    await delivery_connections.publish(
        delivery_id,
        {"type": "delivery.delayed", "delivery_id": delivery_id, "reason": payload.reason.strip()},
    )
    return {"delivery": delivery}


@router.post("/{delivery_id}/complete")
async def finish_delivery(delivery_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "DELIVERY_MANAGER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        delivery = complete_delivery(delivery_id)
    except OrderWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await delivery_connections.publish(
        delivery_id,
        {"type": "delivery.completed", "delivery_id": delivery_id, "status": delivery["status"]},
    )
    return {"delivery": delivery}


def _authorize_delivery_read(delivery: dict, user: dict) -> None:
    role = user.get("role")
    if role == "CUSTOMER":
        order = db.orders.find_one(
            {"order_id": delivery["order_id"], "customer_id": user.get("email")}, {"_id": 0}
        )
        if not order:
            raise HTTPException(status_code=403, detail="Not allowed to view this delivery")
    elif role == "STORE_MANAGER":
        if delivery.get("fulfillment_location") != user.get("store_id"):
            raise HTTPException(status_code=403, detail="Not allowed to view this delivery")
    elif role not in {"ADMIN", "SUPPLY_CHAIN_MANAGER", "WAREHOUSE_MANAGER", "DELIVERY_MANAGER", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.websocket("/{delivery_id}/live")
async def delivery_live_updates(websocket: WebSocket, delivery_id: str):
    ticket = websocket.query_params.get("ticket", "")
    ticket_record = db.websocket_tickets.find_one_and_delete(
        {
            "ticket_hash": hashlib.sha256(ticket.encode()).hexdigest(),
            "delivery_id": delivery_id,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        }
    ) if ticket else None
    delivery = db.deliveries.find_one({"delivery_id": delivery_id})
    if not ticket_record or not delivery:
        await websocket.close(code=1008, reason="Delivery not found")
        return
    try:
        _authorize_delivery_read(delivery, ticket_record["user"])
    except HTTPException:
        await websocket.close(code=1008, reason="Not authorized")
        return
    await delivery_connections.connect(delivery_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        delivery_connections.disconnect(delivery_id, websocket)
