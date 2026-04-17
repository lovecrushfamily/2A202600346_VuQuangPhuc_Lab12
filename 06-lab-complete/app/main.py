"""
Production AI Agent — Final Project Complete
Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication (Separate module)
  ✅ Rate limiting (Redis-based)
  ✅ Cost guard (Redis-based)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown
  ✅ Stateless design
"""
import os
import time
import signal
import logging
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.auth import verify_api_key
from app.rate_limiter import check_rate_limit
from app.cost_guard import check_and_record_cost

# Mock LLM
from utils.mock_llm import ask as llm_ask

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0

# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "environment": settings.environment,
    }))
    # Simulate some initialization
    _is_ready = True
    yield
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))

# ─────────────────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    global _request_count
    start = time.time()
    _request_count += 1
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 1)
    
    logger.info(json.dumps({
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": duration,
    }))
    return response

# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)

class AskResponse(BaseModel):
    question: str
    answer: str
    timestamp: str

# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": f"Welcome to {settings.app_name}", "docs": "/docs"}

@app.post("/ask", response_model=AskResponse)
async def ask_agent(
    body: AskRequest,
    user_id: str = Depends(verify_api_key)
):
    # 1. Rate limiting check
    check_rate_limit(user_id)
    
    # 2. Pre-check cost (estimation)
    input_tokens = len(body.question.split()) * 1.5
    check_and_record_cost(user_id, int(input_tokens), 0)
    
    # 3. Call LLM
    answer = llm_ask(body.question)
    
    # 4. Record output cost
    output_tokens = len(answer.split()) * 1.5
    check_and_record_cost(user_id, 0, int(output_tokens))
    
    return AskResponse(
        question=body.question,
        answer=answer,
        timestamp=datetime.now(timezone.utc).isoformat()
    )

@app.get("/health")
def health():
    return {"status": "ok", "uptime": round(time.time() - START_TIME, 1)}

@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {"status": "ready"}

# ─────────────────────────────────────────────────────────
# Signal handling for Graceful Shutdown
# ─────────────────────────────────────────────────────────
def handle_sigterm(*args):
    logger.info("Received SIGTERM, shutting down...")
    
signal.signal(signal.SIGTERM, handle_sigterm)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
