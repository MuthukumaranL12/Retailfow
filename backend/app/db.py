from pymongo import MongoClient
from redis import Redis

from app.config import settings

mongo_client = MongoClient(settings.mongodb_uri)
db = mongo_client[settings.mongo_db_name]
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


def ensure_indexes() -> None:
    db.orders.create_index("order_id", unique=True)
    db.orders.create_index("idempotency_key", unique=True, sparse=True)
    db.inventory.create_index([("store_id", 1), ("product_id", 1)], unique=True)
    db.deliveries.create_index("delivery_id", unique=True)
    db.routes.create_index("route_id", unique=True)
    db.vehicles.create_index("vehicle_id", unique=True)
    db.forecasts.create_index([("product_id", 1), ("store_id", 1)], unique=True)
    db.sales.create_index([("product_id", 1), ("store_id", 1), ("date", 1)])
    db.replenishment_recommendations.create_index("recommendation_id", unique=True)
    db.conversations.create_index("conversation_id", unique=True)
    db.websocket_tickets.create_index("ticket_hash", unique=True)
    db.websocket_tickets.create_index("expires_at", expireAfterSeconds=0)
    db.rate_limits.create_index("expires_at", expireAfterSeconds=0)


def ping_db() -> bool:
    try:
        mongo_client.admin.command("ping")
        return True
    except Exception:
        return False
