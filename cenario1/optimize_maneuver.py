import os
import sys
import json
import logging
import time
import datetime
import traceback
import multiprocessing
import numpy as np
import matplotlib.pyplot as plt
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pymoo.core.problem import Problem, ElementwiseProblem
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from pymoo.termination import get_termination

# Configuração do Satélite Primário
PRIMARY_ID = 65774  # Altere este ID para o satélite que deseja otimizar

# Setup paths to ensure we can import 'app'
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Initialize Orekit early
from app.orekit_config import setup_orekit
setup_orekit()

from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore
from org.orekit.propagation.analytical.tle import TLE, TLEPropagator  # type: ignore
from org.orekit.orbits import KeplerianOrbit, PositionAngleType  # type: ignore
from org.orekit.frames import FramesFactory  # type: ignore
from org.orekit.propagation.analytical import KeplerianPropagator  # type: ignore
from org.orekit.propagation import SpacecraftState  # type: ignore
from org.orekit.propagation.conversion.osc2mean import FixedPointConverter # type: ignore
from org.hipparchus.geometry.euclidean.threed import Vector3D  # type: ignore
from app.conjunctions.conjunction_analysis import conjunctionAnalysis
from app.conjunctions.config import GA_ELLIPSOID_BOUNDS
from app.download_all_tles import requestTles

# Constante gravitacional da Terra no Orekit (WGS84)
from org.orekit.utils import Constants  # type: ignore
MU = Constants.WGS84_EARTH_MU / 1e9  # km^3/s^2. WGS84 MU is in m^3/s^2

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class ConjunctionCandidate:
    def __init__(self, sec_id, tca_str, p_tle1, p_tle2, s_tle1, s_tle2):
        self.sec_id = sec_id
        self.tca_str = tca_str
        self.p_tle1 = p_tle1
        self.p_tle2 = p_tle2
        self.s_tle1 = s_tle1
        self.s_tle2 = s_tle2

