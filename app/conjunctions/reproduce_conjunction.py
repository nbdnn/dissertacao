import sys
import argparse
import json
import logging
import os
from datetime import timezone

if __name__ == '__main__' and __package__ is None:
    # Hack to allow running this script directly while keeping relative imports
    file_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    __package__ = "app.conjunctions"

from ..orekit_config import setup_orekit
from ..utils import orekit_date_to_datetime
from .sieve import sieveAlgorithm

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_tles_from_json(filepath):
    logger.info(f"Loading TLEs from {filepath}...")

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)

        if len(data) < 2:
            logger.error(f"JSON file must contain at least 2 objects. Found: {len(data)}")
            sys.exit(1)

        result = []
        # Take the first two objects
        for entry in data[:2]:
            nid = str(entry.get("NORAD_CAT_ID"))
            # Convert numeric fields needed by the algorithm
            entry["NORAD_CAT_ID"] = int(nid)
            if "APOAPSIS" in entry:
                entry["APOAPSIS"] = float(entry["APOAPSIS"])
            if "PERIAPSIS" in entry:
                entry["PERIAPSIS"] = float(entry["PERIAPSIS"])
            if "ECCENTRICITY" in entry:
                entry["ECCENTRICITY"] = float(entry["ECCENTRICITY"])
            result.append(entry)

        return result[0], result[1]

    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        sys.exit(1)


def main():
    setup_orekit()

    parser = argparse.ArgumentParser(description="Reproduce conjunction analysis for two objects.")
    # parser.add_argument("primary_id", type=int, help="NORAD ID for Primary")
    # parser.add_argument("secondary_id", type=int, help="NORAD ID for Secondary")
    # parser.add_argument("tca", help="TCA Date") # Removed as requested
    parser.add_argument("--json-file", default="specific_tles.json", help="Path to TLE JSON file")
    parser.add_argument("--days", type=float, default=7.0, help="Simulation duration in days")
    parser.add_argument(
        '--threshold', type=float, default=5000.0, help="Distância de alerta (metros)"
    )

    args = parser.parse_args()

    primary, secondary = load_tles_from_json(args.json_file)

    # Use primary TLE epoch as simulation start
    # type: ignore[reportMissingImports]
    from org.orekit.propagation.analytical.tle import TLE  # type: ignore

    tle_p = TLE(primary["TLE_LINE1"], primary["TLE_LINE2"])
    simulation_start = orekit_date_to_datetime(tle_p.getDate())
    if simulation_start.tzinfo is None:
        simulation_start = simulation_start.replace(tzinfo=timezone.utc)

    primaries = [primary]
    secondaries = [secondary]

    logger.info(
        f"Starting reproduction analysis for {primary['NORAD_CAT_ID']} vs "
        f"{secondary['NORAD_CAT_ID']}"
    )
    logger.info(f"Start Date: {simulation_start}")

    # Run Sieve
    # Note: We pass start_date and tles to override default behavior
    sieveAlgorithm(
        primariesID=[primary["NORAD_CAT_ID"]],
        daysOfSimulation=args.days,
        threshold=args.threshold,
        verbose=False,
        verboseConjAnalysis=True,
        start_date=simulation_start,
        tles=(primaries, secondaries)
    )


if __name__ == "__main__":
    main()
