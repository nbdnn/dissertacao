import sys
import os
import re
import numpy as np
from datetime import datetime

# Add project root to path to allow importing app.orekit_config
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# Try importing Orekit setup
try:
    from app.orekit_config import setup_orekit
    HAS_OREKIT_CONFIG = True
except ImportError:
    HAS_OREKIT_CONFIG = False
    print(
        "Warning: Could not import app.orekit_config. "
        "Orekit functions will rely on manual setup or fail."
    )


def create_ephemeris_propagator(parsed_data, frame=None):
    """
    Creates an Orekit Ephemeris propagator from parsed STK data.
    """
    if 'orekit' not in sys.modules:
        import orekit_jpype
        if HAS_OREKIT_CONFIG:
            setup_orekit()
        else:
            orekit_jpype.initVM()

    from org.orekit.propagation.analytical import Ephemeris         # type: ignore
    from org.orekit.utils import PVCoordinates, Constants           # type: ignore
    from org.orekit.orbits import CartesianOrbit                    # type: ignore
    from org.orekit.propagation import SpacecraftState              # type: ignore
    from org.orekit.frames import FramesFactory                     # type: ignore
    from org.hipparchus.geometry.euclidean.threed import Vector3D   # type: ignore
    from java.util import ArrayList                                 # type: ignore

    if frame is None:
        frame = FramesFactory.getEME2000()

    states_list = ArrayList()
    mu = Constants.IERS2010_EARTH_MU

    for date, pos, vel, _ in parsed_data:
        # pos/vel are numpy arrays in meters and m/s
        pv = PVCoordinates(
            Vector3D(float(pos[0]), float(pos[1]), float(pos[2])),
            Vector3D(float(vel[0]), float(vel[1]), float(vel[2]))
        )
        # Using CartesianOrbit to represent the state
        orbit = CartesianOrbit(pv, frame, date, mu)
        state = SpacecraftState(orbit)
        states_list.add(state)

    return Ephemeris(states_list, 8)


def get_time_grid(start_date, end_date, step=180.0):
    """
    Generates a list of AbsoluteDates from start to end with step.
    """
    grid = []
    curr = start_date
    while curr.compareTo(end_date) <= 0:
        grid.append(curr)
        curr = curr.shiftedBy(float(step))
    return grid


def sample_propagator(propagator, dates, frame):
    """
    Samples the propagator at given dates.
    Returns list of (date, pos_arr, vel_arr, None).
    """

    samples = []
    for date in dates:
        pv = propagator.getPVCoordinates(date, frame)
        p = pv.getPosition()
        v = pv.getVelocity()
        p_arr = np.array([p.getX(), p.getY(), p.getZ()])
        v_arr = np.array([v.getX(), v.getY(), v.getZ()])
        samples.append((date, p_arr, v_arr, None))
    return samples


def parse_stk_date(date_str):
    """
    Parses STK date string "1 Feb 2026 04:37:24.940" into a datetime object.
    """
    # Fix Month mapping if necessary or use %b
    # Python's %b matches "Feb", etc.
    return datetime.strptime(date_str, "%d %b %Y %H:%M:%S.%f")


