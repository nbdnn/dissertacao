import os
import sys
import glob

# Add project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.orekit_config import setup_orekit
from cenario2.ephemeris_extension import extend_ephemeris_file
from cenario2.parse_ephemerides import parse_stk_ephemeris


def main():
    import argparse
    from datetime import datetime

    # Args
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-date', type=str, default="2026-02-19T12:00:00",
                        help="Analysis Start Date (UTC) ISO Format. Default: 2026-02-19T12:00:00")
    args = parser.parse_args()

    setup_orekit()

    from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
    utc = TimeScalesFactory.getUTC()

    # Parse Argument Date
    try:
        dt = datetime.fromisoformat(args.start_date)
        # Target Date for extension (needs to cover this date)
        target_date = AbsoluteDate(dt.year, dt.month, dt.day, dt.hour,
                                   dt.minute, float(dt.second), utc)
    except ValueError:
        print(f"Invalid date format: {args.start_date}. Use ISO format (YYYY-MM-DDTHH:MM:SS)")
        sys.exit(1)

    # Validation Threshold: (e.g. 20 days before target)
    # Keeping original hardcoded or making it dynamic?
    # Let's keep the logic safe: if target moves, threshold should arguably move.
    # But for now, I will leave the hardcoded one unless it conflicts heavily.
    # Actually, let's make it relative to match the shift.
    # Original: Feb 17 (Target) -> Jan 25 (Start). Diff ~ 23 days.
    # New: Target - 25 days.
    valid_start_threshold = target_date.shiftedBy(-25.0 * 86400.0)

    data_dir = os.path.join(project_root, "cenario2", "data")

    # Get all .e files
    all_files = glob.glob(os.path.join(data_dir, "SP_*.e"))

    # Filter out already extended files to find base files
    base_files = [f for f in all_files if "_extended.e" not in f]

    # Sort by Satellite ID (Numerical Sort)
    import re

    def get_sat_id(filepath):
        match = re.search(r"SP_(\d+)\.e$", os.path.basename(filepath))
        return int(match.group(1)) if match else float('inf')

    base_files.sort(key=get_sat_id)

    print(f"Found {len(base_files)} base Ephemeris files.")
    print(f"Target Extension Date: {target_date.toString()}")

    for i, file_path in enumerate(base_files):
        filename = os.path.basename(file_path)
        name_no_ext = os.path.splitext(filename)[0]

        extended_path = os.path.join(data_dir, f"{name_no_ext}_extended.e")

        print(f"[{i + 1}/{len(base_files)}] Processing {filename}...")

        # Removed redundant 'if exists' check to allow 'extend_ephemeris_file'
        # to handle logging and validation (extended file check is done inside)

        try:
            # Check Start Date (Filter old files)
            data_map = parse_stk_ephemeris(file_path)
            if not data_map:
                print(f"  Skipping {filename}: No valid data parsed.")
                continue

            # Assume first object is the main one
            obj_id = list(data_map.keys())[0]
            states = data_map[obj_id]

            if not states:
                print(f"  Skipping {filename}: Empty state list.")
                continue

            start_date = states[0][0]

            if start_date.compareTo(valid_start_threshold) < 0:
                print(f"  Skipping {filename}: Data starts too early ({start_date.toString()})")
                continue

            extend_ephemeris_file(file_path, extended_path, target_date)
        except Exception as e:
            print(f"  Error extending {filename}: {e}")


if __name__ == "__main__":
    main()
