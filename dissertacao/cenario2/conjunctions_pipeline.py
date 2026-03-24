import sys
import os
import glob
import json
import time
import logging
import argparse

# Hack to deal with imports from sibling directories
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Orekit Setup
from app.orekit_config import setup_orekit
setup_orekit()

from app.conjunctions.bisection import bisectionMethod
from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.stk_parser import parse_stk_ephemeris, parse_stk_ephemeris_filtered
from app.conjunctions.config import ELLIPSOID_BOUNDS
from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
from org.hipparchus.analysis.interpolation import HermiteInterpolator  # type: ignore
import numpy as np


def get_interpolated_covariance(target_date, state_list):
    """
    Interpolates covariance matrix at target_date using 4-point Hermite interpolation.

    state_list: List of tuples (date, pos, vel, cov) sorted by date.
    Returns: numpy array (6x6) or None.
    """
    if not state_list:
        return None

    # Check bounds
    dates = [s[0] for s in state_list]
    if target_date.compareTo(dates[0]) <= 0:
        return state_list[0][3]
    if target_date.compareTo(dates[-1]) >= 0:
        return state_list[-1][3]

    # Find interval using binary search
    n = len(dates)
    low = 0
    high = n - 1
    idx = -1

    while low <= high:
        mid = (low + high) // 2
        mid_date = dates[mid]
        diff = mid_date.durationFrom(target_date)
        if diff < 0:
            low = mid + 1
        elif diff > 0:
            high = mid - 1
        else:
            idx = mid
            break

    if idx == -1:
        idx = high

    idx = max(0, min(idx, n - 1))
    if dates[idx].durationFrom(target_date) > 0 and idx > 0:
        idx -= 1

    # Select 4 points: idx-1, idx, idx+1, idx+2
    start_k = max(0, idx - 1)
    end_k = min(n, idx + 3)

    # Ensure we have at least 2 points
    if end_k - start_k < 2:
        return state_list[idx][3]

    interpolator = HermiteInterpolator()

    for k in range(start_k, end_k):
        s_date = state_list[k][0]
        s_cov = state_list[k][3]

        if s_cov is None:
            continue

        dt = s_date.durationFrom(target_date)
        # Flatten covariance (6x6 -> 36)
        cov_flat = s_cov.flatten()
        # Add sample point (value only, no derivatives)
        interpolator.addSamplePoint(dt, cov_flat)

    # Interpolate
    try:
        res = interpolator.value(0.0)
        return res.reshape((6, 6))
    except Exception:
        # Fallback to nearest
        return state_list[idx][3]


def get_interpolated_velocity(target_date, state_list):
    """
    Interpolates velocity vector at target_date using 4-point Hermite interpolation.

    state_list: List of tuples (date, pos, vel, cov) sorted by date.
    Returns: numpy array of shape (3,) or None.
    """
    if not state_list:
        return None

    dates = [s[0] for s in state_list]

    # Check bounds
    if target_date.compareTo(dates[0]) <= 0:
        return state_list[0][2]
    if target_date.compareTo(dates[-1]) >= 0:
        return state_list[-1][2]

    # Find interval
    n = len(dates)
    low = 0
    high = n - 1
    idx = -1

    while low <= high:
        mid = (low + high) // 2
        mid_date = dates[mid]
        diff = mid_date.durationFrom(target_date)
        if diff < 0:
            low = mid + 1
        elif diff > 0:
            high = mid - 1
        else:
            idx = mid
            break

    if idx == -1:
        idx = high

    idx = max(0, min(idx, n - 1))
    if dates[idx].durationFrom(target_date) > 0 and idx > 0:
        idx -= 1

    # Select 4 points: idx-1, idx, idx+1, idx+2
    start_k = max(0, idx - 1)
    end_k = min(n, idx + 3)

    interpolator = HermiteInterpolator()

    for k in range(start_k, end_k):
        s_date = state_list[k][0]
        s_vel = state_list[k][2]

        dt = s_date.durationFrom(target_date)
        # Add sample point (value only)
        interpolator.addSamplePoint(dt, s_vel)

    # Interpolate
    try:
        res = interpolator.value(0.0)
        # res IS a numpy array due to jpype conversion usually, or double[]
        # If jpype returns double[], we need to convert.
        # But let's assume it behaves nicely with numpy in bisection.
        # Actually bisection code used:
        # pos_x = interp_ds[0].getValue()
        # Here we use value(double), returning double[].
        return np.array(res)
    except Exception:
        return state_list[idx][2]


# Configure logging
log_file = os.path.join(os.path.dirname(__file__), "pipeline_ephemeris.log")
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
    pattern = os.path.join(search_dir, f"screening_{base_id}_*_ephemeris.json")
    files = glob.glob(pattern)
    if not files:
        # Fallback to check without timestamp if pattern differs
        pattern = os.path.join(search_dir, f"screening_{base_id}_ephemeris.json")
        files = glob.glob(pattern)

    if not files:
        return None
    # Sort by modification time
    latest_file = max(files, key=os.path.getctime)
    return latest_file


