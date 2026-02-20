import sys
import argparse
import time
import json
import logging
import os

if __name__ == '__main__' and __package__ is None:
    # Hack to allow running this script directly while keeping relative imports
    file_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    __package__ = "app.conjunctions"

from ..orekit_config import setup_orekit
from ..download_all_tles import requestTles
from .sieve import sieveAlgorithm
from .config import ELLIPSOID_BOUNDS, SCREENING_MULTIPLIER

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Screening inicial de conjunções (10x Elipsoide)."
    )
    parser.add_argument('--base', type=int, default=47699, help="NORAD ID do satélite base")
    parser.add_argument('--days', type=float, default=7.0, help="Dias de simulação")
    parser.add_argument(
        '--start-date',
        type=str,
        help="Data de início (ISO: YYYY-MM-DDTHH:MM:SS) [Default: 2026-02-11 12:00:00 UTC]"
    )

    args = parser.parse_args()

    logger.info("Inicializando Orekit...")
    setup_orekit()

    # Determine Start Date
    start_date = None

    # 1. Try Argument
    if args.start_date:
        try:
            from datetime import datetime
            start_date = datetime.fromisoformat(args.start_date)
            logger.info(f"Data de início definida via argumento: {start_date}")
        except ValueError:
            logger.error(f"Formato de data inválido: {args.start_date}")
            sys.exit(1)

    # 2. Fallback to Fixed Default
    if not start_date:
        from datetime import datetime, timezone
        start_date = datetime(2026, 2, 11, 12, 0, 0, tzinfo=timezone.utc)
        logger.info(f"Data de início padrão aplicada: {start_date}")

    logger.info("Baixando catálogo de TLEs...")
    all_cat = requestTles()

    if not all_cat:
        logger.error("Falha ao obter TLEs.")
        sys.exit(1)

    primary_data = None
    secondaries = []

    # Process TLEs
    for item in all_cat:
        norad_id = int(item['NORAD_CAT_ID'])
        item['NORAD_CAT_ID'] = norad_id

        # Ensure numeric types for fields possibly used
        if "APOAPSIS" in item:
            item["APOAPSIS"] = float(item["APOAPSIS"])
        if "PERIAPSIS" in item:
            item["PERIAPSIS"] = float(item["PERIAPSIS"])

        if norad_id == args.base:
            primary_data = item
        else:
            secondaries.append(item)

    if not primary_data:
        logger.error(f"Satélite base {args.base} não encontrado.")
        sys.exit(1)

    # Configuração do Elipsoide de Screening (10x base)
    # Base: 1000, 5000, 1000 -> Screening: 10000, 50000, 10000
    base_bounds = ELLIPSOID_BOUNDS
    screening_bounds = tuple(SCREENING_MULTIPLIER * x for x in base_bounds)

    # Threshold definido como o maior componente do elipsoide de screening
    threshold = max(screening_bounds)

    logger.info(
        f"Screening Bounds (m): {screening_bounds} "
        f"(Base: {base_bounds} x {SCREENING_MULTIPLIER})"
    )
    logger.info(f"Sieve Threshold (m): {threshold}")
    logger.info(
        f"Analisando {len(secondaries)} objetos secundários contra {primary_data['OBJECT_NAME']}..."
    )

    start_time = time.time()

    results = sieveAlgorithm(
        primariesID=[primary_data["NORAD_CAT_ID"]],
        daysOfSimulation=args.days,
        threshold=threshold,
        ellipsoid_bounds=screening_bounds,
        verbose=False,
        tles=([primary_data], secondaries),
        verboseConjAnalysis=False,
        start_date=start_date,
        screening_mode=True
    )

    end_time = time.time()
    duration = end_time - start_time

    logger.info("=" * 60)
    logger.info(f"Screening finalizado em {duration:.2f} segundos.")
    logger.info(f"Candidatos encontrados: {len(results)}")
    logger.info("=" * 60)

    # Salvar resultados
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    screenings_dir = os.path.join(project_root, "screenings")
    os.makedirs(screenings_dir, exist_ok=True)

    output_filename = os.path.join(screenings_dir, f"screening_{args.base}_{int(time.time())}.json")
    with open(output_filename, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Lista de candidatos salva em: {output_filename}")

    # Preview
    if results:
        print("\nExemplo de candidatos encontrados:")
        for r in results[:5]:
            print(
                f"- {r['secondary_name']} ({r['secondary_id']}): ",
                f"TCA {r['tca']} | kc2={r['kc2']:.2f}"
            )


if __name__ == '__main__':
    main()
