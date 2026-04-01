from dotenv import load_dotenv
load_dotenv()

import asyncio
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from models import PatientProfile, MatchRequest, MatchResponse
from matching_engine import match_trials
from trials_client import get_trial

app = FastAPI(title="Kyriaki", description="Clinical trial matching engine for cancer patients")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timeout for the match endpoint (seconds)
MATCH_TIMEOUT = 120


def _error_response(status_code: int, message: str, detail: Optional[str] = None) -> JSONResponse:
    """Return a structured error response with a user-friendly message."""
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
    print(f"[ERROR] Unhandled exception: {type(exc).__name__}: {exc}")
    traceback.print_exc()
    return _error_response(
        500,
        "Something went wrong on our end. Please try again in a moment.",
        detail=f"{type(exc).__name__}: {exc}",
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/intake")
async def intake(patient: PatientProfile):
    """Validate and echo back the patient profile."""
    return {"status": "accepted", "patient": patient}


@app.post("/api/match", response_model=MatchResponse)
async def match(request: MatchRequest):
    """Run the full matching pipeline."""
    try:
        result = await asyncio.wait_for(
            match_trials(request.patient, max_results=request.max_results),
            timeout=MATCH_TIMEOUT,
        )
        return MatchResponse(**result)
    except asyncio.TimeoutError:
        return _error_response(
            504,
            "The matching process took too long. Please try again with fewer results or a more specific cancer type.",
        )
    except Exception as e:
        print(f"[MATCH] Pipeline error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return _error_response(
            500,
            "We encountered an error while matching trials. Please try again.",
            detail=f"{type(e).__name__}: {e}",
        )


@app.get("/api/trials/{nct_id}")
async def trial_detail(nct_id: str):
    """Get full details for a specific trial."""
    trial = await get_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial
