from google.cloud.aiplatform import vizier
import time
import numpy as np
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# Fallback fake implementation in case GCP credentials are not set locally
class FakeVizierStudy:
    def __init__(self, name):
        self.name = name
        self.trials = []
    def suggest(self, count, client_id):
        # purely fake for local without GCP
        from unittest.mock import MagicMock
        t = MagicMock()
        t.parameters = {"time_offset_s": MagicMock(value=3600.0 * len(self.trials))}
        return [t]

class VizierTCASolver:
    """
    Uses Vertex AI Vizier to find the Time of Closest Approach (TCA) 
    between two satellites by exploring the time parameter space.
    """
    def __init__(self, project_id: str, location: str = "us-central1"):
        self.project_id = project_id
        self.location = location
        try:
            from google.cloud import aiplatform
            aiplatform.init(project=project_id, location=location)
            self.has_gcp = True
        except Exception as e:
            logger.warning(f"Could not init GCP Vertex AI (Offline mode?). {e}")
            self.has_gcp = False

    def create_tca_study(self, study_id: str, display_name: str, max_days: float = 7.0):
        if not self.has_gcp:
            return FakeVizierStudy(display_name)
            
        problem = vizier.Study.Problem()
        
        # Parameter: Time Offset in Seconds from Epoch
        max_sec = max_days * 24.0 * 3600.0
        problem.parameters.append(
            vizier.Study.Problem.Parameter(
                name="time_offset_s",
                type=vizier.Study.Problem.Parameter.Type.DOUBLE,
                min_value=0.0,
                max_value=max_sec,
            )
        )

        # Objective: Minimize Distance
        problem.metric_information.append(
            vizier.Study.Problem.MetricInformation(
                name="distance_m",
                goal=vizier.Study.Problem.MetricInformation.Goal.MINIMIZE,
            )
        )

        study = vizier.Study.create_or_load(
            display_name=display_name,
            problem=problem,
        )
        return study

    def run_optimization_loop(self, study, primary_tle, secondary_tle, initial_time, num_trials=20):
        # type: ignore[reportMissingImports]
        from org.orekit.frames import FramesFactory
        # type: ignore[reportMissingImports]
        from org.orekit.propagation.analytical.tle import TLE, TLEPropagator
        
        inertialFrame = FramesFactory.getEME2000()
        propagPrimary = TLEPropagator.selectExtrapolator(
            TLE(primary_tle["TLE_LINE1"], primary_tle["TLE_LINE2"])
        )
        propagSecondary = TLEPropagator.selectExtrapolator(
            TLE(secondary_tle["TLE_LINE1"], secondary_tle["TLE_LINE2"])
        )

        best_distance = float('inf')
        best_time = 0.0

        for i in range(num_trials):
            # Suggest Trial
            trials = study.suggest(count=1, client_id=f"tca-worker-{i}") if self.has_gcp else [{"parameters": {"time_offset_s": {"value": 0.0}}}]
            trial = trials[0] if isinstance(trials, list) else trials
            
            # Extract Parameter
            t_offset = trial.parameters["time_offset_s"].value if self.has_gcp else (i * 3600)
            
            # Simulation
            eval_time = initial_time.shiftedBy(float(t_offset))
            pv_prim = propagPrimary.getPVCoordinates(eval_time, inertialFrame)
            pv_sec = propagSecondary.getPVCoordinates(eval_time, inertialFrame)
            
            pos_p = np.array([pv_prim.getPosition().getX(), pv_prim.getPosition().getY(), pv_prim.getPosition().getZ()])
            pos_s = np.array([pv_sec.getPosition().getX(), pv_sec.getPosition().getY(), pv_sec.getPosition().getZ()])
            
            dist = float(np.linalg.norm(pos_p - pos_s))
            
            if dist < best_distance:
                best_distance = dist
                best_time = t_offset
                
            # Report Measurement
            if self.has_gcp:
                measurement = vizier.Trial.Measurement()
                measurement.metrics["distance_m"] = dist
                trial.add_measurement(measurement=measurement)
                trial.complete()

        return best_distance, best_time

def solve_tca(primary, secondary, initial_time, project_id="safe-on-orbit"):
    solver = VizierTCASolver(project_id)
    study_id = f"tca_{primary['NORAD_CAT_ID']}_{secondary['NORAD_CAT_ID']}_{int(time.time())}"
    study = solver.create_tca_study(study_id, display_name=study_id)
    min_dist, tca_offset = solver.run_optimization_loop(study, primary, secondary, initial_time)
    
    return {
        "primary_id": primary["NORAD_CAT_ID"],
        "secondary_id": secondary["NORAD_CAT_ID"],
        "min_distance": min_dist,
        "tca_offset": tca_offset
    }
