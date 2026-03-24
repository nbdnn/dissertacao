import asyncio
import logging
import subprocess
import os
import json
import glob
from typing import List

from .state_manager import get_satellite_state, update_satellite_state

logger = logging.getLogger(__name__)

# Base IDs to monitor and orchestrate
TARGET_SATELLITES = [61046, 64830, 65774]

# Fetch every 24 hours (86400s). For demo purposes we can configure it.
POLL_INTERVAL_SEC = 3600 * 12

file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))

async def run_shell_command(cmd: List[str], cwd: str) -> bool:
    """Run a shell command asynchronously and log output."""
    logger.info(f"Running command: {' '.join(cmd)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"Command failed with exit code {process.returncode}")
            logger.error(stderr.decode())
            return False
        return True
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return False

def check_analysis_for_threats(sat_id: int) -> bool:
    """Checks if the latest analysis file for this sat_id has high risks (kc_squared < 1.0)"""
    analysis_dir = os.path.join(project_root, "cenario1", "analysis_results")
    pattern = os.path.join(analysis_dir, f"analysis_{sat_id}_*.json")
    files = glob.glob(pattern)
    if not files:
        return False
    latest_file = max(files, key=os.path.getmtime)
    try:
        with open(latest_file, 'r') as f:
            data = json.load(f)
            # Find any threat
            for event in data:
                # kc_squared default logic: < 1.0 is danger.
                if event.get("kc_squared", float('inf')) <= 1.0:
                    return True
    except Exception as e:
        logger.error(f"Could not read analysis file {latest_file}: {e}")
    return False

async def background_orchestrator():
    logger.info("Starting ADK Background Orchestrator...")
    while True:
        try:
            # 1. Update Global TLEs
            logger.info("[Orchestrator] Refreshing Global TLEs...")
            await run_shell_command(["uv", "run", "app/download_all_tles.py"], cwd=project_root)
            
            for sat_id in TARGET_SATELLITES:
                logger.info(f"[Orchestrator] Processing pipeline for satellite {sat_id}")
                
                 # 2. Run Pipeline (Screening + Analysis)
                 # Conjunction pipeline automatically calls screening.py if needed.
                 # Let's run it.
                pipeline_success = await run_shell_command([
                     "uv", "run", "cenario1/conjunctions_pipeline.py",
                     "--base", str(sat_id)
                ], cwd=project_root)
                
                if pipeline_success:
                    update_satellite_state(sat_id, {"status": "ANALYSIS_DONE"})
                    
                    # 3. Check for threats and run optimization if needed
                    has_threats = check_analysis_for_threats(sat_id)
                    state = get_satellite_state(sat_id)
                    
                    # Only optimize if not already optimized recently or if threats are high
                    if has_threats:
                        logger.info(f"[Orchestrator] ⚠️ High threats detected for {sat_id}. Triggering optimization.")
                        
                        update_satellite_state(sat_id, {"status": "AWAITING_MANEUVER"})
                        
                        # In a real environment, we'd fire the Optimizer here, but to avoid 
                        # hogging user CPU with 128 workers during polling we might want to trigger it selectively via the ADK agent instead.
                        logger.info(f"[Orchestrator] Postponed heavy PyMoo GA execution. The ADK agent can trigger it upon request.")
                        
                        # --- Vizier TCA Sandbox Recalculation ---
                        # If Vertex AI is enabled, we could spawn a targeted TCA verification study
                        # to confirm the exact time of minimum distance globally.
                        logger.info(f"[Orchestrator] Optional: Spawning Vertex Vizier TCA Study for verification...")
                        try:
                            from app.conjunctions.vizier_tca_solver import solve_tca
                            # solve_tca(primary, secondary, initial_time, project_id) # Example call
                        except Exception as e:
                            logger.error(f"[Vizier System] Failed to init: {e}")
                else:
                    logger.error(f"[Orchestrator] Pipeline failed for {sat_id}")

        except Exception as e:
            logger.error(f"[Orchestrator] Error in background loop: {e}")
        
        logger.info(f"[Orchestrator] Loop finished, sleeping for {POLL_INTERVAL_SEC} seconds...")
        await asyncio.sleep(POLL_INTERVAL_SEC)
