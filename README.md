# Kyriaki

Clinical trial matching engine for cancer patients. Takes a patient's profile and returns a ranked list of clinical trials they're likely eligible for, with plain-language explanations.

## How It Works

1. Patient fills out an intake form (cancer type, stage, biomarkers, prior treatments, labs, location)
2. Backend searches ClinicalTrials.gov for recruiting trials
3. Claude analyzes each trial's eligibility criteria against the patient profile
4. Returns ranked matches with scores, explanations, and logistics

## Tech Stack

- **Backend:** Python / FastAPI
- **AI:** Claude API (eligibility reasoning)
- **Frontend:** React / Vite
- **Trial Data:** ClinicalTrials.gov API v2

## Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
python3 -m uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Environment Variables

```
ANTHROPIC_API_KEY=your-key-here
```

## License

All rights reserved.
