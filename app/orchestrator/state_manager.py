import json
import os
import fcntl
from typing import Dict, Any, Optional
import time

# Get project root
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
STATE_FILE = os.path.join(project_root, "cenario1", "orchestrator_state.json")

def _load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"satellites": {}}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"satellites": {}}

def _save_state(state: Dict[str, Any]):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True) # Ensure cenario1 exists conceptually
    # Because fcntl needs a real file handle, we open it
    with open(STATE_FILE, "w") as f:
        # File locking to prevent race conditions from concurrent fastAPI requests/scheduler
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(state, f, indent=4)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def get_satellite_state(sat_id: str) -> Dict[str, Any]:
    """
    Returns the current state for a given satellite ID.
    Status can be: "PENDING_DOWNLOAD", "SCREENING_DONE", "ANALYSIS_DONE", "MANEUVER_OPTIMIZED"
    """
    state = _load_state()
    return state.get("satellites", {}).get(str(sat_id), {
        "status": "PENDING_DOWNLOAD",
        "last_updated": 0,
        "latest_analysis_file": None,
        "latest_solution_file": None,
        "threat_count": 0
    })

def update_satellite_state(sat_id: str, updates: Dict[str, Any]):
    """
    Updates the state for a given satellite ID with new values.
    """
    # Wait to get the lock implicitly handled via atomic logic if it gets complex,
    # but for simple json parsing, we just read without lock and write with it. 
    # For a low throughput scheduler, this is sufficient.
    state = _load_state()
    if "satellites" not in state:
        state["satellites"] = {}
    
    current_sat_state = state["satellites"].get(str(sat_id), {
        "status": "PENDING_DOWNLOAD",
        "last_updated": 0,
        "latest_analysis_file": None,
        "latest_solution_file": None,
        "threat_count": 0
    })
    
    current_sat_state.update(updates)
    current_sat_state["last_updated"] = time.time()
    
    state["satellites"][str(sat_id)] = current_sat_state
    _save_state(state)
