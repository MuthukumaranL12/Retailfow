from fastapi import APIRouter

from app.api.v1.alerts import router as alerts_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chatbot import router as chatbot_router
from app.api.v1.deliveries import router as deliveries_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.orders import router as orders_router
from app.api.v1.products import router as products_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.replenishment import router as replenishment_router
from app.api.v1.stores import router as stores_router
from app.api.v1.routes import router as routes_router
from app.api.v1.warehouses import router as warehouses_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(inventory_router)
api_router.include_router(orders_router)
api_router.include_router(products_router)
api_router.include_router(forecast_router)
api_router.include_router(replenishment_router)
api_router.include_router(stores_router)
api_router.include_router(warehouses_router)
api_router.include_router(routes_router)
api_router.include_router(deliveries_router)
api_router.include_router(analytics_router)
api_router.include_router(alerts_router)
api_router.include_router(chatbot_router)
