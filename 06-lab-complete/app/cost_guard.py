import time
import logging
from fastapi import HTTPException
from app.config import settings
from app.store import store

logger = logging.getLogger(__name__)

def check_and_record_cost(user_id: str, input_tokens: int, output_tokens: int):
    """
    Kiểm tra và ghi nhận chi phí sử dụng.
    """
    cost = (input_tokens / 1_000_000) * 0.15 + (output_tokens / 1_000_000) * 0.60
    
    today = time.strftime("%Y-%m-%d")
    key = f"cost:{user_id}:{today}"
    
    current_cost = store.get_float(key)
    
    if current_cost + cost > settings.daily_budget_usd:
        logger.error(f"Budget exceeded for user {user_id}: ${current_cost}")
        raise HTTPException(
            status_code=503,
            detail="Daily budget exceeded. Please try again tomorrow."
        )
    
    store.incrbyfloat(key, cost, ttl_seconds=86400 * 2)
