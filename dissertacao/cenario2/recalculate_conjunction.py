import sys
import os
import json
import argparse
import glob
import subprocess
from datetime import datetime, timezone

# Add project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Orekit setup
try:
    from app.orekit_config import setup_orekit
    setup_orekit()
except ImportError:
    print("Failed to import/setup orekit")
    sys.exit(1)

from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
from org.hipparchus.analysis.interpolation import HermiteInterpolator  # type: ignore
import numpy as np

from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.bisection import bisectionMethod
from cenario2.parse_ephemerides import parse_stk_ephemeris


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
        return np.array(res)
    except Exception:
        return state_list[idx][2]


def get_obj_type(name):
    if not name:
        return "PAYLOAD"
    n = name.upper()
    if 'DEB' in n:
        return 'DEBRIS'
    if 'R/B' in n:
        return 'ROCKET BODY'
    return 'PAYLOAD'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True, help="Satellite ID base")
    args = parser.parse_args()

    # 1. Find input file
    cenario1_results = os.path.join(project_root, 'cenario1', 'analysis_results')
    pattern = os.path.join(cenario1_results, f"analysis_{args.base}_*.json")
    files = glob.glob(pattern)

    if not files:
        print(f"No analysis file found for base {args.base} in {cenario1_results}")
        print("Running conjunctions_pipeline to generate initial analysis...")

        pipeline_script = os.path.join(project_root, 'cenario1', 'conjunctions_pipeline.py')
        try:
            # Running strictly with 'uv run' if configured, or just python3
            cmd = ["uv", "run", pipeline_script, "--base", str(args.base)]
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Pipeline execution failed: {e}")

        # Try finding the file again in cenario1
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"Analysis file could not be generated for base {args.base}")

    # Pick latest by filename timestamp
    def get_ts(f):
        try:
            return int(os.path.basename(f).split('_')[2].split('.')[0])
        except (IndexError, ValueError):
            return 0

    input_file = max(files, key=get_ts)
    print(f"Using input file: {input_file}")

    with open(input_file, 'r') as f:
        conjunctions = json.load(f)

    results = []

    ephem_dir = os.path.join(current_dir, 'data')
    utc = TimeScalesFactory.getUTC()

    for c in conjunctions:
        id1 = c['primary_id']
        id2 = c['secondary_id']
        tca_str = c['tca_utc']

        # Load ephemerides
        path1_ext = os.path.join(ephem_dir, f"SP_{id1}_extended.e")
        path2_ext = os.path.join(ephem_dir, f"SP_{id2}_extended.e")

        file1 = path1_ext if os.path.exists(path1_ext) else None
        file2 = path2_ext if os.path.exists(path2_ext) else None

        if not file1 or not file2:
            print(
                f"Skipping {id1} vs {id2}: Missing extended ephemeris files."
            )
            continue

        file1_name = os.path.basename(file1)
        file2_name = os.path.basename(file2)
        print(f"Processing {id1} vs {id2} using {file1_name} and {file2_name}")

        try:
            # Parse Ephemerides (returns lists of states)
            data1 = parse_stk_ephemeris(file1)
            data2 = parse_stk_ephemeris(file2)

            # Assuming single object per file
            states1 = data1[list(data1.keys())[0]]
            states2 = data2[list(data2.keys())[0]]

            # Initial TCA from previous analysis
            clean_tca = tca_str.replace('Z', '')
            tca_date = AbsoluteDate(clean_tca, utc)

            # Prepare metadata dicts for bisection/analysis
            p_dict = {
                "OBJECT_NAME": c.get('primary_name', 'UNKNOWN'),
                "NORAD_CAT_ID": c.get('primary_id'),
                "OBJECT_TYPE": get_obj_type(c.get('primary_name', 'UNKNOWN'))
            }
            s_dict = {
                "OBJECT_NAME": c.get('secondary_name', 'UNKNOWN'),
                "NORAD_CAT_ID": c.get('secondary_id'),
                "OBJECT_TYPE": get_obj_type(c.get('secondary_name', 'UNKNOWN'))
            }

            # Run Bisection Algorithm
            # Start search 60s before reported TCA
            search_start = tca_date.shiftedBy(-60.0)

            times, distances, bisection_states = bisectionMethod(
                search_start,
                p_dict,
                s_dict,
                primary_states=states1,
                secondary_states=states2,
                h=0.5
            )

            if not times or len(times) < 2:
                print(f"Bisection failed for {id2} at {tca_str}")
                results.append(c)
                continue

            # Determine best point from bisection history
            if distances[-1] < distances[-2]:
                best_idx = -1
            else:
                best_idx = -2

            final_tca_date = search_start.shiftedBy(float(times[best_idx]))

            # Note: bisection_states only returns (Date, Position) in simplified mode or
            # (Date, Pos, Vel)
            # We need to re-interpolate Velocity and Covariance for Conjunction Analysis

            p_state_simple, s_state_simple = bisection_states[best_idx]
            p_pos = p_state_simple[1]
            s_pos = s_state_simple[1]

            # Interpolate Velocity and Covariance
            p_vel = get_interpolated_velocity(final_tca_date, states1)
            s_vel = get_interpolated_velocity(final_tca_date, states2)

            p_cov = get_interpolated_covariance(final_tca_date, states1)
            s_cov = get_interpolated_covariance(final_tca_date, states2)

            # Reconstruct full state vectors (Date, Pos, Vel, Cov)
            p_state_full = (final_tca_date, p_pos, p_vel, p_cov)
            s_state_full = (final_tca_date, s_pos, s_vel, s_cov)

            # Recalculate Analysis
            res = conjunctionAnalysis(
                p_dict,
                s_dict,
                final_tca_date,
                primary_state_vector=p_state_full,
                secondary_state_vector=s_state_full
            )

            # Add calculated TCA string to result
            res['tca_utc'] = final_tca_date.toString()

            # Filter redundant keys
            keys_to_exclude = [
                'primary_name', 'primary_id', 'secondary_name',
                'secondary_id', 'is_violated'
            ]

            tle_analysis_data = {k: v for k, v in c.items() if k not in keys_to_exclude}
            ephem_analysis_data = {k: v for k, v in res.items() if k not in keys_to_exclude}

            # Structured Result with comparison
            structured_result = {
                "primary_id": id1,
                "secondary_id": id2,
                "primary_name": c.get('primary_name'),
                "secondary_name": c.get('secondary_name'),
                "tle_analysis": tle_analysis_data,
                "ephemeris_analysis": ephem_analysis_data,
                "ephemeris_used": True,
                "ephemeris_files": [os.path.basename(file1), os.path.basename(file2)]
            }

            results.append(structured_result)

        except Exception as e:
            print(f"Error processing {id1} vs {id2}: {e}")
            import traceback
            traceback.print_exc()

            # Structured Error Result
            keys_to_exclude = ['primary_name', 'primary_id', 'secondary_name', 'secondary_id']
            tle_analysis_data = {k: v for k, v in c.items() if k not in keys_to_exclude}

            error_result = {
                "primary_id": id1,
                "secondary_id": id2,
                "primary_name": c.get('primary_name'),
                "secondary_name": c.get('secondary_name'),
                "tle_analysis": tle_analysis_data,
                "error": str(e),
                "ephemeris_used": False
            }
            results.append(error_result)

    # Save Results
    if results:
        ts = int(datetime.now(timezone.utc).timestamp())
        out_dir = os.path.join(current_dir, 'recalculation_results')
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        outfile = os.path.join(out_dir, f"recalculation_{args.base}_{ts}.json")
        with open(outfile, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Saved {len(results)} updated results to {outfile}")
    else:
        print("No results calculated.")


if __name__ == "__main__":
    main()