def load_ephemeris_data(norad_id, ephemeris_dir, tca_list=None):
    # Try extended first
    path = os.path.join(ephemeris_dir, f"SP_{norad_id}_extended.e")
    if not os.path.exists(path):
        # Fallback to non-extended?
        path_orig = os.path.join(ephemeris_dir, f"SP_{norad_id}.e")
        if os.path.exists(path_orig):
            if tca_list:
                ephemeris_data = parse_stk_ephemeris_filtered(path_orig, tca_list)
                return ephemeris_data, os.path.basename(path_orig)
            return parse_stk_ephemeris(path_orig), os.path.basename(path_orig)
        return None, None

    # parse_stk_ephemeris loads the file. This is I/O + Parsing intensive.
    if tca_list:
        return parse_stk_ephemeris_filtered(path, tca_list), os.path.basename(path)
    return parse_stk_ephemeris(path), os.path.basename(path)


def get_obj_type(name):
    if not name:
        return "PAYLOAD"
    n = name.upper()
    if 'DEB' in n:
        return 'DEBRIS'
    if 'R/B' in n:
        return 'ROCKET BODY'
    return 'PAYLOAD'


def process_conjunction(item, args, primary_states, secondary_states, p_filename, s_filename, utc):
    try:
        sec_id = int(item['secondary_id'])

        # Parse Screening TCA
        tca_str = item['tca'].replace("Z", "")
        # AbsoluteDate parsing is fast, done here
        screening_tca = AbsoluteDate(tca_str, utc)

        # Refine TCA using Bisection
        search_start = screening_tca.shiftedBy(-60.0)

        # Prepare metadata dicts
        p_dict = {
            "OBJECT_NAME": "PRIMARY",
            "NORAD_CAT_ID": args.base,
            "OBJECT_TYPE": "PAYLOAD"
        }
        s_dict = {
            "OBJECT_NAME": item.get('secondary_name', 'UNKNOWN'),
            "NORAD_CAT_ID": sec_id,
            "OBJECT_TYPE": get_obj_type(item.get('secondary_name', 'UNKNOWN'))
        }

        # Run Bisection with Ephemeris Interpolation
        # h=0.5 seconds step
        times, distances, bisection_states = bisectionMethod(
            search_start,
            p_dict,
            s_dict,
            primary_states=primary_states,
            secondary_states=secondary_states,
            h=0.5
        )

        if not times or len(times) < 2:
            return None

        # Determine best point
        if distances[-1] < distances[-2]:
            best_idx = -1
        else:
            best_idx = -2

        final_tca_date = search_start.shiftedBy(float(times[best_idx]))

        # bisectionMethod now returns only Position. We interpolate velocity/covariance here.
        p_state_simple, s_state_simple = bisection_states[best_idx]
        p_pos = p_state_simple[1]
        s_pos = s_state_simple[1]

        p_vel = get_interpolated_velocity(final_tca_date, primary_states)
        s_vel = get_interpolated_velocity(final_tca_date, secondary_states)

        p_cov = get_interpolated_covariance(final_tca_date, primary_states)
        s_cov = get_interpolated_covariance(final_tca_date, secondary_states)

        # Reconstruct full state tuple: (Date, Pos, Vel, Cov)
        p_state_full = (final_tca_date, p_pos, p_vel, p_cov)
        s_state_full = (final_tca_date, s_pos, s_vel, s_cov)

        # Conjunction Analysis
        analysis_result = conjunctionAnalysis(
            primary=p_dict,
            secondary=s_dict,
            tcaTime=final_tca_date,
            verbose=False,
            ellipsoid_bounds=tuple(args.ellipsoid),
            primary_state_vector=p_state_full,
            secondary_state_vector=s_state_full
        )

        # Check violation
        if analysis_result.get('is_violated'):
            del analysis_result['is_violated']
            analysis_result['data_source'] = 'ephemeris'
            analysis_result['primary_ephemeris'] = p_filename
            analysis_result['secondary_ephemeris'] = s_filename

            # Add State Vectors (Position/Velocity only)
            analysis_result['primary_state_vector'] = {
                'position': p_pos.tolist(),
                'velocity': p_vel.tolist() if p_vel is not None else None
            }
            analysis_result['secondary_state_vector'] = {
                'position': s_pos.tolist(),
                'velocity': s_vel.tolist() if s_vel is not None else None
            }

            # Extract Alfriend Probability as main probability
            probs = analysis_result.get('collision_probability', {})
            if 'alfriend1999' in probs:
                analysis_result['collision_probability_alfriend'] = probs['alfriend1999']

            return analysis_result

    except Exception as e:
        logger.error(f"Error processing {item.get('secondary_id')}: {e}")
        return None

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Cálculo de conjunções para o cenário 2 (Efémerides)."
    )
    parser.add_argument('--base', type=int, default=47699, help="NORAD ID do satélite primário.")
    parser.add_argument(
        '--ellipsoid', nargs=3, type=float, default=list(ELLIPSOID_BOUNDS),
        help=(
            f"Semi-eixos do Elipsóide de Segurança (R_U, R_V, R_W) em metros. "
            f"Padrão: {ELLIPSOID_BOUNDS}"
        )
    )

    args = parser.parse_args()

    # 1. Find Screening List
    screenings_dir = os.path.join(os.path.dirname(__file__), "screening_ephemeris")
    screening_file = find_latest_screening(args.base, screenings_dir)

    if not screening_file:
        logger.error(
            f"Could not find generated ephemeris screening file for "
            f"{args.base} in {screenings_dir}."
        )
        sys.exit(1)

    logger.info(f"Using screening file: {screening_file}")

    # 2. Load Candidates
    with open(screening_file, 'r') as f:
        candidates = json.load(f)

    logger.info(f"Loaded {len(candidates)} candidate events from screening.")

    if not candidates:
        logger.warning("No candidates found in screening. Exiting.")
        sys.exit(0)

    # 3. Load Primary Ephemeris
    ephemeris_dir = os.path.join(os.path.dirname(__file__), "data")
    primary_data_map, p_filename = load_ephemeris_data(args.base, ephemeris_dir)

    if not primary_data_map:
        logger.error(f"Could not load ephemeris for primary {args.base} in {ephemeris_dir}")
        sys.exit(1)

    primary_states = list(primary_data_map.values())[0]
    logger.info(f"Loaded Primary Ephemeris from {p_filename}: {len(primary_states)} states.")

    # ---------------------------------------------------------
    # OPTIMIZATION: Sort candidates by Secondary ID
    # This allows us to load the ephemeris for a satellite ONCE
    # and process all its conjunction events sequentially.
    # Furthermore, we now use FILTERED loading to only read relevant lines.
    # ---------------------------------------------------------
    candidates.sort(key=lambda x: int(x['secondary_id']))
    logger.info("Sorted candidates by Secondary ID for optimized loading.")

    # Group candidates by ID to fetch all TCAs at once
    from itertools import groupby

    grouped_candidates = []
    for sec_id, group in groupby(candidates, key=lambda x: int(x['secondary_id'])):
        grouped_candidates.append((sec_id, list(group)))

    results = []
    utc = TimeScalesFactory.getUTC()
    start_time = time.time()

    processed_count = 0
    violation_count = 0

    total_groups = len(grouped_candidates)
    logger.info(f"Processing {total_groups} unique secondary objects.")

    for idx, (sec_id, group_items) in enumerate(grouped_candidates):
        # 1. Collect TCAs for this group to filter ephemeris
        group_tcas = []
        for item in group_items:
            tca_str = item['tca'].replace("Z", "")
            group_tcas.append(AbsoluteDate(tca_str, utc))

        # 2. Load Filtered Ephemeris
        # Pass the list of TCAs so the parser only reads what is needed
        sec_data_map, s_filename = load_ephemeris_data(sec_id, ephemeris_dir, tca_list=group_tcas)

        if not sec_data_map or not list(sec_data_map.values())[0]:
            logger.warning(f"Skipping {sec_id}: Ephemeris empty or not found (filtered).")
            processed_count += len(group_items)
            continue

        secondary_states = list(sec_data_map.values())[0]

        # 3. Process each event in the group
        for item in group_items:
            res = process_conjunction(
                item, args, primary_states, secondary_states,
                p_filename, s_filename, utc
            )
            processed_count += 1

            if res:
                results.append(res)
                violation_count += 1

        # Only print periodically
        if (idx + 1) % 5 == 0 or (idx + 1) == total_groups:
            status = (
                f"\rProcessed Groups: {idx + 1}/{total_groups} | "
                f"Events: {processed_count}/{len(candidates)} | "
                f"Violations: {violation_count}"
            )
            print(status, end="", flush=True)

    print()

    end_time = time.time()

    # Sort final results by TCA for readability
    results.sort(key=lambda x: x['tca_utc'])

    # 4. Save Results
    analysis_dir = os.path.join(os.path.dirname(__file__), "analysis_results")
    if not os.path.exists(analysis_dir):
        os.makedirs(analysis_dir)

    output_filename = os.path.join(
        analysis_dir,
        f"analysis_ephemeris_{args.base}_{int(time.time())}.json"
    )

    with open(output_filename, 'w') as f:
        json.dump(results, f, indent=2)

    print("=" * 60)
    print(f"Analysis Finished in {end_time - start_time:.2f}s.")
    print(f"Processed: {processed_count}/{len(candidates)}")
    print(f"Confirmed Conjunctions (Violations): {len(results)}")
    print(f"Saved to: {output_filename}")
    print("=" * 60)

    # Print violations
    for c in results:
        print(f"⚠️ VIOLATION: {c['secondary_name']} ({c['secondary_id']})")
        print(f"   TCA: {c['tca_utc']}",
              f" | Dist: {c['min_distance_m']:.2f}m | kc2: {c['kc_squared']:.4f}")


if __name__ == '__main__':
    main()
