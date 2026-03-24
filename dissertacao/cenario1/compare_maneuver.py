import os
import sys
import glob
import json
import argparse
import numpy as np

# Instanciar caminhos absolutos para o projeto inteiro
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Orekit setup e imports
from app.orekit_config import setup_orekit
setup_orekit()

from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
from org.orekit.orbits import KeplerianOrbit, PositionAngleType  # type: ignore
from org.orekit.frames import FramesFactory  # type: ignore
from org.orekit.propagation import SpacecraftState  # type: ignore
from org.orekit.propagation.conversion.osc2mean import FixedPointConverter # type: ignore
from org.hipparchus.geometry.euclidean.threed import Vector3D  # type: ignore
from org.orekit.utils import Constants  # type: ignore

MU = Constants.WGS84_EARTH_MU / 1e9  # km^3/s^2

# Reaproveitar a função de equações de Gauss do optimize_maneuver
# Como não queremos importar todo o PyMoo no escopo principal as vezes,
# vamos apenas re-escrever ou importar a função
from cenario1.optimize_maneuver import apply_gauss_variational_equations
from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.config import GA_ELLIPSOID_BOUNDS
from app.conjunctions.bisection import bisectionMethod

def main():
    parser = argparse.ArgumentParser(description="Compara conjunções antes e depois da manobra.")
    parser.add_argument('--base', type=int, default=65774, help="ID do Satélite Primário")
    parser.add_argument('--seed', type=int, default=1, help="Qual arquivo de seed verificar")
    args = parser.parse_args()
    
    base_id = args.base
    seed_idx = args.seed
    
    # 1. Carregar Original Analysis Results
    analysis_dir = os.path.join(os.path.dirname(__file__), "analysis_results")
    pattern_analysis = os.path.join(analysis_dir, f"analysis_{base_id}_*.json")
    files_analysis = glob.glob(pattern_analysis)
    
    if not files_analysis:
        print(f"Erro: Nenhum arquivo de analysis para {base_id} encontrado.")
        return
        
    latest_analysis = max(files_analysis, key=os.path.getctime)
    with open(latest_analysis, 'r') as f:
        original_conjunctions = json.load(f)
        
    print(f"Carregado Original Analysis: {os.path.basename(latest_analysis)} ({len(original_conjunctions)} ameaças)")

    # 1.5 Carregar o Screening Completo (onde estão todos os TLEs e candidatos da triagem)
    screening_dir = os.path.join(project_root, "screenings")
    pattern_screening = os.path.join(screening_dir, f"screening_{base_id}_*.json")
    files_screening = glob.glob(pattern_screening)
    
    if files_screening:
        latest_screening = max(files_screening, key=os.path.getctime)
        with open(latest_screening, 'r') as f:
            full_screening = json.load(f)
        print(f"Carregado Arquivo de Screening de Triagem Total: {os.path.basename(latest_screening)} ({len(full_screening)} candidatos)")
    else:
        full_screening = []
        print(f"Arquivo de Screening completo não encontrado em {screening_dir} para {base_id}")

    # 2. Carregar Solução GA
    solution_file = os.path.join(os.path.dirname(__file__), f"{base_id}_seed_{seed_idx}_solution.json")
    if not os.path.exists(solution_file):
        print(f"Erro: Arquivo de solução não encontrado -> {solution_file}")
        
        # Fallback para o arquivo batch optimization
        pattern_batch = os.path.join(os.path.dirname(__file__), f"{base_id}_optimization_solutions_*.json")
        batch_files = glob.glob(pattern_batch)
        if batch_files:
            latest_batch = max(batch_files, key=os.path.getctime)
            print(f"Buscando seed {seed_idx} no batch: {os.path.basename(latest_batch)}")
            with open(latest_batch, 'r') as f:
                sols = json.load(f)
                sol_data = next((s for s in sols if s['seed'] == seed_idx), None)
                if not sol_data:
                    print(f"Seed {seed_idx} não encontrada no batch.")
                    return
        else:
            return
    else:
        with open(solution_file, 'r') as f:
            sol_data = json.load(f)
            
    dt_maneuver = sol_data["dt_maneuver_s"]
    delta_v = sol_data["delta_v_ms"]
    
    print(f"Carregada Solução Seed {seed_idx}:")
    print(f"  -> dt_maneuver: {dt_maneuver / 3600.0:.2f} h")
    print(f"  -> delta_v:     {delta_v:.4f} m/s")
    print("-" * 60)
    
    # Vamos armazenar os TLEs do primário encontrados no arquivo de screening original das conjuncoes
    if not original_conjunctions:
        return
        
    p_tle1 = original_conjunctions[0]["primary_tle_line1"]
    p_tle2 = original_conjunctions[0]["primary_tle_line2"]
    
    utc = TimeScalesFactory.getUTC()
    inertialFrame = FramesFactory.getEME2000()
    
    tle_p = TLE(p_tle1, p_tle2)
    prop_p_orig = TLEPropagator.selectExtrapolator(tle_p)

    # Identificar o t_maneuver referenciado pelo TCA do PRImeiro candidato da lista do otimizador
    # O PyMoo usa o primeiro TCA do screening (que é cronologicamente o primeiro encontro) e
    # adiciona dt_maneuver para encontrar a Data da Manobra
    # Vamos procurar o TCA mais antigo na lista de analysis (foco de Opt. A)
    min_tca_date = min([AbsoluteDate(c["tca_utc"].replace("Z", ""), utc) for c in original_conjunctions])
    t_maneuver_date = min_tca_date.shiftedBy(float(dt_maneuver))
    
    # Propagar P até t_maneuver para aplicar a manobra
    pv_maneuver = prop_p_orig.getPVCoordinates(t_maneuver_date, inertialFrame)
    keplerian_orbit = KeplerianOrbit(pv_maneuver, inertialFrame, t_maneuver_date, Constants.WGS84_EARTH_MU)
    
    a = keplerian_orbit.getA() / 1000.0  
    e = keplerian_orbit.getE()
    i = keplerian_orbit.getI()
    raan = keplerian_orbit.getRightAscensionOfAscendingNode()
    arg_p = keplerian_orbit.getPerigeeArgument()
    f = keplerian_orbit.getTrueAnomaly()
    
    new_a, new_e, new_i, new_raan, new_arg_p, new_f = apply_gauss_variational_equations(
        a, e, i, raan, arg_p, f, delta_v
    )
    
    virtual_orbit = KeplerianOrbit(
        new_a * 1000.0, new_e, new_i, new_arg_p, new_raan, new_f,
        PositionAngleType.TRUE, inertialFrame, t_maneuver_date, Constants.WGS84_EARTH_MU
    )
    virtual_state = SpacecraftState(virtual_orbit)
    converter = FixedPointConverter()
    virtual_tle = TLE.stateToTLE(virtual_state, tle_p, converter)
    virtual_propagator = TLEPropagator.selectExtrapolator(virtual_tle)

    print(f"Manobra APLICADA em: {t_maneuver_date.toString()}")
    print(f"Propagador Virtual Inicializado!")
    print("=" * 100)
    print("=== AMEAÇAS REGISTRADAS NO PIPELINE DE ANALYSIS ===")
    print("=" * 100)
    
    # Processar apenas conjunctions da lista Analysis
    process_list(original_conjunctions, t_maneuver_date, utc, virtual_propagator, inertialFrame, virtual_tle, base_id, tle_p, p_tle1, p_tle2, print_out=True)
    
    if full_screening:
        print("\n\n" + "=" * 100)
        print("=== AVALIANDO TODAS AS AMEAÇAS DO ARQUIVO DE SCREENING PÓS-MANOBRA ===")
        print("=" * 100)
        
        # Para o screening completo, a estrutura do JSON tem 'sec_id', 'tca', 'secondary_id', etc.
        # Precisamos fazer fetch dos TLEs de forma diferente?
        # A função load_screening_results do optimize_maneuver mapeia isso perfeitamente.
        # Para simplificar aqui, vamos ler o catalog local igual fazemos via requestTles ou cache.
        from app.download_all_tles import requestTles
        all_tles = requestTles()
        tle_map = {int(item['NORAD_CAT_ID']): item for item in all_tles}
        
        # O arquivo screening não tem a linha TLE completa em todos (as vezes salva apenas id).
        # Vamos injetar o TLE nos itens antes do process_list.
        valid_screening_cands = []
        for cand in full_screening:
            s_id = int(cand['secondary_id'])
            if s_id in tle_map:
                cand["secondary_tle_line1"] = tle_map[s_id]['TLE_LINE1']
                cand["secondary_tle_line2"] = tle_map[s_id]['TLE_LINE2']
                valid_screening_cands.append(cand)
        
        # Avaliar e retornar resultados, sem printar um por um
        print("Avaliando candidatos do Screening original (isso pode levar alguns segundos)...")
        evaluated = process_list(valid_screening_cands, t_maneuver_date, utc, virtual_propagator, inertialFrame, virtual_tle, base_id, tle_p, p_tle1, p_tle2, print_out=False)
        
        # Filtrar apenas as que ocorreram DEPOIS da manobra
        post_maneuver_evals = [e for e in evaluated if not e.get("is_pre_maneuver", False)]
        
        # Ordenar os resultados baseados no kc_squared depositado depois da manobra
        sorted_screening = sorted(
            post_maneuver_evals,
            key=lambda x: (x.get("kc2_depois", float('inf')), x.get("dist_depois", float('inf')))
        )
        
        top5_new = sorted_screening[:5]
        
        print("\n\n" + "=" * 100)
        print("=== TOP 5 AMEAÇAS (MENOR KC2) DO SCREENING APOS A MANOBRA ===")
        print("=" * 100)
        
        for res in top5_new:
            # Se a métrica 'Antes' não existe (porque veio do screening cru), calculamos agora apenas para os Top 5
            if res.get('dist_antes') is None:
                sec_id_val = res['sec_id']
                tca_str_val = res['tca_antes']
                s_tle1 = res['conj_ref']['secondary_tle_line1']
                s_tle2 = res['conj_ref']['secondary_tle_line2']
                
                # Setup
                tle_s = TLE(s_tle1, s_tle2)
                prop_s = TLEPropagator.selectExtrapolator(tle_s)
                
                primary_data_orig = {
                    "TLE_LINE1": p_tle1, 
                    "TLE_LINE2": p_tle2,
                    "OBJECT_NAME": "PRIMARY_ORIGINAL",
                    "NORAD_CAT_ID": base_id
                }
                secondary_data = {
                    "TLE_LINE1": s_tle1, 
                    "TLE_LINE2": s_tle2,
                    "OBJECT_NAME": "SECONDARY_CANDIDATE",
                    "NORAD_CAT_ID": sec_id_val
                }
                
                search_start_orig = AbsoluteDate(tca_str_val, utc).shiftedBy(-60.0)
                times_o, dists_o, __ = bisectionMethod(search_start_orig, primary_data_orig, secondary_data, h=0.5)
                
                if times_o and len(times_o) >= 2:
                    best_idx_o = -1 if dists_o[-1] < dists_o[-2] else -2
                    new_tca_date_o = search_start_orig.shiftedBy(float(times_o[best_idx_o]))
                    min_dist_o = dists_o[best_idx_o]
                    
                    best_p_pv_o = prop_p_orig.getPVCoordinates(new_tca_date_o, inertialFrame)
                    best_s_pv_o = prop_s.getPVCoordinates(new_tca_date_o, inertialFrame)
                    
                    # Full states and analysis
                    p_pos_o = best_p_pv_o.getPosition()
                    p_vel_o = best_p_pv_o.getVelocity()
                    s_pos_o = best_s_pv_o.getPosition()
                    s_vel_o = best_s_pv_o.getVelocity()
                    
                    p_state_full_o = (new_tca_date_o, np.array([p_pos_o.getX(), p_pos_o.getY(), p_pos_o.getZ()]), np.array([p_vel_o.getX(), p_vel_o.getY(), p_vel_o.getZ()]), None)
                    s_state_full_o = (new_tca_date_o, np.array([s_pos_o.getX(), s_pos_o.getY(), s_pos_o.getZ()]), np.array([s_vel_o.getX(), s_vel_o.getY(), s_vel_o.getZ()]), None)
                    
                    try:
                        an_res_o = conjunctionAnalysis(
                            primary=primary_data_orig,
                            secondary=secondary_data,
                            tcaTime=new_tca_date_o,
                            verbose=False,
                            ellipsoid_bounds=GA_ELLIPSOID_BOUNDS,
                            primary_state_vector=p_state_full_o,
                            secondary_state_vector=s_state_full_o
                        )
                        res['dist_antes'] = min_dist_o
                        res['radial_antes'] = an_res_o.get('radial_dist_m', 0.0)
                        res['along_antes'] = an_res_o.get('along_track_dist_m', 0.0)
                        res['cross_antes'] = an_res_o.get('cross_track_dist_m', 0.0)
                        res['kc2_antes'] = an_res_o.get('kc_squared', 0.0)
                        res['tca_antes'] = new_tca_date_o.toString()
                    except:
                        pass
                
                # Fallbacks in case Bisection or Analysis fails
                res.setdefault('dist_antes', 0.0)
                res.setdefault('radial_antes', 0.0)
                res.setdefault('along_antes', 0.0)
                res.setdefault('cross_antes', 0.0)
                res.setdefault('kc2_antes', 0.0)
            
            # Recalculate differences dynamically
            dist_antes = res['dist_antes']
            diff_m = res['dist_depois'] - dist_antes
            rad_antes = res['radial_antes']
            al_antes = res['along_antes']
            cr_antes = res['cross_antes']
            k2_antes = res['kc2_antes']
            
            print(f"SEC_ID: {res['sec_id']} | TCA Pré-Manobra: {res['tca_antes'][:22]} | TCA Pós-Manobra: {res['tca_depois'][:22]}")
            print("-" * 100)
            print(f"{'Métrica':<18} | {'Antes':<15} | {'Depois':<15} | {'Diferença'}")
            print("-" * 100)
            print(f"{'Distância (m)':<18} | {dist_antes:<15.2f} | {res['dist_depois']:<15.2f} | {diff_m:+.2f}")
            print(f"{'Radial (m)':<18} | {rad_antes:<15.2f} | {res['radial_depois']:<15.2f} | {res['radial_depois'] - rad_antes:+.2f}")
            print(f"{'Along-Track (m)':<18} | {al_antes:<15.2f} | {res['along_depois']:<15.2f} | {res['along_depois'] - al_antes:+.2f}")
            print(f"{'Cross-Track (m)':<18} | {cr_antes:<15.2f} | {res['cross_depois']:<15.2f} | {res['cross_depois'] - cr_antes:+.2f}")
            print(f"{'Kc^2':<18} | {k2_antes:<15.2f} | {res['kc2_depois']:<15.2f} | {res['kc2_depois'] - k2_antes:+.2f}")
            print("=" * 100)

