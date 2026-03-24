import os
import glob
import json
import sys
import requests
import logging
import argparse
from datetime import datetime

# Add project root to path
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_latest_screening(base_id, search_dir):
    pattern = os.path.join(search_dir, f"screening_{base_id}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    return latest_file


def download_ephemeris(url, noradId, output_dir="."):
    local_filename = os.path.join(output_dir, f"SP_{noradId}.e")

    if os.path.exists(local_filename):
        print(
            f"\rEphemeris file {local_filename} already exists. Skipping download.",
            end="",
            flush=True
        )
        return local_filename

    print(f"Downloading ephemeris for {noradId} from {url}...", flush=True)
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return local_filename
    except Exception as e:
        print(f"Failed to download ephemeris for {noradId}: {e}")
        raise e


def request_sat_catalog(output_dir="."):
    catalog_file = os.path.join(output_dir, "SatellitesSpaceBook.json")

    if os.path.exists(catalog_file):
        logger.info(f"Using cached catalog: {catalog_file}")
        with open(catalog_file, "r") as fid:
            return json.load(fid)

    logger.info("Downloading catalog details from spacebook...")
    uri = "https://spacebook.com/api/entity/satcat/details"

    try:
        s = requests.Session()
        resp = s.get(uri, timeout=30)
        resp.raise_for_status()

        with open(catalog_file, "w+") as fid:
            fid.write(resp.text)

        return json.loads(resp.text)
    except Exception as e:
        logger.error(f"Failed to fetch satellite catalog: {e}")
        return []


def get_spacebook_id(norad_id, catalog):
    for satellite in catalog:
        if str(satellite.get("noradId")) == str(norad_id):
            return satellite.get("id")
    return None


def list_secondaries(base_id):
    screenings_dir = os.path.join(project_root, "screenings")

    print(f"Searching for screening files for base ID {base_id} in {screenings_dir}...")
    screening_file = find_latest_screening(base_id, screenings_dir)

    if not screening_file:
        print(f"No screening file found for base ID {base_id}.")
        return set()

    print(f"Found latest screening file: {os.path.basename(screening_file)}")

    with open(screening_file, 'r') as f:
        candidates = json.load(f)

    if not candidates:
        print("Screening file is empty or invalid.")
        return set()

    unique_secondaries = set()

    for c in candidates:
        sec_id = c.get('secondary_id')
        sec_name = str(c.get('secondary_name', 'Unknown'))
        unique_secondaries.add((sec_id, sec_name))

    return unique_secondaries


def process_satellite(base_id, catalog, data_dir):
    print(f"\n{'=' * 20} Processing Base Satellite: {base_id} {'=' * 20}")

    # List objects
    secondaries = list_secondaries(base_id)
    if not secondaries:
        print(f"Skipping {base_id} due to missing or empty screening file.")
        return

    print("-" * 50)
    print(f"Unique secondary objects: {len(secondaries)}")
    for sid, sname in sorted(list(secondaries), key=lambda x: int(x[0])):
        print(f" - {sid}: {sname}")

    print("-" * 50)
    print("Starting Download Process...")

    # 2. Download Primary
    print(f"\nProcessing Primary {base_id}...")
    sb_id = get_spacebook_id(base_id, catalog)
    if sb_id:
        url = f"https://spacebook.com/api/entity/synthetic-covariance/{sb_id}"
        file_path = download_ephemeris(url, base_id, data_dir)
        if file_path:
            print(f" ✅ Downloaded/Found: {os.path.basename(file_path)}")
    else:
        print(f" ❌ Primary {base_id} not found in catalog.")

    # 3. Download Secondaries
    print(f"\nProcessing {len(secondaries)} Secondaries...")

    count_ok = 0
    count_fail = 0
    count_nocat = 0

    for sid, sname in sorted(list(secondaries), key=lambda x: int(x[0])):
        sb_id = get_spacebook_id(sid, catalog)
        if sb_id:
            url = f"https://spacebook.com/api/entity/synthetic-covariance/{sb_id}"
            file_path = download_ephemeris(url, sid, data_dir)
            if file_path:
                count_ok += 1
                # print(f" ✅ {sid}: OK")
            else:
                count_fail += 1
                print(f" ❌ {sid}: Download Failed")
        else:
            count_nocat += 1
            print(f" ⚠️ {sid}: Not in Spacebook Catalog")

    print("-" * 50)
    print(f"Summary for {base_id}: OK={count_ok}, Failed={count_fail}, NotInCatalog={count_nocat}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download ephemerides for satellites and their screening secondaries."
    )
    parser.add_argument(
        "--norad_id",
        type=str,
        nargs="+",
        required=True,
        help="List of satellite NORAD IDs to process (space or comma separated)"
    )

    args = parser.parse_args()

    # Parse and flatten NORAD IDs (allow "123,456" and "123 456")
    norad_ids = []
    for item in args.norad_id:
        for sub_item in item.split(','):
            if sub_item.strip():
                norad_ids.append(int(sub_item.strip()))

    # Time params
    now = datetime.utcnow()
    year = now.year
    yday = now.timetuple().tm_yday
    hour = now.hour

    # Setup Data Directory
    # Using existing cenario2 folder structure
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    print("-" * 50)
    print(f"Starting Process for {len(norad_ids)} satellites...")

    # 1. Catalog
    catalog = request_sat_catalog(year, yday, hour, output_dir=data_dir)

    if not catalog:
        print("Failed to get catalog.")
        sys.exit(1)

    for sat_id in norad_ids:
        process_satellite(sat_id, catalog, data_dir)
