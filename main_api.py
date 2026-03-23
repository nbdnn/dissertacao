from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn

import sys
# Add the current directory to sys.path to allow imports like `app.agents`
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncio
from app.agents.adk_operator import build_adk_operator_agent
from app.orchestrator.scheduler import background_orchestrator
from app.download_all_tles import requestTles

app = FastAPI(title="SafeOnOrbit API", description="Backend for ADK Agent and Vizier Integration")

# Configure CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev, allow all. TBD tighten for prod.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instance
adk_agent = None

from typing import Optional

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    error: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    global adk_agent
    try:
        print("Building ADK Operator Agent...")
        adk_agent = build_adk_operator_agent()
        print("Agent built successfully.")
    except Exception as e:
        print(f"FAILED to build agent: {e}")
        # We don't crash the server, so the frontend can display the error gracefully
        adk_agent = None

    # Start Orchestrator Task
    try:
        print("Starting ADK Orchestrator background task...")
        asyncio.create_task(background_orchestrator())
    except Exception as e:
        print(f"FAILED to start orchestrator: {e}")

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    global adk_agent
    if not adk_agent:
        return ChatResponse(
            response="", 
            error="ADK Agent is not initialized. Check server logs (missing GCP credentials?)."
        )
    
    try:
        # Pass the input to LangChain agent
        # Using a threadpool run_in_executor in production, but simplified for dev
        print(f"Received message: {req.message}")
        result = adk_agent.invoke({"input": req.message})
        return ChatResponse(response=result["output"], error=None)
    except Exception as e:
        print(f"Error invoking agent: {e}")
        return ChatResponse(
            response="",
            error=f"Error invoking agent: {str(e)}"
        )

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "agent_loaded": adk_agent is not None}

@app.get("/api/tles")
async def get_tles():
    """
    Returns the complete list of available TLEs using the download_all_tles script.
    It will automatically fetch from Space-Track or the local json cache.
    """
    try:
        tles = requestTles()
        if not tles:
            raise HTTPException(status_code=500, detail="Failed to retrieve TLE data.")
        return {"tles": tles}
    except Exception as e:
        print(f"Error fetching TLEs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class MarkSatelliteRequest(BaseModel):
    norad_id: int

@app.post("/api/satellites/mark")
async def mark_satellite_endpoint(req: MarkSatelliteRequest):
    try:
        from app.database import mark_satellite
        mark_satellite(req.norad_id)
        return {"status": "ok", "message": f"Satellite {req.norad_id} marked for historical tracking."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/satellites/historical/{norad_id}")
async def get_historical_tles_endpoint(norad_id: int):
    try:
        from app.database import get_historical_tles
        history = get_historical_tles(norad_id)
        return {"norad_id": norad_id, "history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
