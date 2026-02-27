import os
import sys
import json
import glob
import numpy as np
import matplotlib.pyplot as plt
import argparse

# Add project root to path
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from cenario2.parse_ephemerides import parse_stk_ephemeris
from app.orekit_config import setup_orekit


def find_latest_analysis_result(base_id=47699):
    analysis_dir = os.path.join(project_root, "cenario1", "analysis_results")
    pattern = os.path.join(analysis_dir, f"analysis_{base_id}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def load_ephemeris_data(norad_id):
    expected_file = os.path.join(project_root, "cenario2", "data", f"SP_{norad_id}.e")
    if not os.path.exists(expected_file):
        return None
    data = parse_stk_ephemeris(expected_file)
    # Flexible key check (int vs str)
    if norad_id in data:
        return data[norad_id]
    if str(norad_id) in data:
        return data[str(norad_id)]
    # Fallback if single key
    keys = list(data.keys())
    if len(keys) == 1:
        return data[keys[0]]
    return None


def main():

    parser = argparse.ArgumentParser(
        description="Comparacao entre conjunções TLE e Efémerides."
    )
    parser.add_argument('--base', type=int, default=47699, help="NORAD ID do satélite primário.")

    args = parser.parse_args()

    setup_orekit()

    from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
    from org.orekit.frames import FramesFactory  # type: ignore

    # 1. Load Analysis Objects
    analysis_file = find_latest_analysis_result(base_id=args.base)
    if not analysis_file:
        print("No analysis file found in cenario1/analysis_results")
        return

    print(f"Reading objects from: {analysis_file}")
    with open(analysis_file, 'r') as f:
        events = json.load(f)

    # Collect unique objects (ID -> TLE Info)
    objects = {}

    for ev in events:
        # Primary
        p_id = ev['primary_id']
        if p_id not in objects and 'primary_tle_line1' in ev:
            objects[p_id] = {
                'name': ev['primary_name'],
                'line1': ev['primary_tle_line1'],
                'line2': ev['primary_tle_line2']
            }

        # Secondary
        s_id = ev['secondary_id']
        if s_id not in objects and 'secondary_tle_line1' in ev:
            objects[s_id] = {
                'name': ev['secondary_name'],
                'line1': ev['secondary_tle_line1'],
                'line2': ev['secondary_tle_line2']
            }

    print(f"Found {len(objects)} unique objects with TLEs.")

    output_dir = os.path.join(project_root, "cenario2", "results", "residuals_plots")
    os.makedirs(output_dir, exist_ok=True)

    inertial_frame = FramesFactory.getEME2000()

    # 2. Process Each Object
    for obj_id, info in objects.items():
        print(f"Processing {info['name']} ({obj_id})...")

        # Load Ephemeris
        ephem_data = load_ephemeris_data(obj_id)
        if not ephem_data:
            print(f"  Skipping: No Ephemeris found for {obj_id}")
            continue

        # Setup TLE Propagator
        try:
            tle = TLE(info['line1'], info['line2'])
            propagator = TLEPropagator.selectExtrapolator(tle)
        except Exception as e:
            print(f"  Skipping: Invalid TLE for {obj_id}. Error: {e}")
            continue

        # Collect Data points
        times_rel = []

        diff_pos = []  # (TLE - Eph) in meters
        diff_vel = []  # (TLE - Eph) in m/s

        start_date = ephem_data[0][0]

        valid_points = 0

        for entry in ephem_data:
            date_eph = entry[0]
            pos_eph = entry[1]  # numpy array [x,y,z]
            vel_eph = entry[2]  # numpy array [vx,vy,vz]

            try:
                # Propagate TLE
                pv_tle = propagator.getPVCoordinates(date_eph, inertial_frame)
                pos = pv_tle.getPosition()
                pos_tle = np.array([pos.getX(), pos.getY(), pos.getZ()])
                vel = pv_tle.getVelocity()
                vel_tle = np.array([vel.getX(), vel.getY(), vel.getZ()])

                # Calculate Absolute Residuals
                d_pos = pos_tle - pos_eph
                d_vel = vel_tle - vel_eph

                diff_pos.append(d_pos)
                diff_vel.append(d_vel)
                times_rel.append(date_eph.durationFrom(start_date))
                valid_points += 1

            except Exception:
                continue

        if valid_points == 0:
            print("  No valid points computed.")
            continue

        diff_pos = np.array(diff_pos)
        diff_vel = np.array(diff_vel)
        times_rel = np.array(times_rel)

        # 3. Plotting
        fig, axes = plt.subplots(3, 2, figsize=(15, 12), sharex=True)
        fig.suptitle(f"TLE vs Ephemeris Residuals - {info['name']} ({obj_id})", fontsize=16)

        comps = ['X', 'Y', 'Z']

        # Position Residuals
        for i in range(3):
            ax = axes[i, 0]
            ax.plot(times_rel, diff_pos[:, i], color='tab:blue', linewidth=1)
            ax.set_ylabel(f"Pos {comps[i]} Residual (m)")
            ax.grid(True, alpha=0.3)
            # Add simple stats in title
            mean_err = np.mean(diff_pos[:, i])
            std_err = np.std(diff_pos[:, i])
            ax.set_title(f"Mean: {mean_err:.2f} m, Std: {std_err:.2f} m", fontsize=9)

        # Velocity Residuals
        for i in range(3):
            ax = axes[i, 1]
            ax.plot(times_rel, diff_vel[:, i], color='tab:orange', linewidth=1)
            ax.set_ylabel(f"Vel {comps[i]} Residual (m/s)")
            ax.grid(True, alpha=0.3)
            ax.yaxis.set_label_position("right")
            ax.yaxis.tick_right()
            mean_err = np.mean(diff_vel[:, i])
            std_err = np.std(diff_vel[:, i])
            ax.set_title(f"Mean: {mean_err:.4f} m/s, Std: {std_err:.4f} m/s", fontsize=9)

        axes[2, 0].set_xlabel("Time from Ephemeris Start (s)")
        axes[2, 1].set_xlabel("Time from Ephemeris Start (s)")

        out_name = f"residuals_{obj_id}.png"
        out_path = os.path.join(output_dir, out_name)

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(out_path, dpi=100)
        plt.close(fig)
        print(f"  Saved plot: {out_path}")


if __name__ == "__main__":
    main()
