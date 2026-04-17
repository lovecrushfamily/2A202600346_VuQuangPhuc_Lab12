from fastapi import HTTPException
from app.config import settings
from app.store import store
import logging

logger = logging.getLogger(__name__)

def check_rate_limit(user_id: str):
    """
    Kiểm tra rate limit sử dụng Sliding Window với Redis hoặc in-memory fallback.
    """
    key = f"rate_limit:{user_id}"
    window_seconds = 60
    request_count = store.count_recent_requests(key, window_seconds)

    if request_count >= settings.rate_limit_per_minute:
        logger.warning(f"Rate limit hit for user {user_id}")
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Limit is {settings.rate_limit_per_minute} per minute.",
            headers={"Retry-After": "60"}
        )

    store.add_request(key, ttl_seconds=window_seconds * 2)
