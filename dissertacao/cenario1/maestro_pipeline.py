import os
import glob
import re
import subprocess
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    # Determine project root relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)  # UP one level

    screenings_dir = os.path.join(project_root, "screenings")
    pipeline_script = os.path.join(script_dir, "conjunctions_pipeline.py")

    if not os.path.exists(screenings_dir):
        logger.error(f"Directory not found: {screenings_dir}")
        return

    # Find screening files
    # Pattern: screening_{base_id}_{timestamp}.json
    pattern_glob = os.path.join(screenings_dir, "screening_*.json")
    screening_files = glob.glob(pattern_glob)

    if not screening_files:
        logger.warning(f"No screening files found in {screenings_dir}")
        return

    logger.info(f"Found {len(screening_files)} screening files.")

    # Regex to extract base_id
    # Filename format expected: screening_55045_1738520000.json
    filename_regex = re.compile(r"screening_(\d+)_")

    processed_ids = set()

    for screening_file in sorted(screening_files):
        filename = os.path.basename(screening_file)

        match = filename_regex.search(filename)
        if not match:
            logger.warning(f"Could not extract base_id from {filename}. Skipping.")
            continue

        base_id = match.group(1)

        if base_id in processed_ids:
            logger.info(
                f"Skipping {filename} (Base ID {base_id} already scheduled for processing)."
            )
            continue

        processed_ids.add(base_id)

        logger.info(f"Processing Base ID: {base_id} (from {filename})")

        # Build command: uv run cenario1/conjunctions_pipeline.py --base <base_id> --days 7.0
        cmd = [
            "uv", "run", pipeline_script,
            "--base", base_id,
            "--days", "7.0"
        ]

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Successfully finished pipeline for Base ID {base_id}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Pipeline failed for Base ID {base_id}: {e}")

        logger.info("-" * 40)


if __name__ == "__main__":
    main()
