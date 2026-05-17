import base64
import json
import logging
import os
import google.auth
from google.cloud import run_v2

logger = logging.getLogger(__name__)

# Configurações GCP
PROJECT_ID = os.environ.get("PROJECT_ID", "cosmos-project-479403")
REGION = os.environ.get("REGION", "southamerica-east1")
JOB_NAME = os.environ.get("JOB_NAME", "vizier-optimizer-job")

def trigger_camo_job(event, context):
    """
    Função Cloud (Triggered via Eventarc / PubSub) 
    acionada quando um novo registro de conjunção de alto risco
    é inserido no BigQuery (cosmos_analytics.conjunction_screenings).
    """
    if 'data' in event:
        # A mensagem do Pub/Sub vem encodada em base64
        pubsub_message = base64.b64decode(event['data']).decode('utf-8')
        logger.info(f"Recebido evento do Pub/Sub: {pubsub_message}")
        try:
            payload = json.loads(pubsub_message)
            primary_id = payload.get("primary_id")
            
            if primary_id:
                logger.info(f"Disparando otimização CAMO (Cloud Run Job) para o satélite {primary_id}")
                _start_cloud_run_job(primary_id)
            else:
                logger.warning("Nenhum primary_id encontrado no payload do evento.")
        except Exception as e:
            logger.error(f"Erro ao decodificar JSON do evento: {e}")

def _start_cloud_run_job(primary_id: int):
    """Aciona a execução do Cloud Run Job configurado passando o primary_id como variável de ambiente ou override."""
    try:
        # Cria o cliente do Cloud Run
        client = run_v2.JobsClient()
        
        # Constrói o caminho completo do Job
        job_path = client.job_path(PROJECT_ID, REGION, JOB_NAME)
        
        # Configura as sobreposições para a execução
        overrides = run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[
                        run_v2.EnvVar(name="PRIMARY_ID", value=str(primary_id))
                    ]
                )
            ]
        )
        
        request = run_v2.RunJobRequest(
            name=job_path,
            overrides=overrides
        )
        
        logger.info(f"Iniciando Cloud Run Job {JOB_NAME} para satélite {primary_id}...")
        operation = client.run_job(request=request)
        
        logger.info(f"Operação submetida com sucesso. Nome: {operation.operation.name}")
        
    except Exception as e:
        logger.error(f"Falha ao iniciar o Cloud Run Job: {e}")

# Para testes locais:
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dummy_event = {
        'data': base64.b64encode(json.dumps({"primary_id": 61046}).encode('utf-8'))
    }
    trigger_camo_job(dummy_event, None)
