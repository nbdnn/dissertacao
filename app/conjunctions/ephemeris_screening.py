import sys
import argparse
import time
import json
import logging
import os
import numpy as np

if __name__ == '__main__' and __package__ is None:
    # Hack to allow running this script directly while keeping relative imports
    file_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    __package__ = "app.conjunctions"

from ..orekit_config import setup_orekit
from .filter_pre import filterPre
from .conjunction_analysis import conjunctionAnalysis
from .config import ELLIPSOID_BOUNDS

try:
    from cenario2.parse_ephemerides import parse_stk_ephemeris
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), "../../../cenario2"))
    from cenario2.parse_ephemerides import parse_stk_ephemeris

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# --- Helper Functions for Ephemeris Propagation ---

def create_ephemeris_propagator(parsed_data, frame):
    """Creates an Orekit Ephemeris propagator from parsed STK data."""
    from org.orekit.propagation.analytical import Ephemeris
    from org.orekit.utils import PVCoordinates, Constants
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.propagation import SpacecraftState
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from java.util import ArrayList

    states_list = ArrayList()
    mu = Constants.IERS2010_EARTH_MU
    
    for date, pos, vel, _ in parsed_data:
        pv = PVCoordinates(
            Vector3D(float(pos[0]), float(pos[1]), float(pos[2])),
            Vector3D(float(vel[0]), float(vel[1]), float(vel[2]))
        )
        orbit = CartesianOrbit(pv, frame, date, mu)
        state = SpacecraftState(orbit)
        states_list.add(state)
        
    return Ephemeris(states_list, 8)

def get_time_grid(start_date, end_date, step=180.0):
    """Generates a list of AbsoluteDates from start to end with step."""
    grid = []
    curr = start_date
    while curr.compareTo(end_date) <= 0:
        grid.append(curr)
        curr = curr.shiftedBy(float(step))
    return grid

def sample_propagator(propagator, dates, frame):
    """Samples the propagator at given dates."""
    samples = []
    for date in dates:
        pv = propagator.getPVCoordinates(date, frame)
        p = pv.getPosition()
        v = pv.getVelocity()
        p_arr = np.array([p.getX(), p.getY(), p.getZ()])
        v_arr = np.array([v.getX(), v.getY(), v.getZ()])
        samples.append((date, p_arr, v_arr, None))
    return samples

def get_obj_type(name):
    if not name: return "PAYLOAD"
    n = name.upper()
    if 'DEB' in n: return 'DEBRIS'
    if 'R/B' in n: return 'ROCKET BODY'
    return 'PAYLOAD'

# --- Main Logic ---

