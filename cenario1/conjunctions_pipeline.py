import sys
import os
import glob
import json
import time
import logging
import argparse
import subprocess

# Hack to deal with imports from sibling directories
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.orekit_config import setup_orekit
from app.download_all_tles import requestTles
from app.conjunctions.bisection import bisectionMethod
from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.config import ELLIPSOID_BOUNDS

# Configure logging
log_file = os.path.join(os.path.dirname(__file__), "pipeline.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def find_latest_screening(base_id, search_dir):
    pattern = os.path.join(search_dir, f"screening_{base_id}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    # Sort by modification time (or filename timestamp)
    latest_file = max(files, key=os.path.getctime)
    return latest_file


def run_screening_script(base_id, days, script_path):
    logger.info(f"Screening file not found for satellite {base_id}. Running screening.py...")
    cmd = [
        "uv", "run", script_path,
        "--base", str(base_id),
        "--days", str(days)
    ]
    result = subprocess.run(cmd, capture_output=False, check=True)  # Let stdout flow to console
    if result.returncode != 0:
        logger.error("Screening script failed.")
        sys.exit(1)

    # Try finding it again
    return find_latest_screening(base_id, os.getcwd())  # screening.py saves to cwd


def main():
    parser = argparse.ArgumentParser(description="Cálculo de conjunções para o cenário 1.")
    parser.add_argument('--base', type=int, default=47699, help="NORAD ID do satélite primário.")
    parser.add_argument('--days', type=float, default=7.0, help="Dias de simulação.")
    parser.add_argument(
        '--ellipsoid', nargs=3, type=float, default=list(ELLIPSOID_BOUNDS),
        help=(
            f"Semi-eixos do Elipsóide de Segurança (R_U, R_V, R_W) em metros. "
            f"Padrão: {ELLIPSOID_BOUNDS}"
        )
    )

    args = parser.parse_args()

    # 1. Find or Generate Screening List
    screenings_dir = os.path.join(project_root, "screenings")
    screening_file = find_latest_screening(args.base, screenings_dir)

    if not screening_file:
        # Fallback to old location check and move if found (optional, but good for transition)
        pass

    if not screening_file:
        screening_script = os.path.join(project_root, "app", "conjunctions", "screening.py")
        run_screening_script(args.base, args.days, screening_script)
        # Search again in screenings dir
        screening_file = find_latest_screening(args.base, screenings_dir)

        if not screening_file:
            # Fallback search if screening.py saved somewhere else or CWD issue
            # Let's assume user runs this from project root usually
            logger.error("Could not find generated screening file.")
            sys.exit(1)

    logger.info(f"Using screening file: {screening_file}")

    # 2. Load Candidates
    with open(screening_file, 'r') as f:
        candidates = json.load(f)

    candidate_ids = {int(c['secondary_id']) for c in candidates}
    logger.info(f"Loaded {len(candidate_ids)} candidate objects from screening.")

    if not candidate_ids:
        logger.warning("No candidates found in screening. Exiting.")
        sys.exit(0)

    # 3. Setup Orekit & TLEs
    logger.info("Initializing Orekit...")
    setup_orekit()

    logger.info("Fetching TLE Catalog...")
    all_cat = requestTles()

    primary_data = None
    filtered_secondaries = []

    for item in all_cat:
        norad_id = int(item['NORAD_CAT_ID'])
        item['NORAD_CAT_ID'] = norad_id

        # Ensure floats
        if "APOAPSIS" in item:
            item["APOAPSIS"] = float(item["APOAPSIS"])
        if "PERIAPSIS" in item:
            item["PERIAPSIS"] = float(item["PERIAPSIS"])

        if norad_id == args.base:
            primary_data = item
        elif norad_id in candidate_ids:
            filtered_secondaries.append(item)

    if not primary_data:
        logger.error(f"Primary satellite {args.base} not found in TLE catalog.")
        sys.exit(1)

    logger.info(f"Running Analysis on {len(candidates)} screening events.")
    logger.info(f"Ellipsoid: {args.ellipsoid} (m).")

    start_time = time.time()

    # Map secondaries for quick lookup
    sec_map = {s['NORAD_CAT_ID']: s for s in filtered_secondaries}

    results = []

    # Imports inside function to ensure JVM is started
    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
    utc = TimeScalesFactory.getUTC()

    for i, item in enumerate(candidates):
        sec_id = int(item['secondary_id'])
        if sec_id not in sec_map:
            continue

        secondary = sec_map[sec_id]

        # Parse Screening TCA
        try:
            # Handle potential Z suffix or simple ISO format
            tca_str = item['tca'].replace("Z", "")
            screening_tca = AbsoluteDate(tca_str, utc)
        except Exception as e:
            logger.warning(f"Failed to parse TCA {item['tca']}: {e}")
            continue

        # Refine TCA: Start search 60s before reported TCA
        # We assume the screening TCA is reasonably accurate, so we sweep a small window
        search_start = screening_tca.shiftedBy(-60.0)

        # Run Bisection (h=0.1s for higher precision in refinement?)
        # Original sieve used h=1.0. Let's use h=0.5 for a balance
        times, distances, __ = bisectionMethod(
            search_start,
            primary_data,
            secondary,
            h=0.5
        )

        if not times or len(times) < 2:
            logger.warning(f"Bisection failed for {sec_id} at {tca_str}")
            continue

        # Determine best point from bisection history
        if distances[-1] < distances[-2]:
            best_idx = -1
        else:
            best_idx = -2

        final_tca_date = search_start.shiftedBy(float(times[best_idx]))

        # bisectionMethod now returns only position: (date, pos)
        # We need to compute velocity and covariance using the propagation method.
        # Since TLE propagation provides both Pos and Vel, we can reuse it?
        # Re-propagate at final_tca_date using conjunctionAnalysis internal propagator
        # or manually here.

        # Let's clean up state passing
        # conjunctionAnalysis expects full state or TLE data.
        # If we pass state vector with None velocity, it might fail internal logic if velocity
        # is needed.
        # It needs velocity for metrics like Relative Velocity and CoB.

        # We can extract pos from bisection result, but velocity must be re-calculated.
        # Actually bisectionMethod for TLE case (no interpolation) iterates propagation.
        # But we changed bisectionMethod to return ONLY position for optimization!
        # Wait, the optimization in bisection.py was inside `bisectionMethod`.
        # For TLE case (when no states list provided), bisectionMethod calculates PV coordinates.
        #
        # Let's check bisection.py again. When use_interpolation is FALSE (TLE mode),
        # it calls `propagator.getPVCoordinates(date, inertialFrame)`.
        # And creates `p_state = (simulationTime, posPrimArr, velPrimArr, p_cov)`.
        #
        # Oh, I modified bisection.py to only capture POSITION in the state tuple!
        #
        # "p_state = (simulationTime, posPrimArr)"
        #
        # So for Cenario 1 (TLE), we lost Velocity in the return of bisectionMethod.
        # We need to re-propagate at TCA to get Velocity and Covariance.

        # Re-propagate to get full state at TCA
        from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
        from org.orekit.frames import FramesFactory  # type: ignore

        inertialFrame = FramesFactory.getEME2000()

        # Primary
        tle_p = TLE(primary_data["TLE_LINE1"], primary_data["TLE_LINE2"])
        prop_p = TLEPropagator.selectExtrapolator(tle_p)
        pv_p = prop_p.getPVCoordinates(final_tca_date, inertialFrame)

        p_pos = pv_p.getPosition()
        p_vel = pv_p.getVelocity()

        # Secondary
        tle_s = TLE(secondary["TLE_LINE1"], secondary["TLE_LINE2"])
        prop_s = TLEPropagator.selectExtrapolator(tle_s)
        pv_s = prop_s.getPVCoordinates(final_tca_date, inertialFrame)

        s_pos = pv_s.getPosition()
        s_vel = pv_s.getVelocity()

        # Construct full state tuples for analysis
        # (Date, PosArray, VelArray, CovArray)
        # TLE doesn't provide covariance natively here, will use default in analysis
        import numpy as np

        p_pos_arr = np.array([p_pos.getX(), p_pos.getY(), p_pos.getZ()])
        p_vel_arr = np.array([p_vel.getX(), p_vel.getY(), p_vel.getZ()])

        s_pos_arr = np.array([s_pos.getX(), s_pos.getY(), s_pos.getZ()])
        s_vel_arr = np.array([s_vel.getX(), s_vel.getY(), s_vel.getZ()])

        p_state_full = (final_tca_date, p_pos_arr, p_vel_arr, None)
        s_state_full = (final_tca_date, s_pos_arr, s_vel_arr, None)

        # Analyze with full precision and stricter bounds
        analysis_result = conjunctionAnalysis(
            primary=primary_data,
            secondary=secondary,
            tcaTime=final_tca_date,
            verbose=False,
            ellipsoid_bounds=tuple(args.ellipsoid),
            primary_state_vector=p_state_full,
            secondary_state_vector=s_state_full
        )

        if analysis_result['is_violated']:
            # Remove helper key before saving to final list
            del analysis_result['is_violated']

            # Remove covariance, sigma and collision_probability for Cenario 1
            analysis_result.pop('covariance_matrix_uvw_primary', None)
            analysis_result.pop('covariance_matrix_uvw_secondary', None)
            analysis_result.pop('sigma_uvw_primary', None)
            analysis_result.pop('sigma_uvw_secondary', None)
            analysis_result.pop('collision_probability', None)

            results.append(analysis_result)

        if i % 10 == 0:
            print(f"\rRefining {i + 1}/{len(candidates)}...", end="", flush=True)
    print()  # Newline after progress

    end_time = time.time()

    # 5. Save Results
    analysis_dir = os.path.join(os.path.dirname(__file__), "analysis_results")
    os.makedirs(analysis_dir, exist_ok=True)

    output_filename = os.path.join(
        analysis_dir,
        f"analysis_{args.base}_{int(time.time())}.json"
    )
    with open(output_filename, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info("=" * 60)
    logger.info(f"Analysis Finished in {end_time - start_time:.2f}s.")
    logger.info(f"Confirmed Conjunctions (Violations): {len(results)}")
    logger.info(f"Saved to: {output_filename}")
    logger.info("=" * 60)

    # Print violations
    for c in results:
        print(f"⚠️ VIOLATION: {c['secondary_name']} ({c['secondary_id']})")
        print(f"   TCA: {c['tca_utc']}",
              f" | Dist: {c['min_distance_m']:.2f}m | kc2: {c['kc_squared']:.4f}")


if __name__ == '__main__':
    main()
