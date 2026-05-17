import os
import sys
import json
import logging
import time
import datetime
import numpy as np

# Adicione o Google Cloud SDKs
from google.cloud import aiplatform
from google.cloud.aiplatform.vizier import Study, Trial
from google.cloud.aiplatform.vizier import pyvizier as vz
from google.cloud import bigquery

# Import das lógicas originais do Orekit do seu repositório
file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.orekit_config import setup_orekit
setup_orekit()
from org.orekit.time import AbsoluteDate, TimeScalesFactory  # type: ignore

# Reaproveitar funções originais do seu pipeline
from cenario1.optimize_maneuver import (
    apply_gauss_variational_equations, 
    _evaluate_single_member_worker
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Configurações GCP
PROJECT_ID = "cosmos-project-479403"
LOCATION = "southamerica-east1"
BQ_DATASET = "cosmos_analytics"
from app.bigquery_adapter import fetch_screening_from_bigquery

def create_vizier_study(primary_id: str, t_tca_str: str) -> Study:
    """Cria um Estudo Black-Box no Vertex AI Vizier para a manobra"""
    aiplatform.init(project=PROJECT_ID, location=LOCATION)
    
    problem = vz.ProblemStatement()
    
    # Definindo o Espaço de Busca (Search Space) equivalente ao PyMoo
    # dt_maneuver: Entre 2 dias (-172800 s) e 1 hora (-3600 s) antes do TCA
    problem.search_space.root.add_float_param("dt_maneuver", -172800.0, -3600.0)
    
    # delta_v: Entre 0 e 0.5 m/s
    problem.search_space.root.add_float_param("delta_v", 0.0, 0.5)

    # Definindo a Métrica (Minimizar DeltaV, garantindo que violations seja 0)
    # Como Vizier lida bem com múltiplas métricas, podemos tratar violations como uma restrição rigorosa.
    problem.metric_information.append(
        vz.MetricInformation(name="delta_v_cost", goal=vz.ObjectiveMetricGoal.MINIMIZE)
    )
    problem.metric_information.append(
        vz.MetricInformation(
            name="constraint_violations", 
            goal=vz.ObjectiveMetricGoal.MINIMIZE
        )
    )

    study_id = f"maneuver-opt-{primary_id}-{int(time.time())}"
    
    study = Study.create_or_load(
        display_name=study_id,
        problem=problem,
        algorithm=vz.Algorithm.RANDOM_SEARCH # Para Bayesian Optimization, usamos vz.Algorithm.ALGORITHM_UNSPECIFIED
    )
    
    return study

def run_distributed_optimization(primary_id: int):
    logger.info(f"Iniciando integração Vizier para o satélite {primary_id}")
    
    # 1. Fetch de BigQuery
    try:
        t_tca_str, candidates = fetch_screening_from_bigquery(primary_id)
        logger.info(f"Encontrados {len(candidates)} candidatos de risco. TCA Base: {t_tca_str}")
    except Exception as e:
        logger.error(f"Falha ao obter dados do BigQuery: {e}")
        return
    
    # 2. Inicializa Vizier
    study = create_vizier_study(str(primary_id), t_tca_str)
    
    # 3. Execução em Batch / Distributed
    # Em produção, esse loop rodará distribuído (via Cloud Run Jobs escutando o Study)
    MAX_TRIALS = 40 # Substitui as 40 gerações iterativas locais
    
    logger.info("Solicitando sugestões do Vertex Vizier...")
    trials = study.suggest(count=5, worker="worker-1") # Pega um lote
    
    for trial in trials:
        dt_maneuver = trial.parameters["dt_maneuver"].value
        delta_v = trial.parameters["delta_v"].value
        
        # Array formatado para o _evaluate_single_member_worker
        X_array = [dt_maneuver, delta_v]
        
        logger.info(f"Trial {trial.name}: Testando dt={dt_maneuver:.1f}s | dV={delta_v:.4f}m/s")
        
        try:
            # 4. Avalia no Propagador (Orekit)
            ret_F, ret_G, ret_kc_list = _evaluate_single_member_worker((X_array, t_tca_str, candidates, 1, primary_id))
            
            # 5. Reporta Resultados de volta para o Google Vertex
            trial.add_measurement(
                metrics={
                    "delta_v_cost": float(ret_F),
                    "constraint_violations": float(ret_G)
                }
            )
            trial.complete()
        except Exception as e:
            trial.complete(infeasible_reason=f"Failed Orekit propagation: {str(e)}")

    logger.info("Estudo do Vertex AI concluído! Você pode ver os resultados no painel do Google Cloud.")

if __name__ == "__main__":
    # Teste rápido
    run_distributed_optimization(61046)