def main():
    parser = argparse.ArgumentParser(
        description="Screening refinado utilizando efemérides (STK)."
    )
    parser.add_argument('--base', type=int, required=True, help="NORAD ID do satélite base")
    parser.add_argument('--input', type=str, required=True, help="Caminho para arquivo JSON de screening inicial")

    args = parser.parse_args()

    logger.info("Inicializando Orekit...")
    setup_orekit()

    from org.orekit.frames import FramesFactory
    frame = FramesFactory.getEME2000()

    # Load candidates from screening file
    logger.info(f"Carregando candidatos de: {args.input}")
    if not os.path.exists(args.input):
        logger.error(f"Arquivo de input não encontrado: {args.input}")
        sys.exit(1)

    with open(args.input, 'r') as f:
        candidates = json.load(f)

    # Organize candidates by dictionary to remove duplicates if necessary
    candidates_dict = {c['secondary_id']: c for c in candidates}
    logger.info(f"Processando {len(candidates_dict)} candidatos únicos.")

    # Paths setup
    # Assuming standard structure: project_root/cenario2/data for ephemerides
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ephemeris_dir = os.path.join(project_root, 'cenario2', 'data')

    # Load Primary Ephemeris
    primary_file = os.path.join(ephemeris_dir, f'SP_{args.base}_extended.e')
    if not os.path.exists(primary_file):
        logger.error(f"Efeméride estendida do primário {args.base} não encontrada em {primary_file}")
        sys.exit(1)
        
    logger.info(f"Lendo efeméride do primário: {primary_file}")
    primary_data_raw = parse_stk_ephemeris(primary_file)
    # Handle single logic
    primary_data = primary_data_raw.get(args.base) or primary_data_raw.get(list(primary_data_raw.keys())[0])
    
    primary_prop = create_ephemeris_propagator(primary_data, frame)
    p_start = primary_data[0][0]
    p_end = primary_data[-1][0]
    
    logger.info(f"Intervalo primário: {p_start} até {p_end}")

    # Analysis Configuration
    # Uses 10x bounds for high fidelity filtering
    analysis_ellipsoid = [b * 10.0 for b in ELLIPSOID_BOUNDS]
    sieve_threshold = max(analysis_ellipsoid)
    
    logger.info(f"Ellipsoid de Análise (10x): {analysis_ellipsoid}")
    logger.info(f"Threshold Sieve: {sieve_threshold} m")
    
    conjunctions = []
    seen_conjunctions = [] # To avoid duplicates close in time
    
    start_time = time.time()

    for sec_id, cand_info in candidates_dict.items():
        sec_file = os.path.join(ephemeris_dir, f'SP_{sec_id}_extended.e')
        if not os.path.exists(sec_file):
            logger.warning(f"Efeméride estendida para secundário {sec_id} ausente. Pulando.")
            continue
            
        try:
            sec_data_raw = parse_stk_ephemeris(sec_file)
            sec_data = sec_data_raw.get(sec_id) or sec_data_raw.get(list(sec_data_raw.keys())[0])
        except Exception as e:
            logger.error(f"Erro ao parsear {sec_file}: {e}")
            continue
            
        sec_prop = create_ephemeris_propagator(sec_data, frame)
        s_start = sec_data[0][0]
        s_end = sec_data[-1][0]
        
        # Check intersection
        intersect_start = p_start if p_start.compareTo(s_start) > 0 else s_start
        intersect_end = p_end if p_end.compareTo(s_end) < 0 else s_end
        
        if intersect_start.compareTo(intersect_end) >= 0:
            # logger.debug(f"Sem interseção de tempo para {sec_id}.")
            continue
            
        # 1. Broad Phase: FilterPre (Sieve)
        # 60s step for quick checking
        h_step = 60.0
        grid_dates = get_time_grid(intersect_start, intersect_end, h_step)
        if not grid_dates:
            continue
            
        p_samples = sample_propagator(primary_prop, grid_dates, frame)
        s_samples = sample_propagator(sec_prop, grid_dates, frame)
        
        prim_dict = {
            "NORAD_CAT_ID": args.base,
            "OBJECT_NAME": cand_info.get("primary_name", str(args.base)),
            "OBJECT_TYPE": get_obj_type(cand_info.get("primary_name", "")),
        }
        sec_dict = {
            "NORAD_CAT_ID": sec_id,
            "OBJECT_NAME": cand_info.get("secondary_name", str(sec_id)),
            "OBJECT_TYPE": get_obj_type(cand_info.get("secondary_name", "")),
        }
        
        t_offsets, _ = filterPre(
            p_samples, s_samples,
            primary=prim_dict, secondary=sec_dict,
            h=h_step, rc=sieve_threshold, verbose=False
        )
        
        if t_offsets:
            logger.info(f"Candidato {sec_id}: {len(t_offsets)} pontos suspeitos em filtro grosso.")
            
            # 2. Narrow Phase: Minimization & Conjunction Analysis
            for t_off in t_offsets:
                detection_time = grid_dates[0].shiftedBy(float(t_off))
                
                # Minimization in +/- 60s window
                min_dist = float('inf')
                min_date = detection_time
                
                check_start = detection_time.shiftedBy(-60.0)
                check_end = detection_time.shiftedBy(60.0)
                curr_check = check_start
                
                # Check every 1 second
                while curr_check.compareTo(check_end) <= 0:
                    pv_p = primary_prop.getPVCoordinates(curr_check, frame)
                    pv_s = sec_prop.getPVCoordinates(curr_check, frame)
                    dist = pv_p.getPosition().distance(pv_s.getPosition())
                    
                    if dist < min_dist:
                        min_dist = dist
                        min_date = curr_check
                    
                    curr_check = curr_check.shiftedBy(1.0)
                
                if min_dist < sieve_threshold:
                    # Final check with full conjunction analysis (impact probability etc if implemented)
                    p_pv_final = primary_prop.getPVCoordinates(min_date, frame)
                    s_pv_final = sec_prop.getPVCoordinates(min_date, frame)
                    
                    p_state_final = (
                        min_date, 
                        np.array([p_pv_final.getPosition().getX(), p_pv_final.getPosition().getY(), p_pv_final.getPosition().getZ()]), 
                        np.array([p_pv_final.getVelocity().getX(), p_pv_final.getVelocity().getY(), p_pv_final.getVelocity().getZ()]), 
                        None
                    )
                    
                    s_state_final = (
                        min_date, 
                        np.array([s_pv_final.getPosition().getX(), s_pv_final.getPosition().getY(), s_pv_final.getPosition().getZ()]), 
                        np.array([s_pv_final.getVelocity().getX(), s_pv_final.getVelocity().getY(), s_pv_final.getVelocity().getZ()]), 
                        None
                    )

                    res = conjunctionAnalysis(
                        primary=prim_dict,
                        secondary=sec_dict,
                        tcaTime=min_date,
                        verbose=False,
                        ellipsoid_bounds=tuple(analysis_ellipsoid),
                        primary_state_vector=p_state_final,
                        secondary_state_vector=s_state_final
                    )
                    
                    # Store if violation or just close approach
                    # If is_violated is in result or distance is small
                    if res.get('is_violated', False) or res.get('min_distance_m', float('inf')) < sieve_threshold:
                         
                         # Check strict duplicates (same secondary, close time)
                         is_dup = False
                         for seen_sec_id, seen_date in seen_conjunctions:
                             if seen_sec_id == sec_id:
                                 if abs(min_date.durationFrom(seen_date)) < 120.0:
                                     is_dup = True
                                     break
                         
                         if not is_dup:
                             res['primary_id'] = args.base
                             res['secondary_id'] = sec_id
                             res['tca_utc'] = min_date.toString()
                             conjunctions.append(res)
                             seen_conjunctions.append((sec_id, min_date))
                             logger.info(f"  -> Conjunção Confirmada: {sec_id} em {res['tca_utc']} | Dist: {res['min_distance_m']:.2f}m")

    end_time = time.time()
    duration = end_time - start_time

    logger.info("=" * 60)
    logger.info(f"Screening de Efemérides finalizado em {duration:.2f} segundos.")
    logger.info(f"Eventos encontrados: {len(conjunctions)}")
    logger.info("=" * 60)

    # Save results
    screenings_dir = os.path.join(project_root, "screenings")
    os.makedirs(screenings_dir, exist_ok=True)

    output_filename = os.path.join(screenings_dir, f"ephemeris_screening_{args.base}_{int(time.time())}.json")
    with open(output_filename, 'w') as f:
        json.dump(conjunctions, f, indent=2)
    logger.info(f"Resultados salvos em: {output_filename}")


if __name__ == '__main__':
    main()
