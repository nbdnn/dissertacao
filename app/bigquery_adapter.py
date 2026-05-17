import logging
from google.cloud import bigquery
from typing import List, Tuple
from cenario1.optimize_maneuver import ConjunctionCandidate

logger = logging.getLogger(__name__)

# Configurações GCP
PROJECT_ID = "cosmos-project-479403"
BQ_DATASET = "cosmos_analytics"
BQ_TABLE_SCREENING = "conjunction_screenings"

def fetch_screening_from_bigquery(primary_id: int) -> Tuple[str, List[ConjunctionCandidate]]:
    """
    Substitui a leitura de JSON por uma query agregada no BigQuery.
    Lê o banco para obter os eventos e cruza com os TLEs vigentes mais recentes.
    Retorna a menor data de TCA como string e a lista de ConjunctionCandidates.
    """
    client = bigquery.Client(project=PROJECT_ID)
    
    query = f"""
        SELECT 
            tca_utc, 
            secondary_id, 
            primary_tle_line1, primary_tle_line2, 
            secondary_tle_line1, secondary_tle_line2
        FROM `{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE_SCREENING}`
        WHERE primary_id = @primary_id
        AND is_latest = TRUE
        ORDER BY tca_utc ASC
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("primary_id", "INT64", primary_id)]
    )
    
    logger.info(f"Fazendo query no BigQuery para o satélite primário {primary_id}...")
    query_job = client.query(query, job_config=job_config)
    results = query_job.result()
    
    candidates = []
    first_tca = None
    
    from org.orekit.time import AbsoluteDate, TimeScalesFactory # type: ignore
    utc = TimeScalesFactory.getUTC()
    
    for row in results:
        # A API Python BigQuery retorna datetime para TIMESTAMP, ou string
        # Vamos normalizar para string como Orekit espera
        tca_str = row.tca_utc if isinstance(row.tca_utc, str) else row.tca_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")
        tca_str = tca_str.replace("Z", "")
        
        tca_date = AbsoluteDate(tca_str, utc)
        
        if first_tca is None or tca_date.compareTo(first_tca) < 0:
            first_tca = tca_date
            
        cand = ConjunctionCandidate(
            sec_id=row.secondary_id,
            tca_str=tca_str,
            p_tle1=row.primary_tle_line1,
            p_tle2=row.primary_tle_line2,
            s_tle1=row.secondary_tle_line1,
            s_tle2=row.secondary_tle_line2
        )
        candidates.append(cand)
        
    if not candidates:
        raise ValueError(f"Nenhum evento de triagem válido encontrado no BigQuery para {primary_id}.")
        
    return first_tca.toString(), candidates
