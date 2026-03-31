from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    result = await match_trials(request.patient, max_results=request.max_results)
    return MatchResponse(**result)


@app.get("/api/trials/{nct_id}")
async def trial_detail(nct_id: str):
    """Get full details for a specific trial."""
    trial = await get_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial
