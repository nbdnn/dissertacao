import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone


# Add project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# Orekit Setup
from app.orekit_config import setup_orekit


from app.conjunctions.sieve import sieveAlgorithm
from app.conjunctions.config import (
    ELLIPSOID_BOUNDS,
    SCREENING_MULTIPLIER,
    LARGE_SCREENING_BOUNDS
)
from app.download_all_tles import requestTles
from cenario2.download_ephemeris import request_sat_catalog, get_spacebook_id, download_ephemeris
from cenario2.ephemeris_extension import extend_ephemeris_file


# (Orekit imports moved inside scope where JVM is ready)


# Configure Logger Explicitly
logger = logging.getLogger("ScreeningPipeline")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
logger.propagate = False


def run_large_tle_screening(base_id, days, start_date, primaries, secondaries):
    """
    Step 1: Run Sieve with TLE and Very Large Bounds.
    """
    logger.info("--- Step 1: Large TLE Screening ---")

    # Threshold = max dimension
    threshold = max(LARGE_SCREENING_BOUNDS)
    logger.info(f"Using Large Threshold: {threshold / 1000.0} km")

    # Save to cenario2/screening_tle
    out_dir = os.path.join(current_dir, "screening_tle")
    os.makedirs(out_dir, exist_ok=True)

    # Generate unique filename based on parameters to avoid overwrite and enable caching
    date_str = start_date.strftime("%Y%m%dT%H%M%S")
    filename = os.path.join(out_dir, f"screening_{base_id}_{date_str}_{days}d_large.json")

    # Check if this specific screening was already performed
    if os.path.exists(filename):
        logger.info(f"Existing screening file found: {os.path.basename(filename)}")
        try:
            with open(filename, 'r') as f:
                results = json.load(f)
            logger.info(f"Loaded {len(results)} candidates from cache. Skipping TLE screening.")
            return results, filename
        except Exception as e:
            logger.warning(f"Could not read existing file ({e}). Re-running screening.")

    # Run Sieve
    results = sieveAlgorithm(
        primariesID=[base_id],
        daysOfSimulation=days,
        threshold=threshold,
        ellipsoid_bounds=LARGE_SCREENING_BOUNDS,
        verbose=False,
        tles=([primaries], secondaries),
        verboseConjAnalysis=False,
        start_date=start_date,
        screening_mode=True
    )

    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"Large screening found {len(results)} candidates. Saved to {filename}")
    return results, filename


def download_and_extend_ephemeris(base_id, candidates, days_sim, start_date_dt):
    """
    Step 2: Download and Extend Ephemerides for Base + Candidates.
    """
    logger.info("--- Step 2: Download & Extend Ephemerides ---")

    # Collect Unique IDs
    ids_to_process = {base_id}
    for c in candidates:
        if 'secondary_id' in c:
            ids_to_process.add(int(c['secondary_id']))

    logger.info(f"Need ephemerides for {len(ids_to_process)} objects.")

    catalog = request_sat_catalog(output_dir=os.path.join(current_dir, "data"))

    data_dir = os.path.join(current_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    end_date_dt = start_date_dt.shiftedBy(float(days_sim * 86400.0))

    target_date = end_date_dt

    # Phase 1: Download All
    logger.info("Starting Batch Download...")
    downloaded_files = []

    sorted_ids = sorted(list(ids_to_process))
    total_ids = len(sorted_ids)

    for i, norad_id in enumerate(sorted_ids):
        # Progress indication with Carriage Return (update in place)
        print(
            f"\r[{i + 1}/{total_ids}] Processing download for ID {norad_id}...",
            end="",
            flush=True
        )

        sb_id = get_spacebook_id(norad_id, catalog)
        if not sb_id:
            # print("")  # Newline to break progress bar output
            logger.warning(f"\nID {norad_id} not found in catalog. Skipping.")
            continue

        url = f"https://spacebook.com/api/entity/synthetic-covariance/{sb_id}"
        try:
            file_path = download_ephemeris(url, norad_id, data_dir)
            if file_path:
                downloaded_files.append((norad_id, file_path))
        except Exception as e:
            logger.warning(f"\nFailed to download ephemeris for {norad_id}: {e}. Skipping.")
            continue

    print("")

    # Phase 2: Extend All
    logger.info("Starting Batch Extension...")

    ext_logger = logging.getLogger("EphemerisExtension")
    ext_logger.setLevel(logging.WARNING)

    total_ext = len(downloaded_files)
    for i, (norad_id, file_path) in enumerate(downloaded_files):
        # logger.info(f"\r[{i + 1}/{total_ext}] Extending Ephemeris for ID {norad_id}...")
        print(
            f"\r[{i + 1}/{total_ext}] Extending Ephemeris for ID {norad_id}...",
            end="",
            flush=True
        )

        filename = os.path.basename(file_path)
        name_no_ext = os.path.splitext(filename)[0]
        extended_path = os.path.join(data_dir, f"{name_no_ext}_extended.e")

        try:
            extend_ephemeris_file(file_path, extended_path, target_date)

        except Exception as e:
            # Newline to separate error from progress bar
            print("")
            logger.error(f"Failed to extend {norad_id}: {e}")
            continue

    print("")


def run_ephemeris_screening(base_id, days, start_date, primaries, secondaries_tle_list):
    """
    Step 3: Run Sieve with Ephemerides.
    """
    logger.info("--- Step 3: Ephemeris Screening ---")

    # Configured Ephemeris Sieve Bounds (10 * Standard)
    # Standard: (2000, 5000, 2000)
    # Multiplier: 10
    # Threshold = max(20000, 50000, 20000) = 50000

    # We pass 'ephemerides' path to sieve
    data_dir = os.path.join(current_dir, "data")

    sieve_bounds = tuple(x * SCREENING_MULTIPLIER for x in ELLIPSOID_BOUNDS)
    threshold = max(sieve_bounds)
    logger.info(f"Using Ephemeris Threshold: {threshold / 1000.0} km (Bounds: {sieve_bounds})")

    # Filter 'secondaries' list passed to Sieve to ONLY be the ones from Step 1
    # sieveAlgorithm(..., secondariesID=[...])
    # Pass 'tles' as None or Minimal?
    # If ephemerides path is passed, sieve uses it.

    # Need list of IDs
    sec_ids = [int(s['NORAD_CAT_ID']) for s in secondaries_tle_list]

    # Sieve expects TLEs argument to have (primaries, secondaries) dicts if not loading from file?
    # Actually sieve logic:
    # if tles: use them.
    # elif ephemerides_files and secondariesID: construct dummy dicts.

    # So we pass tles=None, ephemerides=path, secondariesID=...

    results = sieveAlgorithm(
        primariesID=[base_id],
        daysOfSimulation=days,
        threshold=threshold,
        ellipsoid_bounds=sieve_bounds,
        verbose=False,
        tles=None,                      # Trigger ephemeris mode logic
        ephemerides=data_dir,
        secondariesID=sec_ids,
        start_date=start_date,
        screening_mode=True
    )

    out_dir = os.path.join(current_dir, "screening_ephemeris")
    os.makedirs(out_dir, exist_ok=True)
    filename = os.path.join(out_dir, f"screening_{base_id}_ephemeris.json")

    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"Ephemeris screening found {len(results)} candidates. Saved to {filename}")


