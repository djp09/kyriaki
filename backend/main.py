from dotenv import load_dotenv
load_dotenv()

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config import get_settings
from logging_config import setup_logging, get_logger
from middleware import RequestLoggingMiddleware
from models import PatientProfile, MatchRequest, MatchResponse
from matching_engine import match_trials
from trials_client import get_trial

settings = get_settings()
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
logger = get_logger("kyriaki.main")

app = FastAPI(title="Kyriaki", description="Clinical trial matching engine for cancer patients")

# Request logging middleware (added first so it wraps everything)
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(status_code: int, message: str, detail: Optional[str] = None) -> JSONResponse:
    body: dict = {"error": True, "message": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    errors = exc.errors()
    fields = [e.get("loc", ["unknown"])[-1] for e in errors[:3]]
    return _error_response(
        422,
        f"Invalid input. Please check these fields: {', '.join(str(f) for f in fields)}",
        detail=str(errors),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_type=type(exc).__name__, error=str(exc), exc_info=True)
    return _error_response(
        500,
        "Something went wrong on our end. Please try again in a moment.",
        detail=f"{type(exc).__name__}: {exc}",
    )


@app.get("/api/health")
async def health():
    from database import check_db_health
    db_ok = await check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
    }


@app.post("/api/intake")
async def intake(patient: PatientProfile):
    return {"status": "accepted", "patient": patient}


@app.post("/api/match", response_model=MatchResponse)
async def match(request: MatchRequest):
    try:
        result = await asyncio.wait_for(
            match_trials(request.patient, max_results=request.max_results),
            timeout=settings.match_timeout,
        )
        return MatchResponse(**result)
    except asyncio.TimeoutError:
        return _error_response(
            504,
            "The matching process took too long. Please try again with fewer results or a more specific cancer type.",
        )
    except Exception as e:
        logger.error("match.pipeline_error", exc_type=type(e).__name__, error=str(e), exc_info=True)
        return _error_response(
            500,
            "We encountered an error while matching trials. Please try again.",
            detail=f"{type(e).__name__}: {e}",
        )


@app.get("/api/trials/{nct_id}")
async def trial_detail(nct_id: str):
    trial = await get_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial
