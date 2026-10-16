from math import ceil, sqrt
from statistics import mean


def moving_average(values: list[float], window: int = 7) -> float:
    if not values:
        return 0.0
    return mean(values[-window:])


def exponential_smoothing(values: list[float], alpha: float = 0.5) -> float:
    if not values:
        return 0.0
    smoothed = values[0]
    for val in values[1:]:
        smoothed = alpha * val + (1 - alpha) * smoothed
    return smoothed


def build_forecast(product_id: str, store_id: str | None = None, history: list[float] | None = None) -> dict:
    history = history or []
    baseline_daily = moving_average(history, 7)
    smoothed_daily = exponential_smoothing(history)
    errors = []
    for index in range(1, len(history)):
        errors.append(history[index] - moving_average(history[:index], 7))
    mae = mean(abs(error) for error in errors) if errors else 0.0
    rmse = sqrt(mean(error * error for error in errors)) if errors else 0.0
    return {
        "product_id": product_id,
        "store_id": store_id,
        "actual_daily": [round(value, 2) for value in history],
        "forecast_daily": round(max(0.0, smoothed_daily), 2),
        "baseline_daily": round(max(0.0, baseline_daily), 2),
        "forecast_7d": round(max(0.0, smoothed_daily * 7), 2),
        "baseline_7d": round(max(0.0, baseline_daily * 7), 2),
        "forecast_30d": round(max(0.0, smoothed_daily * 30), 2),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "sample_days": len(history),
        "baseline_method": "7-day moving average",
        "enhanced_method": "exponential smoothing",
    }


def build_replenishment_recommendation(available: int, incoming: int, safety_stock: int, forecast_7d: float, reorder_point: int, lead_time_days: int = 4) -> int:
    lead_time_demand = max(0.0, forecast_7d) / 7 * max(0, lead_time_days)
    review_period_demand = max(0.0, forecast_7d)
    target_stock = max(float(reorder_point), lead_time_demand + review_period_demand + safety_stock)
    inventory_position = available + incoming
    return max(0, ceil(target_stock - inventory_position))