def main():
    setup_orekit()
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=int, default=47699)
    parser.add_argument('--days', type=float, default=5.0)
    parser.add_argument(
        '--start-date',
        type=str,
        help="ISO format. Default: 2026-02-19T12:00:00+00:00"
    )
    args = parser.parse_args()

    start_dt = None
    if args.start_date:
        start_dt = datetime.fromisoformat(args.start_date)
    else:
        # Default start: 2026-02-19 12:00 UTC
        start_dt = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    logger.info(f"Simulation Start: {start_dt}")

    # Fetch TLEs (needed for Step 1)
    all_cat = requestTles()
    prim_data = next((x for x in all_cat if int(x['NORAD_CAT_ID']) == args.base), None)
    if not prim_data:
        logger.error(f"Base satellite {args.base} not found in TLEs.")
        raise Exception("Base satellite not found in TLEs.")

    # Filter TLEs
    # Rules:
    # 1. Not the primary itself
    # 2. NORAD ID <= 80000 (Analyst Sats)
    # 3. Not "TBA - TO BE ASSIGNED"

    secondaries_full = []
    skipped_count = 0

    for x in all_cat:
        try:
            nid = int(x['NORAD_CAT_ID'])

            if nid == args.base:
                continue

            if nid > 80000:
                skipped_count += 1
                continue

            secondaries_full.append(x)
        except Exception:
            continue

    logger.info(
        f"Loaded {len(secondaries_full)} candidates for screening "
        f"(Skipped {skipped_count} filtered objects)."
    )

    # 1. Large TLE Screening
    tle_results, _ = run_large_tle_screening(
        args.base,
        args.days,
        start_dt,
        prim_data,
        secondaries_full
    )

    if not tle_results:
        logger.info("No candidates found in large screening. Exiting.")
        raise Exception("No candidates found in large screening.")

    # 2. Download Ephem
    # Convert start_dt to AbsoluteDate for extend function context
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    utc = TimeScalesFactory.getUTC()
    abs_start = AbsoluteDate(
        start_dt.year, start_dt.month, start_dt.day,
        start_dt.hour, start_dt.minute, float(start_dt.second),
        utc
    )

    download_and_extend_ephemeris(args.base, tle_results, args.days, abs_start)

    # 3. Ephemeris Screening
    # We need the TLE objects corresponding to the results of step 1 to pass IDs?
    # Sieve in ephemeris mode takes 'secondariesID' list.

    candidate_ids = [int(r['secondary_id']) for r in tle_results]

    # Get objects just for metadata passing?
    # Actually sieve creates dummy objects if secondariesID passed.
    # But wait, we need 'secondary_tle_list' passed to run_ephemeris_screening?
    # I passed filtered list of TLE dicts.

    # Filter TLE list just to be safe/consistent?
    # Actually 'run_ephemeris_screening' takes 'secondaries_tle_list' just to extract IDs inside.
    # It constructs IDs list.
    # Let's pass the subset of TLEs matching candidates.

    cands_tles = [x for x in secondaries_full if int(x['NORAD_CAT_ID']) in candidate_ids]

    run_ephemeris_screening(
        args.base,
        args.days,
        start_dt,
        prim_data,  # Not used in ephem mode but kept for clear signature
        cands_tles
    )


if __name__ == "__main__":
    main()
