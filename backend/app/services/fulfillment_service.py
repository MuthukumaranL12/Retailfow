from __future__ import annotations

from typing import Any

from app.db import db
from app.services.operations_service import haversine_km


class NoFulfillmentCandidate(Exception):
    pass


def _distance(location: dict, address: dict) -> float:
    if address.get("lat") is not None and address.get("lng") is not None:
        return haversine_km(location, address)
    if address.get("city") and location.get("city", "").casefold() == address["city"].casefold():
        return 0.0
    return 150.0


def rank_fulfillment_locations(items: list[dict], address: dict) -> list[dict[str, Any]]:
    requirements: dict[str, int] = {}
    for item in items:
        requirements[item["product_id"]] = requirements.get(item["product_id"], 0) + item["quantity"]
    product_docs = {
        product["product_id"]: product
        for product in db.products.find({"product_id": {"$in": list(requirements)}})
    }
    if len(product_docs) != len(requirements):
        raise NoFulfillmentCandidate("One or more products do not exist")

    locations = list(db.stores.find({}))
    vehicles = list(db.vehicles.find({"status": "AVAILABLE"}))
    candidates = []
    for location in locations:
        inventory_docs = {
            row["product_id"]: row
            for row in db.inventory.find(
                {"store_id": location["store_id"], "product_id": {"$in": list(requirements)}}
            )
        }
        if len(inventory_docs) != len(requirements):
            continue
        if any(
            row.get("on_hand", 0) - row.get("reserved", 0) - row.get("safety_stock", 0) < requirements[product_id]
            for product_id, row in inventory_docs.items()
        ):
            continue
        cargo_weight = sum(
            float(product_docs[product_id].get("weight_kg", 0)) * quantity
            for product_id, quantity in requirements.items()
        )
        eligible_vehicles = [v for v in vehicles if float(v.get("capacity_kg", 0)) >= cargo_weight]
        if not eligible_vehicles:
            continue
        distance = _distance(location, address)
        workload = db.deliveries.count_documents(
            {"fulfillment_location": location["store_id"], "status": {"$in": ["ASSIGNED", "IN_TRANSIT", "DELAYED"]}}
        )
        capacity_fit = min(float(v["capacity_kg"]) for v in eligible_vehicles)
        stock_cover = min(
            (row.get("on_hand", 0) - row.get("reserved", 0) - requirements[product_id])
            / max(row.get("safety_stock", 1), 1)
            for product_id, row in inventory_docs.items()
        )
        distance_score = max(0.0, 40.0 - distance / 10.0)
        inventory_score = min(30.0, max(0.0, stock_cover * 5.0))
        workload_score = max(0.0, 20.0 - workload * 4.0)
        capacity_score = max(0.0, 10.0 - (capacity_fit - cargo_weight) / 100.0)
        score = round(distance_score + inventory_score + workload_score + capacity_score, 2)
        candidates.append(
            {
                "location": location,
                "score": score,
                "distance_km": round(distance, 2),
                "cargo_weight_kg": round(cargo_weight, 2),
                "vehicle_ids": [vehicle["vehicle_id"] for vehicle in eligible_vehicles],
                "reasons": [
                    "All order lines are available above safety stock",
                    f"Estimated delivery distance is {distance:.1f} km",
                    f"{workload} active deliveries are assigned to this location",
                    f"Cargo weight {cargo_weight:.1f} kg fits an available vehicle",
                ],
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["score"], reverse=True)
