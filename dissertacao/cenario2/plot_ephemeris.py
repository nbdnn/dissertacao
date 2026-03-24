import os
import sys
import numpy as np
import matplotlib.pyplot as plt

# Add project root to path
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from cenario2.parse_ephemerides import parse_stk_ephemeris
from app.orekit_config import setup_orekit


def load_ephemeris_data(norad_id):
    expected_file = os.path.join(project_root, "cenario2", "data", f"SP_{norad_id}.e")
    if not os.path.exists(expected_file):
        print(f"File not found: {expected_file}")
        return None
    data = parse_stk_ephemeris(expected_file)
    # Check keys
    if norad_id in data:
        return data[norad_id]
    elif str(norad_id) in data:
        return data[str(norad_id)]

    # Fallback: check if only one key exists
    keys = list(data.keys())
    if len(keys) == 1:
        return data[keys[0]]

    print(f"Key {norad_id} not found in {keys}")
    return None


def main():
    setup_orekit()

    # Imports need to happen after setup_orekit
    from org.hipparchus.analysis.interpolation import HermiteInterpolator  # type: ignore
    from org.hipparchus.analysis.differentiation import DSFactory  # type: ignore

    norad_id = 47699
    data = load_ephemeris_data(norad_id)

    if not data:
        print("No data found.")
        return

    # 1. Extract Raw Data
    # data is list of (date, pos, vel, cov)
    dates_raw = []
    pos_raw = []
    vel_raw = []

    start_date = data[0][0]

    for entry in data:
        dt = entry[0].durationFrom(start_date)
        dates_raw.append(dt)
        pos_raw.append(entry[1])
        vel_raw.append(entry[2])

    pos_raw = np.array(pos_raw)
    vel_raw = np.array(vel_raw)
    dates_raw = np.array(dates_raw)

    print(f"Loaded {len(dates_raw)} points. Duration: {dates_raw[-1]:.2f} s")

    # 2. Generate Interpolation Grid (10s step)
    step = 10.0
    interp_times = np.arange(0, dates_raw[-1], step)

    pos_interp = []
    vel_interp = []

    print(f"Interpolating {len(interp_times)} points...")

    for t_target in interp_times:
        idx = np.searchsorted(dates_raw, t_target)

        k = max(0, idx - 1)
        if k >= len(dates_raw) - 1:
            k = len(dates_raw) - 2

        # Window: k-1, k, k+1, k+2
        start_k = max(0, k - 1)
        end_k = min(len(dates_raw), k + 3)

        interpolator = HermiteInterpolator()

        for i in range(start_k, end_k):
            # Add sample point relative to TARGET date (t=0 at target)
            dt_sample = dates_raw[i] - t_target

            p_val = [float(x) for x in pos_raw[i]]
            v_val = [float(x) for x in vel_raw[i]]

            interpolator.addSamplePoint(float(dt_sample), p_val, v_val)

        # Interpolate at 0.0
        # Using DSFactory for derivatives (Velocity)
        factory = DSFactory(1, 1)
        t_ds = factory.variable(0, 0.0)

        try:
            interp_ds = interpolator.value(t_ds)    # Returns DerivativeStructure[]

            # Extract
            px = interp_ds[0].getValue()
            py = interp_ds[1].getValue()
            pz = interp_ds[2].getValue()

            vx = interp_ds[0].getPartialDerivative(1)
            vy = interp_ds[1].getPartialDerivative(1)
            vz = interp_ds[2].getPartialDerivative(1)

            pos_interp.append([px, py, pz])
            vel_interp.append([vx, vy, vz])
        except Exception:
            # Fallback or NaN
            pos_interp.append([np.nan, np.nan, np.nan])
            vel_interp.append([np.nan, np.nan, np.nan])

    pos_interp = np.array(pos_interp)
    vel_interp = np.array(vel_interp)

    # 3. Plotting
    fig, axes = plt.subplots(3, 2, figsize=(15, 12), sharex=True)
    fig.suptitle(f"Ephemeris Data & Interpolation (Step=10s) - Object {norad_id}", fontsize=16)

    components = ['X', 'Y', 'Z']

    # Plot Position (Left Column)
    for i in range(3):
        ax = axes[i, 0]
        ax.scatter(dates_raw, pos_raw[:, i], c='red', s=10, label='Raw (Points)', zorder=2)
        ax.plot(
            interp_times, pos_interp[:, i], c='blue', alpha=0.7,
            linewidth=1, label='Interp (10s)', zorder=1
        )
        ax.set_ylabel(f"Pos {components[i]} (m)")
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend()

    # Plot Velocity (Right Column)
    for i in range(3):
        ax = axes[i, 1]
        ax.scatter(dates_raw, vel_raw[:, i], c='green', s=10, label='Raw (Points)', zorder=2)
        ax.plot(
            interp_times, vel_interp[:, i], c='purple', alpha=0.7,
            linewidth=1, label='Interp (10s)', zorder=1
        )
        ax.set_ylabel(f"Vel {components[i]} (m/s)")
        ax.yaxis.set_label_position("right")
        ax.yaxis.tick_right()
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend()

    axes[2, 0].set_xlabel("Time from Start (s)")
    axes[2, 1].set_xlabel("Time from Start (s)")

    output_file = os.path.join(
        project_root, "cenario2", "results",
        "orbit_components_interpolation.png"
    )
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_file, dpi=150)
    print(f"Plot saved to {output_file}")
    # plt.show()


if __name__ == "__main__":
    main()
