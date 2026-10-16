from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from app.api.v1.router import api_router
from app.config import settings
from app.db import db, ensure_indexes, ping_db
from app.seed import seed_demo_data
from app.services.event_outbox import EventOutboxError, ensure_outbox_indexes

app = FastAPI(title="RetailFlow API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith(f"{settings.api_v1_str}/auth/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.on_event("startup")
async def startup_event() -> None:
    ensure_indexes()
    ensure_outbox_indexes()
    seed_demo_data()


@app.get("/health")
async def health_check() -> dict:
    database_ready = ping_db()
    outbox_state = "unavailable"
    pending_events = None
    if database_ready:
        try:
            pending_events = db.kafka_outbox.count_documents({"status": {"$in": ["pending", "publishing"]}})
            outbox_state = "pending" if pending_events else "clear"
        except PyMongoError:
            outbox_state = "unavailable"
    return {
        "status": "ok" if database_ready and outbox_state != "unavailable" else "degraded",
        "service": "backend",
        "database": "ready" if database_ready else "unavailable",
        "kafka_outbox": outbox_state,
        "pending_business_events": pending_events,
    }


@app.exception_handler(EventOutboxError)
async def event_outbox_error_handler(_request: Request, exc: EventOutboxError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The operation could not be queued for downstream processing. Check its current state before retrying.",
            "error": str(exc),
        },
    )


app.include_router(api_router, prefix=settings.api_v1_str)


@app.get("/")
async def root() -> dict:
    return {"message": "RetailFlow API is running", "docs": "/docs"}
