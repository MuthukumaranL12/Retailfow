from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


def estimate_eta(
    distance_km: float,
    remaining_stops: int,
    historical_minutes: float,
    time_of_day: int,
    vehicle_utilization: float,
    traffic_multiplier: float = 1.0,
    weather_multiplier: float = 1.0,
) -> float:
    base_travel = distance_km * 7.6
    stop_penalty = remaining_stops * 18
    peak_multiplier = 1.25 if 8 <= time_of_day <= 10 or 16 <= time_of_day <= 19 else 1.0
    utilization_penalty = 1.0 + max(0.0, vehicle_utilization - 0.7) * 0.8
    total = (base_travel + stop_penalty + historical_minutes) * peak_multiplier * traffic_multiplier * weather_multiplier * utilization_penalty
    return round(total, 2)


def haversine_km(origin: dict, destination: dict) -> float:
    lat1, lon1 = radians(float(origin["lat"])), radians(float(origin["lng"]))
    lat2, lon2 = radians(float(destination["lat"])), radians(float(destination["lng"]))
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(value))


def _path_distance(start: dict, stops: list[dict]) -> float:
    points = [start, *stops]
    return sum(haversine_km(left, right) for left, right in zip(points, points[1:]))


def optimize_route(
    route_id: str,
    stops: list[dict],
    starting_location: dict,
    vehicle_capacity_kg: float,
    cargo_weight_kg: float = 0,
    average_speed_kmh: float = 32,
) -> dict:
    if cargo_weight_kg > vehicle_capacity_kg:
        raise ValueError("Cargo exceeds vehicle capacity")
    if average_speed_kmh <= 0:
        raise ValueError("Average speed must be positive")
    if any(not {"lat", "lng"}.issubset(stop) for stop in stops):
        raise ValueError("Every stop must include latitude and longitude")
    if not {"lat", "lng"}.issubset(starting_location):
        raise ValueError("Starting location must include latitude and longitude")

    remaining = list(stops)
    baseline: list[dict] = []
    cursor = starting_location
    while remaining:
        nearest = min(remaining, key=lambda stop: haversine_km(cursor, stop))
        baseline.append(nearest)
        remaining.remove(nearest)
        cursor = nearest

    baseline_distance = _path_distance(starting_location, baseline)
    optimized = baseline[:]
    improved = True
    while improved:
        improved = False
        for first in range(len(optimized) - 1):
            for last in range(first + 1, len(optimized)):
                candidate = optimized[:first] + list(reversed(optimized[first : last + 1])) + optimized[last + 1 :]
                if _path_distance(starting_location, candidate) + 1e-9 < _path_distance(starting_location, optimized):
                    optimized = candidate
                    improved = True

    optimized_distance = _path_distance(starting_location, optimized)
    elapsed_km = 0.0
    stop_details = []
    for stop in optimized:
        elapsed_km += haversine_km(starting_location if not stop_details else optimized[len(stop_details) - 1], stop)
        stop_details.append(
            {
                **stop,
                "distance_from_previous_km": round(
                    haversine_km(starting_location if len(stop_details) == 0 else optimized[len(stop_details) - 1], stop), 2
                ),
                "eta_minutes": round(elapsed_km / average_speed_kmh * 60, 1),
                "status": "pending",
            }
        )
    return {
        "route_id": route_id,
        "starting_location": starting_location,
        "baseline_distance_km": round(baseline_distance, 2),
        "optimized_distance_km": round(optimized_distance, 2),
        "improvement_percent": round(
            ((baseline_distance - optimized_distance) / baseline_distance * 100) if baseline_distance else 0, 2
        ),
        "ordered_stops": [stop.get("stop_id") for stop in optimized],
        "stops": stop_details,
        "estimated_minutes": round(optimized_distance / average_speed_kmh * 60, 1),
        "vehicle_capacity_kg": vehicle_capacity_kg,
        "cargo_weight_kg": cargo_weight_kg,
    }


def build_replenishment_recommendation(
    available: int,
    incoming: int,
    safety_stock: int,
    forecast_7d: float,
    reorder_point: int,
    lead_time_days: int = 4,
) -> int:
    projected_need = int(forecast_7d) + safety_stock + max(0, reorder_point - safety_stock)
    projected_inventory = available + incoming
    delta = projected_need - projected_inventory
    return max(0, delta + (lead_time_days * 2))
