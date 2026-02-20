import sys
import os
import json
import numpy as np

# Hack imports
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.orekit_config import setup_orekit
setup_orekit()


def main():
    # 1. Load the latest analysis file
    analysis_dir = os.path.join(os.path.dirname(__file__), "analysis_results")
    files = [f for f in os.listdir(analysis_dir) if f.startswith("analysis_ephemeris_")]
    if not files:
        print("No analysis files found.")
        return

    latest_file = max([os.path.join(analysis_dir, f) for f in files], key=os.path.getctime)
    print(f"Loading conjunctions from: {latest_file}")

    with open(latest_file, 'r') as f:
        data = json.load(f)

    if not data:
        print("Analysis file is empty.")
        return

    print(f"Found {len(data)} conjunctions to process.\n")
    print("-" * 60)

    for i, conj in enumerate(data):
        try:
            # 2. Extract Data
            tca_str = conj['tca_utc'].replace("Z", "")

            # Primary Metadata
            p_dict = {
                "OBJECT_NAME": conj['primary_name'],
                "NORAD_CAT_ID": conj['primary_id'],
                "OBJECT_TYPE": "PAYLOAD"
            }

            # Secondary Metadata
            s_dict = {
                "OBJECT_NAME": conj['secondary_name'],
                "NORAD_CAT_ID": conj['secondary_id'],
                "OBJECT_TYPE": "PAYLOAD"
            }

            print(f"[{i + 1}/{len(data)}] Conjunction Analysis")
            print(f"   Primary Object ID: {p_dict['NORAD_CAT_ID']} ({p_dict['OBJECT_NAME']})")
            print(f"   Secondary Object ID: {s_dict['NORAD_CAT_ID']} ({s_dict['OBJECT_NAME']})")
            print(f"   TCA: {tca_str}")

            # 3. Read Analysis Results directly from JSON
            # (We cannot re-run conjunctionAnalysis easily because we only saved the UVW covariance,
            #  but the function expects XYZ covariance input to perform the rotation itself)

            # 4. Show Probabilities
            probs = conj.get("collision_probability", {})
            dist = conj.get("min_distance_m", 0.0)
            rc_val = conj.get("rc", 0.0)

            print(f"   Min Dist: {dist / 1000.0:.4f} km")
            print(f"   Radial: {conj.get('radial_dist_m', 0.0):.2f} m")
            print(f"   In-Track: {conj.get('along_track_dist_m', 0.0):.2f} m")
            print(f"   Cross-Track: {conj.get('cross_track_dist_m', 0.0):.2f} m")
            print(f"   RC: {rc_val:.2f} m")

            # Print Sigmas
            sig_uvw_p = np.array(conj.get("sigma_uvw_primary", []))
            sig_uvw_s = np.array(conj.get("sigma_uvw_secondary", []))

            print(f"   Sigmas UVW (Primary): {sig_uvw_p} m")
            print(f"   Sigmas UVW (Secondary): {sig_uvw_s} m")

            print("   Probabilities:")
            for method, val in probs.items():
                print(f"     - {method}: {val:.6e}")
            print("-" * 60)

        except Exception as e:
            print(f"   Error processing conjunction {i}: {e}")
            import traceback
            traceback.print_exc()
            print("-" * 60)


if __name__ == "__main__":
    main()