def parse_stk_ephemeris(file_path):
    """
    Parses an STK Ephemeris (.e) file and returns a dictionary compatible with the Sieve algorithm.

    Format: { NORAD_ID: [(AbsoluteDate, pos_arr, vel_arr, cov_arr), ...] }

    Units are converted from km (STK) to meters (Sieve).
    """

    # Initialize Orekit if explicitly called here (lazy loading)
    if 'orekit' not in sys.modules:
        import orekit_jpype
        if HAS_OREKIT_CONFIG:
            setup_orekit()
        else:
            orekit_jpype.initVM()

    # Orekit Imports
    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
    # from org.orekit.utils import PVCoordinates
    # frame = FramesFactory.getEME2000() # If conversion is needed, but we start with raw parsing

    utc = TimeScalesFactory.getUTC()

    metadata = {}
    ephemeris_data = []  # List of dicts {time, date, pos, vel}
    covariance_map = {}  # Dict of time -> 6x6 numpy array

    # Flags and pointers
    header_section = True
    ephemeris_section = False
    covariance_section = False

    sat_id = None
    epoch_date = None
    distance_unit_factor = 1000.0  # Default to Kilometers -> Meters conversion

    with open(file_path, 'r') as f:
        lines = f.readlines()

    for line in lines:
        line_clean = line.strip()

        # Skip empty lines
        if not line_clean:
            continue

        # Parse Header
        if header_section:
            if line_clean == 'EphemerisTimePosVel':
                header_section = False
                ephemeris_section = True

                # Process metadata to setup epoch and units
                if 'ScenarioEpoch' in metadata:
                    dt = parse_stk_date(metadata['ScenarioEpoch'])

                    # specific utc handling for orekit
                    epoch_date = AbsoluteDate(
                        dt.year,
                        dt.month,
                        dt.day,
                        dt.hour,
                        dt.minute,
                        dt.second + dt.microsecond / 1e6,
                        utc
                    )

                else:
                    raise ValueError("ScenarioEpoch not found in header")

                if 'DistanceUnit' in metadata:
                    if metadata['DistanceUnit'].lower() == 'kilometers':
                        distance_unit_factor = 1000.0
                    elif metadata['DistanceUnit'].lower() == 'meters':
                        distance_unit_factor = 1.0
                    else:
                        print(
                            f"Warning: Unknown DistanceUnit '{metadata['DistanceUnit']}'. "
                            "Assuming Meters."
                        )
                        distance_unit_factor = 1.0

                continue

            # Catch Satellite ID in comments
            if line_clean.startswith('#'):
                if "Satellite ID" in line_clean:
                    # Format: # Satellite ID = 47699
                    match = re.search(r"Satellite ID\s*=\s*(\d+)", line_clean)
                    if match:
                        sat_id = int(match.group(1))
                continue

            # Key-Value pairs in header (mostly "Key     Value")
            parts = line_clean.split(None, 1)
            if len(parts) == 2:
                key, value = parts
                metadata[key] = value
            elif len(parts) == 1:
                if 'stk.v' in parts[0]:
                    metadata['version'] = parts[0]
                elif parts[0] == 'BEGIN':
                    continue
                else:
                    metadata[parts[0]] = True

        # Parse Ephemeris Data (Time X Y Z Vx Vy Vz) -> km to m
        elif ephemeris_section:
            if line_clean == 'CovarianceTimePosVel':
                ephemeris_section = False
                covariance_section = True
                continue

            parts = line_clean.split()
            if len(parts) >= 7:
                try:
                    t_offset = float(parts[0])

                    # Convert units: km -> m
                    # x, y, z, vx, vy, vz
                    pos = np.array(
                        [float(parts[1]), float(parts[2]), float(parts[3])]
                    ) * distance_unit_factor

                    vel = np.array(
                        [float(parts[4]), float(parts[5]), float(parts[6])]
                    ) * distance_unit_factor

                    # Calculate Date
                    current_date = epoch_date.shiftedBy(t_offset)

                    ephemeris_data.append({
                        'time': t_offset,
                        'date': current_date,
                        'pos': pos,
                        'vel': vel
                    })

                except ValueError:
                    continue
            elif 'END' in line_clean:
                break

        # Parse Covariance
        elif covariance_section:
            if 'END' in line_clean:
                break

            # Format: Time CovValues... (Lower Triangular 6x6)
            # 0.00 Val1 Val2 ... Val21
            parts = line_clean.split()
            # Expected length: 1 (time) + 21 (cov values) = 22
            if len(parts) >= 22:
                try:
                    t_offset = float(parts[0])
                    cov_values = [float(x) for x in parts[1:]]

                    # 6x6 Matrix
                    # Unit conversion:
                    # Pos terms (km^2) -> m^2 (factor^2)
                    # Pos-Vel terms (km*km/s) -> m^2/s (factor^2)
                    # Vel terms (km/s^2) -> m^2/s^2 (factor^2)
                    # All terms scale by distance_unit_factor^2
                    scale_sq = distance_unit_factor ** 2

                    cov_matrix = np.zeros((6, 6))
                    idx = 0

                    # Fill Lower Triangular (Row-major)
                    # (0,0)
                    # (1,0) (1,1)
                    # (2,0) (2,1) (2,2)
                    # ...
                    for i in range(6):
                        for j in range(i + 1):
                            val = cov_values[idx] * scale_sq
                            cov_matrix[i, j] = val
                            cov_matrix[j, i] = val  # Symmetric
                            idx += 1

                    # Key by time (rounded to avoid float issues)
                    t_key = round(t_offset, 6)
                    covariance_map[t_key] = cov_matrix

                except ValueError:
                    continue
                except IndexError:
                    continue

    if sat_id is None:
        # Fallback if ID not found in header, maybe try filename or default
        # For now, return -1 or raise warning
        print(f"Warning: No Satellite ID found in {file_path}")
        sat_id = 0  # Placeholder

    # Merge Ephemeris and Covariance
    final_data = []

    for item in ephemeris_data:
        t_key = round(item['time'], 6)
        cov = covariance_map.get(t_key, None)

        # Tuple: (Date, Pos, Vel, Cov)
        final_data.append((item['date'], item['pos'], item['vel'], cov))

    return {sat_id: final_data}


if __name__ == "__main__":

    # Default test file
    test_file = "cenario2/data/SP_47699.e"

    if len(sys.argv) > 1:
        test_file = sys.argv[1]

    if os.path.exists(test_file):
        print(f"Parsing {test_file} for Sieve format...")
        try:
            result = parse_stk_ephemeris(test_file)

            # Print Summary
            for sat_id, state_list in result.items():
                print(f"\nSatellite ID: {sat_id}")
                print(f"Total States: {len(state_list)}")

                if len(state_list) > 0:
                    first = state_list[0]
                    last = state_list[-1]

                    print(f"First State: Date={first[0]}, Pos={first[1]} m")
                    print(f"Last State:  Date={last[0]}, Pos={last[1]} m")

                    # Verify types
                    from org.orekit.time import AbsoluteDate  # type: ignore
                    if isinstance(first[0], AbsoluteDate):
                        print("✅ Date Type Check Passed (AbsoluteDate)")
                    else:
                        print(f"❌ Date Type Check Failed: {type(first[0])}")

                    if isinstance(first[1], np.ndarray):
                        print("✅ Position Type Check Passed (numpy)")

                    if isinstance(first[3], np.ndarray):
                        print(f"✅ Covariance Found (Shape: {first[3].shape})")
                        print(f"   Cov[0,0] (Var X): {first[3][0, 0]}")
                    else:
                        print("❌ Covariance Missing or None")

        except Exception as e:
            print(f"Error during parsing: {e}")
            import traceback
            traceback.print_exc()

    else:
        print(f"File {test_file} not found.")
