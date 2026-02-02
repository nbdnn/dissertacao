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

# Configura Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Calcula conjunções para um satélite.")
    parser.add_argument(
        '--base', type=int, default=47699,
        help="NORAD ID do satélite base (Ex: 47699 Amazonia-1)"
    )
    parser.add_argument('--days', type=float, default=7.0, help="Dias de simulação")
    parser.add_argument(
        '--ellipsoid', nargs=3, type=float, default=[1000.0, 5000.0, 1000.0],
        help="Semieixos do elipsoide de segurança (R_U, R_V, R_W) em metros. Ex: 2000 10000 10000"
    )

    args = parser.parse_args()

    # Calcular threshold escalar baseado nas regras do elipsoide (100x maior eixo)
    # ou usar o argumento antigo se não for definido (mas aqui definimos um default)
    # Vamos priorizar a lógica do elipsoide pois é a nova regra de negócio.
    rc_u, rc_v, rc_w = args.ellipsoid
    max_axis = max(rc_u, rc_v, rc_w)
    sieve_threshold = max_axis

    logger.info(f"Elipsoide de Segurança: Radial={rc_u}m, In-Track={rc_v}m, Cross-Track={rc_w}m")
    logger.info(f"Threshold escalar para Sieve (max axis): {sieve_threshold}m")

    # 1. Setup Orekit
    logger.info("Inicializando Orekit...")
    setup_orekit()

    # 2. Baixar TLEs
    logger.info("Obtendo catálogo de TLEs...")
    all_cat = requestTles()

    if not all_cat:
        logger.error("Falha ao obter TLEs.")
        sys.exit(1)

    # 3. Preparar dados
    logger.info("Processando catálogo...")
    primary_data = None
    secondaries = []

    # start_epoch_str = datetime.now(timezone.utc).isoformat()

    for item in all_cat:
        norad_id = int(item['NORAD_CAT_ID'])
        # name = item['OBJECT_NAME']
        # line1 = item['TLE_LINE1']
        # line2 = item['TLE_LINE2']

        # sat = Satellite(norad_cat_id=norad_id, name=name)
        # tle_obj = TLEData(satellite=sat, tle_line1=line1, tle_line2=line2, epoch=start_epoch_str)

        # Ensure numeric types
        item['NORAD_CAT_ID'] = norad_id
        if "APOAPSIS" in item:
            item["APOAPSIS"] = float(item["APOAPSIS"])
        if "PERIAPSIS" in item:
            item["PERIAPSIS"] = float(item["PERIAPSIS"])

        # Default keys expected by sieve logic if missing (fallback)
        if "ECCENTRICITY" not in item:
            # Approximation or skip? Logic uses it for printing mostly,
            # but could be used in filters.
            pass

        if norad_id == args.base:
            primary_data = item
        else:
            secondaries.append(item)

    if not primary_data:
        logger.error(f"Satélite base {args.base} não encontrado no catálogo baixado.")
        # Fallback se não estiver no json recente (ex: acabou de decair ou falha)
        # sys.exit(1)
        # Vamos tentar um TLE hardcoded se for Amazonia-1 apenas para teste, ou abortar
        sys.exit(1)

    logger.info(f"Primário: {primary_data['OBJECT_NAME']} ({primary_data['NORAD_CAT_ID']})")
    logger.info(f"Secundários: {len(secondaries)} objetos.")

    # 4. Executar Algoritmo
    # utc = TimeScalesFactory.getUTC()
    # now_dt = datetime.now(timezone.utc)
    # now_orekit = AbsoluteDate(
    #    now_dt.year, now_dt.month, now_dt.day,
    #    now_dt.hour, now_dt.minute, float(now_dt.second),
    #    utc
    # )

    logger.info(f"Iniciando cálculo para {args.days} dias. (Threshold Sieve: {sieve_threshold}m)")
    start_time = time.time()

    results = sieveAlgorithm(
        primariesID=[primary_data["NORAD_CAT_ID"]],
        daysOfSimulation=args.days,
        threshold=sieve_threshold,
        ellipsoid_bounds=tuple(args.ellipsoid),
        verbose=False,  # Or args.verbose if added
        start_date=None,  # Uses real time
        tles=([primary_data], secondaries)
    )

    end_time = time.time()
    duration = end_time - start_time

    # 5. Resultados
    logger.info("=" * 60)
    logger.info(f"Cálculo finalizado em {duration:.2f} segundos.")
    logger.info(f"Conjunções detectadas: {len(results)}")
    logger.info("=" * 60)

    # Salvar em arquivo
    output_filename = f"conjunctions_{args.base}_{int(time.time())}.json"
    with open(output_filename, 'w') as f:
        json.dump(results, f, indent=2)

    # Exibir no console as top 5 mais perigosas (maior PoC ou menor dist)
    results.sort(key=lambda x: x['min_distance_m'])

    for c in results[:10]:
        print(f"⚠️  {c['secondary_name']} ({c['secondary_id']})")
        print(f"   🕒 TCA: {c['tca_utc']}")
        print(f"   📏 Dist: {c['min_distance_m']:.2f} m")
        print(f"   🎲 PoC: {c['poc_max']:.2e}")
        print("-" * 40)

    logger.info(f"Resultados salvos em {output_filename}")


if __name__ == "__main__":
    main()