def process_list(conjunctions_list, t_maneuver_date, utc, virtual_propagator, inertialFrame, virtual_tle, base_id, tle_p, p_tle1, p_tle2, print_out=True):
    results = []
    
    # We will need prop_p_orig inside this function
    from org.orekit.propagation.analytical.tle import TLEPropagator
    prop_p_orig = TLEPropagator.selectExtrapolator(tle_p)
    
    for conj in sorted(conjunctions_list, key=lambda x: x.get("min_distance_m", float('inf'))):
        sec_id = conj.get("secondary_id", conj.get("sec_id"))
        tca_str = conj.get("tca_utc", conj.get("tca", "")).replace("Z", "")
        if not tca_str:
            continue
            
        tca_date = AbsoluteDate(tca_str, utc)
        
        dist_antes = conj.get("min_distance_m")
        kc2_antes = conj.get("kc_squared")
        radial_antes = conj.get("radial_dist_m")
        along_antes = conj.get("along_track_dist_m")
        cross_antes = conj.get("cross_track_dist_m")
        
        # Filtro Causal: Manobras no futuro do TCA não alteram a órbita no instante do TCA
        if tca_date.compareTo(t_maneuver_date) <= 0:
            current_p_prop = prop_p_orig
            current_p_tle = tle_p
            is_pre_maneuver = True
        else:
            current_p_prop = virtual_propagator
            current_p_tle = virtual_tle
            is_pre_maneuver = False
            
        # Secundario
        s_tle1 = conj["secondary_tle_line1"]
        s_tle2 = conj["secondary_tle_line2"]
        tle_s = TLE(s_tle1, s_tle2)
        prop_s = TLEPropagator.selectExtrapolator(tle_s)
        
        # Construir dados JSON mockados para enviar pro bisection
        primary_data = {
            "TLE_LINE1": current_p_tle.getLine1(), 
            "TLE_LINE2": current_p_tle.getLine2(),
            "OBJECT_NAME": "PRIMARY_EVAL",
            "NORAD_CAT_ID": base_id
        }
        secondary_data = {
            "TLE_LINE1": s_tle1, 
            "TLE_LINE2": s_tle2,
            "OBJECT_NAME": "SECONDARY_CANDIDATE",
            "NORAD_CAT_ID": sec_id
        }
        
        # O Bisection pede a data inicial de busca. Vamos iniciar 60 segundos antes do TCA original.
        search_start = tca_date.shiftedBy(-60.0)
        
        times, distances, __ = bisectionMethod(
            search_start,
            primary_data,
            secondary_data,
            h=0.5
        )
        
        if not times or len(times) < 2:
            if print_out:
                print(f"Bisection failed for {sec_id} at {tca_str}")
            new_tca_date = tca_date
            min_dist_new = float('inf')
            
            p_pos_new = current_p_prop.getPVCoordinates(new_tca_date, inertialFrame)
            s_pos_new = prop_s.getPVCoordinates(new_tca_date, inertialFrame)
            best_p_pv = p_pos_new
            best_s_pv = s_pos_new
        else:
            if distances[-1] < distances[-2]:
                best_idx = -1
            else:
                best_idx = -2
                
            new_tca_date = search_start.shiftedBy(float(times[best_idx]))
            min_dist_new = distances[best_idx]
            
            best_p_pv = current_p_prop.getPVCoordinates(new_tca_date, inertialFrame)
            best_s_pv = prop_s.getPVCoordinates(new_tca_date, inertialFrame)
            
        # Calcula diferença provando que dist_antes exista (no screening bruto ele é None)
        diff_m = (min_dist_new - dist_antes) if dist_antes is not None else 0.0
        
        # Extrair estados no instante exato da nova minima distancia
        p_pos = best_p_pv.getPosition()
        p_vel = best_p_pv.getVelocity()
        s_pos = best_s_pv.getPosition()
        s_vel = best_s_pv.getVelocity()
        
        p_pos_arr = np.array([p_pos.getX(), p_pos.getY(), p_pos.getZ()])
        p_vel_arr = np.array([p_vel.getX(), p_vel.getY(), p_vel.getZ()])
        s_pos_arr = np.array([s_pos.getX(), s_pos.getY(), s_pos.getZ()])
        s_vel_arr = np.array([s_vel.getX(), s_vel.getY(), s_vel.getZ()])
        
        p_state_full = (new_tca_date, p_pos_arr, p_vel_arr, None)
        s_state_full = (new_tca_date, s_pos_arr, s_vel_arr, None)
        
        try:
            analysis_result = conjunctionAnalysis(
                primary=primary_data,
                secondary=secondary_data,
                tcaTime=new_tca_date,
                verbose=False,
                ellipsoid_bounds=GA_ELLIPSOID_BOUNDS,
                primary_state_vector=p_state_full,
                secondary_state_vector=s_state_full
            )
            kc2_depois = analysis_result.get('kc_squared', 0.0)
            radial_depois = analysis_result.get('radial_dist_m', 0.0)
            along_depois = analysis_result.get('along_track_dist_m', 0.0)
            cross_depois = analysis_result.get('cross_track_dist_m', 0.0)
        except Exception as e:
            kc2_depois = 0.0
            radial_depois = 0.0
            along_depois = 0.0
            cross_depois = 0.0
            
        if print_out:
            print(f"SEC_ID: {sec_id} | TCA Pré-Manobra: {tca_str[:22]} | TCA Pós-Manobra: {new_tca_date.toString()[:22]}")
            print("-" * 100)
            print(f"{'Métrica':<18} | {'Antes':<15} | {'Depois':<15} | {'Diferença'}")
            print("-" * 100)
            if dist_antes is not None:
                print(f"{'Distância (m)':<18} | {dist_antes:<15.2f} | {min_dist_new:<15.2f} | {diff_m:+.2f}")
                print(f"{'Radial (m)':<18} | {radial_antes:<15.2f} | {radial_depois:<15.2f} | {radial_depois - radial_antes:+.2f}")
                print(f"{'Along-Track (m)':<18} | {along_antes:<15.2f} | {along_depois:<15.2f} | {along_depois - along_antes:+.2f}")
                print(f"{'Cross-Track (m)':<18} | {cross_antes:<15.2f} | {cross_depois:<15.2f} | {cross_depois - cross_antes:+.2f}")
                print(f"{'Kc^2':<18} | {kc2_antes:<15.2f} | {kc2_depois:<15.2f} | {kc2_depois - kc2_antes:+.2f}")
            else:
                print(f"{'Distância (m)':<18} | {'N/A':<15} | {min_dist_new:<15.2f} | N/A")
                print(f"{'Kc^2':<18} | {'N/A':<15} | {kc2_depois:<15.2f} | N/A")
            print("=" * 100)
            
        results.append({
            "ignored_causal": False,
            "sec_id": sec_id,
            "tca_antes": tca_str,
            "tca_depois": new_tca_date.toString(),
            "dist_antes": dist_antes,
            "dist_depois": min_dist_new,
            "diff_m": diff_m,
            "radial_antes": radial_antes,
            "radial_depois": radial_depois,
            "along_antes": along_antes,
            "along_depois": along_depois,
            "cross_antes": cross_antes,
            "cross_depois": cross_depois,
            "kc2_antes": kc2_antes,
            "kc2_depois": kc2_depois,
            "is_pre_maneuver": is_pre_maneuver,
            "conj_ref": conj  # Reference for Top 5
        })
    return results

if __name__ == "__main__":
    main()
