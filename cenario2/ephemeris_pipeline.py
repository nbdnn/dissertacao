import sys
import os
import glob
import json
import logging
import argparse
import time
import subprocess
import numpy as np

# Add project root to path
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# App Imports
from cenario2.parse_ephemerides import (
    parse_stk_ephemeris,
    create_ephemeris_propagator,
    get_time_grid
)
from app.conjunctions.bisection import bisectionMethod
from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.config import ELLIPSOID_BOUNDS
from app.orekit_config import setup_orekit

# Configure Logging
log_file = os.path.join(os.path.dirname(__file__), "ephemeris_pipeline.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def find_latest_screening_extended(base_id, results_dir):
    """Finds the most recent screening EXTENDED file for the given base ID."""
    pattern = os.path.join(results_dir, f"screening_extended_{base_id}.json")
    if os.path.exists(pattern):
        return pattern
    return None # Exact match required per screening tool output

def find_latest_cenario1_analysis(base_id, results_dir):
    pattern = os.path.join(results_dir, f"analysis_{base_id}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getctime)

def run_screening_script(base_id, cenario1_input):
    logger.info(f"Screening extended file not found for {base_id}. Running ephemeris_screening.py...")
    script_path = os.path.join(os.path.dirname(__file__), "ephemeris_screening.py")
    
    cmd = [
        sys.executable, script_path,
        "--primary", str(base_id),
        "--input", cenario1_input
    ]
    logger.info(f"Command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False, check=True)
    if result.returncode != 0:
        logger.error("Screening script failed.")
        sys.exit(1)

def load_extended_ephemeris_data(norad_id):
    """Loads and parses the EXTENDED .e file for a specific satellite."""
    file_path = os.path.join(project_root, "cenario2", "data", f"SP_{norad_id}_extended.e")
    
    if not os.path.exists(file_path):
        logger.warning(f"Extended Ephemeris file not found: {file_path}")
        return None
    
    try:
        parsed_dict = parse_stk_ephemeris(file_path)
        # Handle dict return
        if norad_id in parsed_dict:
            return parsed_dict[norad_id]
        if len(parsed_dict) > 0:
            return list(parsed_dict.values())[0]
        return None
    except Exception as e:
        logger.error(f"Failed to parse {file_path}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Ephemeris Pipeline (Cenario 2 Analysis)")
    parser.add_argument('--base', type=int, default=47699, help="NORAD ID of Primary Satellite")
    parser.add_argument(
        '--ellipsoid', nargs=3, type=float, default=list(ELLIPSOID_BOUNDS),
        help=f"Semi-eixos do Elipsóide (R_U, R_V, R_W) default {ELLIPSOID_BOUNDS}"
    )
    
    args = parser.parse_args()
    
    setup_orekit()
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    from org.orekit.frames import FramesFactory
    
    utc = TimeScalesFactory.getUTC()
    frame = FramesFactory.getEME2000()

    # 1. Locate Screening File
    cenario2_results_dir = os.path.join(project_root, "cenario2", "results")
    os.makedirs(cenario2_results_dir, exist_ok=True)
    
    screening_file = find_latest_screening_extended(args.base, cenario2_results_dir)
    
    if not screening_file:
        logger.warning(f"Screening file for {args.base} missing. Attempting to generate...")
        
        # Need Cenario 1 input
        cenario1_results_dir = os.path.join(project_root, "cenario1", "analysis_results")
        cenario1_file = find_latest_cenario1_analysis(args.base, cenario1_results_dir)
        
        if not cenario1_file:
            logger.error(f"Cannot generate screening: Cenario 1 analysis file for {args.base} not found.")
            sys.exit(1)
            
        run_screening_script(args.base, cenario1_file)
        
        # Check again
        screening_file = find_latest_screening_extended(args.base, cenario2_results_dir)
        if not screening_file:
            logger.error("Screening file generation failed or file not found.")
            sys.exit(1)
            
    logger.info(f"Using Screening File: {screening_file}")
    
    with open(screening_file, 'r') as f:
        candidates = json.load(f)
        
    if not candidates:
        logger.warning("No candidates in screening file.")
        sys.exit(0)
        
    # 2. Prepare Primary
    primary_id = args.base
    logger.info(f"Loading Primary Ephemeris {primary_id}...")
    primary_data = load_extended_ephemeris_data(primary_id)
    if not primary_data:
        logger.error("Primary ephemeris missing.")
        sys.exit(1)
        
    primary_prop = create_ephemeris_propagator(primary_data, frame)

    # 3. Process Candidates
    results = []
    
    logger.info(f"Processing {len(candidates)} candidates...")
    
    print() # Newline for progress
    for i, cand in enumerate(candidates):
        sec_id = int(cand['secondary_id'])
        sec_name = cand.get('secondary_name', f'Unknown-{sec_id}')
        
        print(f"\rAnalyzing candidate {i+1}/{len(candidates)}: {sec_name} ({sec_id})", end="", flush=True)
        # logger.info(f"Analyzing candidate {i+1}/{len(candidates)}: {sec_name} ({sec_id})")
        
        # Load Secondary Ephemeris
        sec_data = load_extended_ephemeris_data(sec_id)
        if not sec_data:
            logger.warning(f"Skipping {sec_id}: Ephemeris missing.")
            continue
            
        sec_prop = create_ephemeris_propagator(sec_data, frame)
        
        # Determine TCA from screening and verify
        # Screening TCA is reliable from our previous step, but let's confirm geometry
        try:
            tca_str = cand['tca_utc'].replace("Z", "") # Clean ISO
            tca_date = AbsoluteDate(tca_str, utc)
        except Exception as e:
            logger.error(f"Bad TCA format: {e}")
            continue
            
        # Refine TCA
        min_dist = float('inf')
        refined_tca = tca_date
        
        # Scan +/- 5 seconds with 0.01 step
        curr = tca_date.shiftedBy(-5.0)
        end_check = tca_date.shiftedBy(5.0)
        step = 0.5 
        
        while curr.compareTo(end_check) <= 0:
            pv_p = primary_prop.getPVCoordinates(curr, frame)
            pv_s = sec_prop.getPVCoordinates(curr, frame)
            d = pv_p.getPosition().distance(pv_s.getPosition())
            if d < min_dist:
                min_dist = d
                refined_tca = curr
            curr = curr.shiftedBy(step)
            
        # Final refinement step 0.01
        curr = refined_tca.shiftedBy(-0.5)
        end_check = refined_tca.shiftedBy(0.5)
        step = 0.01
        while curr.compareTo(end_check) <= 0:
            pv_p = primary_prop.getPVCoordinates(curr, frame)
            pv_s = sec_prop.getPVCoordinates(curr, frame)
            d = pv_p.getPosition().distance(pv_s.getPosition())
            if d < min_dist:
                min_dist = d
                refined_tca = curr
            curr = curr.shiftedBy(step)
            
        # Prepare Analysis Inputs
        p_pv = primary_prop.getPVCoordinates(refined_tca, frame)
        s_pv = sec_prop.getPVCoordinates(refined_tca, frame)
        
        # Find covariance
        def find_cov(data, target):
            min_dt = 1e9
            best_cov = None
            # Simple linear check - extended files are 60s step
            # Could optimize
            for row in data:
                 dt = abs(row[0].durationFrom(target))
                 if dt < min_dt:
                     min_dt = dt
                     best_cov = row[3]
                 if dt > 3600 and min_dt < 3600: break
            return best_cov

        p_cov = find_cov(primary_data, refined_tca)
        s_cov = find_cov(sec_data, refined_tca)
        
        p_vec = (refined_tca, 
                 np.array([p_pv.getPosition().getX(), p_pv.getPosition().getY(), p_pv.getPosition().getZ()]),
                 np.array([p_pv.getVelocity().getX(), p_pv.getVelocity().getY(), p_pv.getVelocity().getZ()]),
                 p_cov)
                 
        s_vec = (refined_tca, 
                 np.array([s_pv.getPosition().getX(), s_pv.getPosition().getY(), s_pv.getPosition().getZ()]),
                 np.array([s_pv.getVelocity().getX(), s_pv.getVelocity().getY(), s_pv.getVelocity().getZ()]),
                 s_cov)

        # Mock dicts for metadata
        def get_type(name):
             if not name: return "DEBRIS"
             if 'DEB' in name.upper(): return "DEBRIS"
             if 'R/B' in name.upper(): return "ROCKET BODY"
             return "PAYLOAD"

        prim_dict = {
            "NORAD_CAT_ID": primary_id,
            "OBJECT_NAME": "PRIMARY",
            "OBJECT_TYPE": "PAYLOAD",
            "TLE_LINE1": cand.get('primary_tle_line1', ''),
            "TLE_LINE2": cand.get('primary_tle_line2', '')
        }
        sec_dict = {
            "NORAD_CAT_ID": sec_id,
            "OBJECT_NAME": sec_name,
            "OBJECT_TYPE": get_type(sec_name),
            "TLE_LINE1": cand.get('secondary_tle_line1', ''),
            "TLE_LINE2": cand.get('secondary_tle_line2', '')
        }
        
        analysis_res = conjunctionAnalysis(
            primary=prim_dict,
            secondary=sec_dict,
            tcaTime=refined_tca,
            verbose=False,
            ellipsoid_bounds=tuple(args.ellipsoid),
            primary_state_vector=p_vec,
            secondary_state_vector=s_vec
        )
        
        if analysis_res['is_violated']:
            del analysis_res['is_violated']
            results.append(analysis_res)
    
    print() # Close progress bar
            
    # 4. Save Final Results
    output_dir = os.path.join(project_root, "cenario2", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = int(time.time())
    output_file = os.path.join(output_dir, f"analysis_{args.base}_{timestamp}.json")
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
        
    logger.info("="*60)
    logger.info(f"Analysis Complete. {len(results)} violations found.")
    logger.info(f"Results saved to: {output_file}")
    logger.info("="*60)
    
    # Print violations
    for c in results:
         print(f"⚠️ VIOLATION: {c['secondary_name']} ({c['secondary_id']})")
         print(f"   TCA: {c['tca_utc']} | Dist: {c['min_distance_m']:.2f}m")

if __name__ == '__main__':
    main()