def load_screening_results(filepath: str, primary_id: int):
    """Lê o arquivo de screening real, faz fetch de todos os TLEs e monta os candidatos."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    if not data:
        raise ValueError("O arquivo de screening está vazio!")
        
    logger.info("Fazendo fetch do catálogo de TLEs para montar os candidatos...")
    all_tles = requestTles()
    tle_map = {int(item['NORAD_CAT_ID']): item for item in all_tles}
    
    if primary_id not in tle_map:
        raise ValueError(f"Primário {primary_id} não encontrado no catálogo de TLEs!")
        
    p_tle = tle_map[primary_id]
    p_tle1 = p_tle['TLE_LINE1']
    p_tle2 = p_tle['TLE_LINE2']
    
    utc = TimeScalesFactory.getUTC()
    candidates = []
    first_tca = None
    
    for item in data:
        sec_id = int(item['secondary_id'])
        if sec_id not in tle_map:
            logger.warning(f"Secundário {sec_id} ignorado pois faltam TLEs.")
            continue
            
        tca_str = item['tca'].replace("Z", "")
        tca_date = AbsoluteDate(tca_str, utc)
        
        if first_tca is None or tca_date.compareTo(first_tca) < 0:
            first_tca = tca_date
            
        s_tle = tle_map[sec_id]
        
        candidates.append(ConjunctionCandidate(
            sec_id=sec_id,
            tca_str=tca_str,
            p_tle1=p_tle1,
            p_tle2=p_tle2,
            s_tle1=s_tle['TLE_LINE1'],
            s_tle2=s_tle['TLE_LINE2']
        ))
        
    if not candidates:
        raise ValueError("Nenhum alvo de screening válido foi pareado com TLE.")
        
    return first_tca.toString(), candidates

def apply_gauss_variational_equations(a: float, e: float, i: float, raan: float, arg_p: float, f: float, delta_v_ms: float) -> tuple:
    """ Equações Variacionais de Gauss para impulso Along-Track. """
    dv_km_s = delta_v_ms / 1000.0
    p = a * (1 - e**2)
    h = np.sqrt(MU * p)
    r = p / (1 + e * np.cos(f))
    
    da = (2 * a**2 * p / (h * r)) * dv_km_s
    de = (1 / h) * ((p + r) * np.cos(f) + r * e) * dv_km_s
    di = 0.0
    draan = 0.0
    
    if e > 1e-12:
        darg_p = ((p + r) * np.sin(f) / (h * e)) * dv_km_s
    else:
        darg_p = 0.0
        
    return a + da, max(0.0, e + de), i + di, raan + draan, arg_p + darg_p, f

def evaluate_trajectory_screening(propagator_primary, candidates, t_maneuver_date, virtual_p_tle1=None, virtual_p_tle2=None):
    """ 
    Filtro de causalidade e avaliação de screening.
    Retorna uma lista contendo o sec_id e o respectivo kc^2 de cada encontro avaliado.
    """
    utc = TimeScalesFactory.getUTC()
    inertialFrame = FramesFactory.getEME2000()
    
    evaluated_conjunctions = []
    
    for cand in candidates:
        cand_tca_date = AbsoluteDate(cand.tca_str, utc)
        
        if cand_tca_date.compareTo(t_maneuver_date) <= 0:
            continue  # Filtro de Causalidade: ignora eventos no passado da manobra
        
        # Propagar secundário com TLE
        tle_s = TLE(cand.s_tle1, cand.s_tle2)
        prop_s = TLEPropagator.selectExtrapolator(tle_s)
        
        # Busca fina do novo TCA em torno do tca_date_original
        # Devido ao pequeno DV, a nova conjunção deve estar perto
        search_start = cand_tca_date.shiftedBy(-30.0)
        search_end = cand_tca_date.shiftedBy(30.0)
        
        step = 0.5
        curr_time = search_start
        min_dist = float('inf')
        new_tca_date = cand_tca_date
        
        # Guardar estados para o Conjunction Analysis
        best_p_pv = None
        best_s_pv = None
        
        while curr_time.compareTo(search_end) <= 0:
            p_pv = propagator_primary.getPVCoordinates(curr_time, inertialFrame)
            s_pv = prop_s.getPVCoordinates(curr_time, inertialFrame)
            
            dist = Vector3D.distance(p_pv.getPosition(), s_pv.getPosition())
            if dist < min_dist:
                min_dist = dist
                new_tca_date = curr_time
                best_p_pv = p_pv
                best_s_pv = s_pv
            
            curr_time = curr_time.shiftedBy(step)
            
        # Reformatar o estado para a pipeline conjunctionAnalysis
        if best_p_pv is not None and best_s_pv is not None:
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
            
            # Precisamos fingir ser JSON primary/secondary object para a conjunctionAnalysis
            # Use the virtual TLEs if provided, otherwise fallback to the original primary TLEs
            p_line1_for_ca = virtual_p_tle1 if virtual_p_tle1 else cand.p_tle1
            p_line2_for_ca = virtual_p_tle2 if virtual_p_tle2 else cand.p_tle2

            primary_data = {
                "TLE_LINE1": p_line1_for_ca, 
                "TLE_LINE2": p_line2_for_ca,
                "OBJECT_NAME": "PRIMARY_VIRTUAL",
                "NORAD_CAT_ID": 0
            }
            secondary_data = {
                "TLE_LINE1": cand.s_tle1, 
                "TLE_LINE2": cand.s_tle2,
                "OBJECT_NAME": "SECONDARY_CANDIDATE",
                "NORAD_CAT_ID": cand.sec_id
            }
            
            # Check usando a funcao real
            kc2 = float('inf')  # Inicializa como seguro
            ca_dict = {
                "primary_id": PRIMARY_ID,
                "secondary_id": cand.sec_id,
                "tca_utc": new_tca_date.toString(),
                "min_distance_m": min_dist,
                "kc_squared": kc2,
                "primary_tle_line1": p_line1_for_ca,
                "primary_tle_line2": p_line2_for_ca,
                "secondary_tle_line1": cand.s_tle1,
                "secondary_tle_line2": cand.s_tle2
            }
            try:
                # O ellipsoid_bounds padrão da config do projeto é 20, 20, 20. Usa-se (20,20,20)
                # Para maior seguranca no GA, usamos o GA_ELLIPSOID_BOUNDS (5000, 20000, 5000)
                analysis_result = conjunctionAnalysis(
                    primary=primary_data,
                    secondary=secondary_data,
                    tcaTime=new_tca_date,
                    verbose=False,
                    ellipsoid_bounds=GA_ELLIPSOID_BOUNDS,
                    primary_state_vector=p_state_full,
                    secondary_state_vector=s_state_full
                )
                if 'kc_squared' in analysis_result:
                    ca_dict.update(analysis_result)
                    kc2 = analysis_result['kc_squared']
                elif min_dist < 20.0:
                    kc2 = 0.0 # Aproximacao ruim para colisão pura sem kc2
                    ca_dict["kc_squared"] = 0.0
            except Exception as e:
                # Fallback on distance threshold Se falhar por causa da covariance nula
                logger.warning(f"Falha ao avaliar kc2 do SEC_{cand.sec_id}: {repr(e)}")
                if min_dist < 20.0:
                    kc2 = 0.0
                    ca_dict["kc_squared"] = 0.0
                    
            evaluated_conjunctions.append(ca_dict)

    return evaluated_conjunctions

# Variável global para evitar recriar as 12 JVMs a cada geração do PyMoo
_global_executor = None

def get_executor():
    global _global_executor
    if _global_executor is None:
        _global_executor = ProcessPoolExecutor(
            max_workers=12, 
            mp_context=multiprocessing.get_context('spawn')
        )
    return _global_executor

def _evaluate_single_member_worker(args):
    x, t_tca_str, candidates, current_seed = args
    import jpype
    if not jpype.isThreadAttachedToJVM():
        jpype.attachThreadToJVM()
        
    dt_maneuver = x[0]
    delta_v = x[1]
    
    utc = TimeScalesFactory.getUTC()
    inertialFrame = FramesFactory.getEME2000()
    
    t_tca_date = AbsoluteDate(t_tca_str, utc)
    t_maneuver_date = t_tca_date.shiftedBy(float(dt_maneuver))
    
    p_tle1 = candidates[0].p_tle1
    p_tle2 = candidates[0].p_tle2
    
    tle_p = TLE(p_tle1, p_tle2)
    prop_p_orig = TLEPropagator.selectExtrapolator(tle_p)
    
    try:
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
        
        vp_line1 = virtual_tle.getLine1()
        vp_line2 = virtual_tle.getLine2()
        
        evaluated_conjunctions = evaluate_trajectory_screening(
            virtual_propagator, candidates, t_maneuver_date, 
            virtual_p_tle1=vp_line1, virtual_p_tle2=vp_line2
        )
        
        violations = sum(1 for c in evaluated_conjunctions if c["kc_squared"] < 1.0)
        
        ret_F = delta_v
        ret_G = violations
        ret_kc_list = evaluated_conjunctions
        
    except Exception as e:
        logger.error(f"Erro na propagação da manobra virtual: {e}")
        ret_F = 1e6
        ret_G = 100
        ret_kc_list = []
        
    print(f"\r[Seed {current_seed}] dt_maneuver: {dt_maneuver/3600.0:.2f}h | delta_V: {delta_v:.4f} m/s      ", end="", flush=True)
    return ret_F, ret_G, ret_kc_list

class CollisionAvoidanceOptimization(Problem):
    def __init__(self, t_tca_str: str, candidates):
        self.t_tca_str = t_tca_str
        self.candidates = candidates
        
        # Limites das variaveis:
        # x_0: t_maneuver em segundos relativos a t_tca_date 
        # (t_tca - 2 dias) <= x_0 <= (t_tca - 1 hora)
        # x_1: delta_V em m/s
        dois_dias = 2 * 24 * 3600.0
        uma_hora = 3600.0
        
        xl = np.array([-dois_dias, 0.0])
        xu = np.array([-uma_hora, 0.5])
        
        super().__init__(n_var=2, n_obj=1, n_ieq_constr=1, xl=xl, xu=xu)

    def _evaluate(self, X, out, *args, **kwargs):
        X = np.atleast_2d(X)
        current_seed = getattr(self, "current_seed", "TEST")
        worker_args = [(X[i], self.t_tca_str, self.candidates, current_seed) for i in range(len(X))]
        
        executor = get_executor()
        results = list(executor.map(_evaluate_single_member_worker, worker_args))
            
        out["F"] = np.column_stack([res[0] for res in results])
        out["G"] = np.column_stack([res[1] for res in results])
        out["kc2_list"] = [res[2] for res in results]

def run_test():
    """Função para extrair logs e instanciar o setup de screening."""
    import glob
    # Busca apenas screenings do primary_id configurado
    pattern = os.path.join(project_root, "screenings", f"screening_{PRIMARY_ID}_*.json")
    files = glob.glob(pattern)
    
    if not files:
        logger.error(f"Nenhum arquivo de screening encontrado para o PRIMARY_ID {PRIMARY_ID} em {pattern}")
        # Tenta buscar qualquer screening se o específico não existir, para não travar o script?
        # Ou melhor travar para garantir que o usuário saiba que não achou o alvo correto.
        logger.info("Dica: Verifique se o arquivo screenings/screening_{PRIMARY_ID}_*.json existe.")
        sys.exit(1)
        
    # Seleciona o mais recente com base no tempo de modificação
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"Otimizando PRIMARY_ID {PRIMARY_ID} usando o screening mais recente: {latest_file}")
    print(f"Otimizando PRIMARY_ID {PRIMARY_ID} usando o screening mais recente: {latest_file}")
    
    primary_id = PRIMARY_ID
    
    # 1. Extração
    t_tca_str, candidates = load_screening_results(latest_file, primary_id)
    logger.info(f"Primeiro TCA encontrado: {t_tca_str} (Total candidates c/ TLE: {len(candidates)})")
    
    # 2. Avaliação simulada de uma partícula
    problem = CollisionAvoidanceOptimization(t_tca_str, candidates)
    
    # Test point: Maneuver 1.5 days before TCA, deltaV = 0.1 m/s
    dt_maneuver_test = -1.5 * 24 * 3600.0
    dv_test = 0.1
    x_test = np.array([dt_maneuver_test, dv_test])
    out = {}
    
    logger.info(f"Executando pseudo-_evaluate para dt_maneuver={dt_maneuver_test}s, dv={dv_test}m/s")
    problem._evaluate(x_test, out)
    logger.info(f"Avaliação do teste finalizou com: F={out.get('F')}, G={out.get('G')}")
    
    return problem

def run_optimization_campaign():
    problem = run_test()
    
    num_seeds = 10
    all_histories = []
    
    logger.info(f"Iniciando campanha de otimização pymoo ...")
    
    valid_solutions = []
    
    for seed in range(1, num_seeds + 1):
        problem.current_seed = seed
        algorithm = GA(pop_size=100, eliminate_duplicates=True)
        termination = get_termination("n_gen", 60)
        
        logger.info(f"========== INICIANDO OTIMIZAÇÃO - SEED: {seed}/{num_seeds} ==========")
        res = minimize(problem,
                       algorithm,
                       termination,
                       seed=seed,
                       save_history=True,
                       verbose=True)
        all_histories.append((seed, res))
        
        if res.F is not None:
            # Recupera a lista kc2 do ótimo (res.X)
            # Como salvamos em out["kc2_list"], nós precisamos reavaliar o ótimo? 
            # pymoo res.opt[0] deve conter os valores customizados no algoritmo em si se setados, caso contrário
            # fazemos uma avaliação extra simples:
            x_best = res.X
            out_best = {}
            problem._evaluate(x_best, out_best)
            best_kc2_list = out_best.get("kc2_list", [[]])[0]
            
            # Ordenar por kc_squared e min_distance_m
            sorted_conjunctions = sorted(
                best_kc2_list, 
                key=lambda x: (x.get("kc_squared", float('inf')), x.get("min_distance_m", float('inf')))
            )
            top5_threats = sorted_conjunctions[:5]
            
            logger.info(f"   Melhor solucao Seed {seed}: dt_Maneuver={res.X[0]:.2f}s, dV={res.X[1]:.4f} m/s | Obj={res.F[0]:.4f} | Constr={res.G[0]}")
            valid_solutions.append({
                "seed": seed,
                "dt_maneuver_s": res.X[0],
                "delta_v_ms": res.X[1],
                "objective_dv": res.F[0],
                "constraint_violations": res.G[0],
                "conjunctions_status": best_kc2_list
            })
            
            # Salvar top 5 threats em arquivo separado
            top5_file = os.path.join(project_root, "cenario1", f"{PRIMARY_ID}_seed_{seed}_top5_threats.json")
            with open(top5_file, "w") as f:
                json.dump(top5_threats, f, indent=4)
            
            # Salvar por seed imediamente para backup
            seed_file = os.path.join(project_root, "cenario1", f"{PRIMARY_ID}_seed_{seed}_solution.json")
            with open(seed_file, "w") as f:
                json.dump(valid_solutions[-1], f, indent=4)
                
        else:
            logger.info(f"   Nenhuma solução válida encontrada no Seed {seed}")

    # Salvar soluções em JSON
    solutions_file = os.path.join(project_root, "cenario1", f"{PRIMARY_ID}_optimization_solutions_{int(time.time())}.json")
    with open(solutions_file, "w") as f:
        json.dump(valid_solutions, f, indent=4)
    logger.info(f"Soluções salvas em {solutions_file}")

    # Plotar Curvas de Convergência
    plt.figure(figsize=(10, 6))
    
    for seed, res in all_histories:
        if res.history is None:
            continue
            
        n_evals = []
        opt = []
        
        generations = len(res.history)
        for gen in range(generations):
            algo_snapshot = res.history[gen]
            
            pop = algo_snapshot.pop
            feas = (pop.get("CV") <= 0.0).flatten()
            
            if np.any(feas):
                best_valid_f = pop[feas].get("F").min()
                opt.append(best_valid_f)
            else:
                if len(opt) > 0:
                    opt.append(opt[-1])
                else:
                    opt.append(np.nan)
                    
            n_evals.append(gen + 1)
            
        plt.plot(n_evals, opt, label=f"Seed {seed}", marker='.', alpha=0.7)

    plt.title(f"Convergência do Otimizador GA (Apenas Soluções Válidas - Satélite {PRIMARY_ID})")
    plt.xlabel("Geração")
    plt.ylabel(r"Objetivo Mínimo: $\Delta V$ (m/s) Consumido")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"cenario1/{PRIMARY_ID}_convergence_plot_pymoo.png", dpi=150)
    logger.info(f"Plot saved in cenario1/{PRIMARY_ID}_convergence_plot_pymoo.png")

if __name__ == "__main__":
    run_optimization_campaign()
