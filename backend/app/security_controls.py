import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.db import db

logger = logging.getLogger(__name__)


def rate_limit(max_requests: int, window_seconds: int):
    if max_requests < 1 or window_seconds < 1:
        raise ValueError("Rate-limit values must be positive")

    async def enforce(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        bucket = int(time.time()) // window_seconds
        scope = f"{client_host}:{request.method}:{request.url.path}:{bucket}"
        key = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp((bucket + 1) * window_seconds, timezone.utc) + timedelta(seconds=5)
        try:
            try:
                counter = db.rate_limits.find_one_and_update(
                    {"_id": key},
                    {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires_at}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                counter = db.rate_limits.find_one_and_update(
                    {"_id": key},
                    {"$inc": {"count": 1}},
                    return_document=ReturnDocument.AFTER,
                )
        except PyMongoError as exc:
            logger.exception("Unable to enforce request rate limit")
            raise HTTPException(
                status_code=503,
                detail="Request protection is temporarily unavailable; retry shortly",
            ) from exc
        if counter and counter["count"] > max_requests:
            retry_after = max(1, int((expires_at - now).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail="Too many requests; retry after the current rate-limit window",
                headers={"Retry-After": str(retry_after)},
            )

    return enforce
