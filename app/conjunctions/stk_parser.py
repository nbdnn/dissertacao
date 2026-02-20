import sys
import os
import re
import numpy as np
from datetime import datetime

# Add project root to path to allow importing app.orekit_config
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# Try importing Orekit setup
try:
    from app.orekit_config import setup_orekit
    HAS_OREKIT_CONFIG = True
except ImportError:
    HAS_OREKIT_CONFIG = False
    # If we are inside app/conjunctions, maybe we can import relative?
    pass


def parse_stk_date(date_str):
    """
    Parses STK date string "1 Feb 2026 04:37:24.940" into a datetime object.
    """
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


def parse_stk_ephemeris_filtered(file_path, tca_list, window_seconds=600.0):
    """
    Parses an STK Ephemeris (.e) file selectively, only reading points within
    +/- window_seconds around the provided TCA list.

    tca_list: List of AbsoluteDate objects (TCAs provided by screening)
    window_seconds: Total window centered on TCA (e.g. 300s -> +/- 150s) will be
                    processed.
    
    Returns: { NORAD_ID: [(AbsoluteDate, pos_arr, vel_arr, cov_arr), ...] }
    """
    
    # Initialize Orekit if not already
    if 'orekit' not in sys.modules:
        import orekit_jpype
        if HAS_OREKIT_CONFIG:
            setup_orekit()
        else:
            orekit_jpype.initVM()

    from org.orekit.time import AbsoluteDate, TimeScalesFactory

    utc = TimeScalesFactory.getUTC()

    metadata = {}
    ephemeris_data = []  
    covariance_map = {}  

    header_section = True
    ephemeris_section = False
    covariance_section = False

    sat_id = None
    epoch_date = None
    distance_unit_factor = 1000.0 

    # Prepare Time Windows relative to Epoch
    # We can't calculate relative times until we parse ScenarioEpoch from header.
    # So we defer range calculation to after header processing.
    ranges = []

    with open(file_path, 'r') as f:
        # We process line-by-line using an iterator to allow manual advancing if needed,
        # but simple for-loop is usually fine.
        iterator = iter(f)
        
        for line in iterator:
            line_clean = line.strip()

            if not line_clean:
                continue

            # --- Header Processing ---
            if header_section:
                if line_clean == 'EphemerisTimePosVel':
                    header_section = False
                    ephemeris_section = True

                    if 'ScenarioEpoch' in metadata:
                        dt = parse_stk_date(metadata['ScenarioEpoch'])
                        epoch_date = AbsoluteDate(
                            dt.year, dt.month, dt.day,
                            dt.hour, dt.minute, dt.second + dt.microsecond / 1e6,
                            utc
                        )
                    else:
                        raise ValueError("ScenarioEpoch not found in header")

                    if 'DistanceUnit' in metadata:
                        val = metadata['DistanceUnit'].lower()
                        if val == 'kilometers': distance_unit_factor = 1000.0
                        elif val == 'meters': distance_unit_factor = 1.0
                        else: distance_unit_factor = 1.0

                    # Now that we have epoch, calculate relative time ranges
                    half_window = window_seconds / 2.0
                    raw_ranges = []
                    for tca in tca_list:
                        # Duration in seconds from Epoch to TCA
                        dt_sec = tca.durationFrom(epoch_date)
                        raw_ranges.append((dt_sec - half_window, dt_sec + half_window))
                    
                    # Sort and merge overlapping ranges
                    if not raw_ranges:
                        # No TCAs? Return empty
                        return {sat_id: []}
                        
                    raw_ranges.sort(key=lambda x: x[0])
                    
                    merged = []
                    curr_start, curr_end = raw_ranges[0]
                    for r_start, r_end in raw_ranges[1:]:
                        if r_start <= curr_end:  # Overlap or adjacent
                            curr_end = max(curr_end, r_end)
                        else:
                            merged.append((curr_start, curr_end))
                            curr_start, curr_end = r_start, r_end
                    merged.append((curr_start, curr_end))
                    
                    # Flip list to use as a stack (pop from end) or just iterate with index
                    # Let's use an index pointer
                    range_idx = 0
                    current_range_start = merged[0][0]
                    current_range_end = merged[0][1]
                    
                    continue

                if line_clean.startswith('#'):
                    if "Satellite ID" in line_clean:
                        match = re.search(r"Satellite ID\s*=\s*(\d+)", line_clean)
                        if match: sat_id = int(match.group(1))
                    continue

                parts = line_clean.split(None, 1)
                if len(parts) == 2: metadata[parts[0]] = parts[1]
                elif len(parts) == 1 and 'stk.v' in parts[0]: metadata['version'] = parts[0]
                
            # --- Ephemeris Data Processing ---
            elif ephemeris_section:
                if line_clean == 'CovarianceTimePosVel':
                    ephemeris_section = False
                    covariance_section = True
                    # Reset range index for covariance pass? 
                    # Usually covariance follows same time steps.
                    # Use same ranges logic.
                    range_idx = 0
                    if merged:
                        current_range_start, current_range_end = merged[0]
                    continue
                
                parts = line_clean.split()
                if len(parts) >= 7:
                    try:
                        t_offset = float(parts[0])
                        
                        # Optimization: Check if time is within any range
                        if t_offset < current_range_start:
                            # Not yet at the window
                            continue
                        elif t_offset > current_range_end:
                            # Passed the current window. Move to next range
                            range_idx += 1
                            if range_idx >= len(merged):
                                # No more ranges to seek. 
                                # We can technically break IF we don't care about Covariance later.
                                # But if Covariance is at the bottom, we must skip lines until Covariance section.
                                # HOWEVER, parsing floats line by line to check > end is cheap.
                                # Breaking means we miss the 'CovarianceTimePosVel' switch.
                                # If we are sure we need covariance, we should probably just fast-forward.
                                # But text files require read to advance line.
                                pass
                            else:
                                current_range_start, current_range_end = merged[range_idx]
                                # Check if the point fits new range (unlikely if gap is large, but possible)
                                if t_offset < current_range_start:
                                    continue
                                elif t_offset > current_range_end:
                                     # Jumped over a tiny range? Loop until fit or exhaust
                                     valid_range = False
                                     while range_idx < len(merged):
                                         current_range_start, current_range_end = merged[range_idx]
                                         if t_offset < current_range_start: 
                                             break
                                         if t_offset <= current_range_end:
                                             valid_range = True
                                             break
                                         range_idx += 1
                                     
                                     if not valid_range:
                                         if range_idx >= len(merged):
                                             continue # Effectively skipping until end of section or file
                                         else:
                                             continue # Wait for next range

                        # If logic falls through here, t_offset is in [current_range_start, current_range_end]
                        pos = np.array([float(parts[1]), float(parts[2]), float(parts[3])]) * distance_unit_factor
                        vel = np.array([float(parts[4]), float(parts[5]), float(parts[6])]) * distance_unit_factor
                        current_date = epoch_date.shiftedBy(t_offset)
                        
                        ephemeris_data.append({
                            'time': t_offset,
                            'date': current_date,
                            'pos': pos,
                            'vel': vel
                        })

                    except ValueError:
                        continue
                elif 'END' in line_clean and 'Ephemeris' in line_clean:
                    break # End of Ephemeris block
            
            # --- Covariance Processing ---
            elif covariance_section:
                if 'END' in line_clean:
                    break

                parts = line_clean.split()
                if len(parts) >= 22: # Time + 21 values
                    try:
                        t_offset = float(parts[0])
                        
                        # Similar range filtering for covariance
                        # (Duplicated logic from ephemeris section essentially)
                        # Re-using range_idx logic requires tracking it separately or resetting it carefully
                        # Since we might have skipped ranges in Ephemeris section, we need to be robust.
                        # Simplest: Just check against all merged ranges? No, O(N*M).
                        # Use the same sliding window logic.
                        
                        # To keep it simple: We just do the "current or next" check
                        # Note: range_idx might be exhausted from previous loop if we didn't reset it.
                        if t_offset < current_range_start:
                            continue
                        elif t_offset > current_range_end:
                            # Advance range
                            # Warning: This simplistic logic assumes strict ordering and no reset.
                            # We need to handle the scan properly.
                            # Let's just do a quick loop to find valid range
                            found = False
                            while range_idx < len(merged):
                                s, e = merged[range_idx]
                                if t_offset > e:
                                    range_idx += 1
                                    continue
                                if t_offset < s:
                                    # Not reached yet
                                    found = False
                                    break
                                # Within range
                                current_range_start, current_range_end = s, e
                                found = True
                                break
                            
                            if not found:
                                continue

                        # Process Covariance
                        cov_values = [float(x) for x in parts[1:]]
                        scale_sq = distance_unit_factor ** 2
                        cov_matrix = np.zeros((6, 6))
                        idx = 0
                        for i in range(6):
                            for j in range(i + 1):
                                val = cov_values[idx] * scale_sq
                                cov_matrix[i, j] = val
                                cov_matrix[j, i] = val
                                idx += 1
                        
                        covariance_map[round(t_offset, 6)] = cov_matrix

                    except ValueError:
                        continue

    if sat_id is None:
        sat_id = 0  # Placeholder

    # Merge Ephemeris and Covariance
    final_data = []

    for item in ephemeris_data:
        t_key = round(item['time'], 6)
        cov = covariance_map.get(t_key, None)
        final_data.append((item['date'], item['pos'], item['vel'], cov))

    return {sat_id: final_data}

